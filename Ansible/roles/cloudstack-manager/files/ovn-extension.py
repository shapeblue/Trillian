#!/usr/bin/env python3
#
# Apache CloudStack NetworkOrchestrator extension for OVN.
#
# This file is intentionally self-contained.  Deploy it as
# /usr/share/cloudstack-management/extensions/ovn-extension/ovn-extension.py
# and register it in CloudStack with relative_path pointing directly at
# the .py file.
#
# Required runtime packages on each management server:
#   python3-ovsdbapp python3-ovs
#
# Typical physical-network extension details (registered via cmk registerExtension):
#   ovn_nb_connection=tcp:10.0.0.11:6641,tcp:10.0.0.12:6641,tcp:10.0.0.13:6641
#   ovn_sb_connection=tcp:10.0.0.11:6642,tcp:10.0.0.12:6642,tcp:10.0.0.13:6642
#   ovn_physnet=cloudstack-public
#   gateway_chassis=gw-a:100:system,gw-b:90:netdev
#   metadata_mode=static-route
#   metadata_store=/var/lib/cloudstack/ovn-extension/metadata
#
# Invocation protocol (CloudStack >= network-extension-v2 framework):
#
#   ovn-extension.py <command> <payload-file> [<timeout-seconds>]
#
# Special-case operator shortcut:
#   ovn-extension.py capabilities
#
# The payload-file is a JSON object with the envelope:
#   {
#     "physical-network-extension-details": { <physical-network registration details> },
#     "network-extension-details":          { <stored extension.details for this network> },
#     "payload":                            { <command-specific fields> }
#   }
#
# Exception: "custom-action" uses a flat top-level structure (no nested "payload");
# it still includes "physical-network-extension-details" and "network-extension-details".
#
# In addition to the documented commands, this script also accepts:
#   sync (via custom-action --action sync --action-params <json>)
#   capabilities
#   serve-metadata --listen <ip> --port <port>
#
# Desired-state schema for sync is intentionally broad.  All sections are
# optional.  Example:
# {
#   "network": {"id": "42", "vpc_id": "7", "cidr": "10.0.0.0/24",
#               "gateway": "10.0.0.1", "vlan": "100",
#               "extension_ip": "10.0.0.1", "routing_mode": "routed"},
#   "public": {"ip": "203.0.113.5", "cidr": "203.0.113.5/24",
#              "gateway": "203.0.113.1", "vlan": "300"},
#   "nat": {"source_nat": {"public_ip": "203.0.113.5",
#                          "logical_ip": "10.0.0.0/24"},
#           "static_nats": [{"id": "sn1", "public_ip": "203.0.113.6",
#                            "private_ip": "10.0.0.10"}],
#           "port_forwards": [{"id": "pf1", "public_ip": "203.0.113.5",
#                              "public_port": "2222", "private_ip": "10.0.0.10",
#                              "private_port": "22", "protocol": "tcp"}]},
#   "firewall": {"default_egress_allow": true, "rules": [...]},
#   "dhcp": {"subnets": [...], "leases": [...]},
#   "dns": {"records": [{"hostname": "vm1", "ip": "10.0.0.10"}]},
#   "load_balancers": [...],
#   "security_groups": [...]
# }

from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import http.server
import ipaddress
import json
import logging
import os
import pathlib
import random
import re
import socketserver
import sys
import tempfile
import time
import urllib.parse
import uuid as _uuid
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple


OWNER = "cloudstack-ovn-network-extension"
EXT_ID_PREFIX = "cloudstack:"
METADATA_IP = "169.254.169.254"
DEFAULT_TIMEOUT = 15
DEFAULT_METADATA_STORE = "/var/lib/cloudstack/ovn-extension/metadata"


LOG = logging.getLogger("ovn-extension")

LOG_FILE = os.environ.get(
    "OVN_EXTENSION_LOG_FILE",
    "/var/log/cloudstack/management/ovs-extension.log",
)
LOG_FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG.setLevel(logging.DEBUG)

fh = logging.FileHandler(LOG_FILE)
fh.setFormatter(logging.Formatter(LOG_FMT))
LOG.addHandler(fh)


class ExtensionError(RuntimeError):
    """Raised for operator/configuration errors that should fail the command."""


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def maybe_json(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def decode_json_payload(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        decoded = base64.b64decode(text, validate=False).decode("utf-8")
        return json.loads(decoded)
    except Exception as exc:
        raise ExtensionError(f"cannot decode JSON payload: {exc}") from exc



def list_csv(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def first_present(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


def sanitize_symbol(value: Any, prefix: str = "cs") -> str:
    text = re.sub(r"[^A-Za-z0-9_.]", "_", str(value or ""))
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = prefix
    if not re.match(r"^[A-Za-z_.]", text):
        text = f"{prefix}_{text}"
    return text[:250]


def safe_name(*parts: Any, max_len: int = 120) -> str:
    text = "-".join(str(p) for p in parts if p not in (None, ""))
    text = re.sub(r"[^A-Za-z0-9_.:-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if len(text) <= max_len:
        return text
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"{text[:max_len - 13]}-{digest}"


def stable_mac(seed: Any) -> str:
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
    return "fa:16:3e:%02x:%02x:%02x" % (digest[0], digest[1], digest[2])


def ip_version(value: str) -> int:
    text = str(value).split("/")[0]
    return ipaddress.ip_address(text).version


def cidr_prefix(cidr: str) -> int:
    return ipaddress.ip_network(cidr, strict=False).prefixlen


def host_cidr(ip_value: str, cidr: Optional[str]) -> str:
    if not cidr:
        return ip_value
    network = ipaddress.ip_network(cidr, strict=False)
    return f"{ip_value}/{network.prefixlen}"


def normalize_port_range(value: Any) -> str:
    if value is None or value == "":
        return ""
    text = str(value).strip()
    if ":" in text:
        text = text.replace(":", "-", 1)
    if "-" in text:
        left, right = [int(p) for p in text.split("-", 1)]
        if left > right:
            left, right = right, left
        return f"{left}-{right}"
    return str(int(text))


def port_range_bounds(value: Any) -> Tuple[int, int]:
    text = normalize_port_range(value)
    if not text:
        raise ExtensionError("port range is empty")
    if "-" in text:
        left, right = text.split("-", 1)
        return int(left), int(right)
    port = int(text)
    return port, port


def protocol_match(protocol: str, port_range: Any = None, direction: str = "dst") -> str:
    proto = (protocol or "all").lower()
    if proto in {"all", "any", "ip"}:
        return "ip"
    if proto == "icmp":
        return "icmp4"
    if proto in {"icmp6", "ipv6-icmp"}:
        return "icmp6"
    if proto not in {"tcp", "udp", "sctp"}:
        raise ExtensionError(f"unsupported protocol: {protocol}")
    if not port_range:
        return proto
    left, right = port_range_bounds(port_range)
    field = f"{proto}.{direction}"
    if left == right:
        return f"{proto} && {field} == {left}"
    return f"{proto} && {left} <= {field} && {field} <= {right}"


def ip_set_expr(field: str, values: Sequence[str], fallback: Optional[str] = None) -> str:
    items = [v for v in values if v]
    if not items and fallback:
        items = [fallback]
    if not items:
        return ""
    if len(items) == 1:
        return f"{field} == {items[0]}"
    return f"{field} == {{{', '.join(items)}}}"


def merge_ext_ids(row: Any, updates: Mapping[str, Any]) -> Dict[str, str]:
    current = dict(getattr(row, "external_ids", {}) or {}) if row is not None else {}
    for key, value in updates.items():
        if value is None:
            current.pop(key, None)
        else:
            current[str(key)] = str(value)
    return current


def ext_ids(**kwargs: Any) -> Dict[str, str]:
    data = {
        f"{EXT_ID_PREFIX}owner": OWNER,
        f"{EXT_ID_PREFIX}managed-by": "cloudstack-network-extension",
        f"{EXT_ID_PREFIX}updated-at": str(int(time.time())),
    }
    for key, value in kwargs.items():
        if value is None:
            continue
        data[f"{EXT_ID_PREFIX}{key.replace('_', '-')}"] = str(value)
    return data


def row_uuid(row: Any) -> str:
    return str(getattr(row, "uuid", row))


def row_name(row: Any) -> str:
    return str(getattr(row, "name", row_uuid(row)))


def row_external_ids(row: Any) -> Dict[str, str]:
    return dict(getattr(row, "external_ids", {}) or {})


def row_options(row: Any) -> Dict[str, str]:
    return dict(getattr(row, "options", {}) or {})


def is_owned(row: Any) -> bool:
    return row_external_ids(row).get(f"{EXT_ID_PREFIX}owner") == OWNER


def _diag_serialize(val: Any) -> Any:
    """Recursively convert an OVN column value to a JSON-serializable form.

    Handles the types that ovsdbapp returns for NB/SB table columns:
    plain scalars, dicts, lists, sets, uuid.UUID, and Row references.
    Row references are serialized as {"uuid": "...", "name": "..."} to
    avoid recursive expansion and circular references.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, _uuid.UUID):
        return str(val)
    if isinstance(val, dict):
        return {str(k): _diag_serialize(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_diag_serialize(v) for v in val]
    if isinstance(val, (set, frozenset)):
        items = [_diag_serialize(v) for v in val]
        try:
            return sorted(items)
        except TypeError:
            return items
    # Row reference: has .uuid attribute but is not a uuid.UUID instance.
    row_uuid_attr = getattr(val, "uuid", None)
    if row_uuid_attr is not None:
        name = getattr(val, "name", None)
        uid = str(row_uuid_attr)
        return {"uuid": uid, "name": name} if name else {"uuid": uid}
    return str(val)


def same_network(row: Any, network_id: Optional[Any]) -> bool:
    if network_id is None:
        return True
    return row_external_ids(row).get(f"{EXT_ID_PREFIX}network-id") == str(network_id)


def same_vpc(row: Any, vpc_id: Optional[Any]) -> bool:
    if vpc_id is None:
        return True
    return row_external_ids(row).get(f"{EXT_ID_PREFIX}vpc-id") == str(vpc_id)


@dataclasses.dataclass
class ExtensionConfig:
    nb_connection: str
    sb_connection: Optional[str] = None
    timeout: int = DEFAULT_TIMEOUT
    ssl_private_key: Optional[str] = None
    ssl_certificate: Optional[str] = None
    ssl_ca_cert: Optional[str] = None
    physnet: str = "physnet1"
    bridge_mappings: str = ""
    metadata_mode: str = "static-route"
    metadata_store: str = DEFAULT_METADATA_STORE
    manage_lsp_for_nics: bool = True
    routing_mode: str = "routed"
    default_domain: str = "cloudstack.internal"
    dry_run: bool = False
    pf_via_nat: bool = False

    @classmethod
    def from_details(cls, details: Mapping[str, Any]) -> "ExtensionConfig":
        nb = first_present(
            details,
            "ovn_nb_connection",
            "ovn_nb_db",
            "nb_connection",
            "nb",
            default=os.environ.get("OVN_NB_DB", "unix:/var/run/ovn/ovnnb_db.sock"),
        )
        sb = first_present(
            details,
            "ovn_sb_connection",
            "ovn_sb_db",
            "sb_connection",
            "sb",
            default=os.environ.get("OVN_SB_DB"),
        )
        return cls(
            nb_connection=str(nb),
            sb_connection=str(sb) if sb else None,
            timeout=int(first_present(details, "timeout", "ovsdb_timeout", default=DEFAULT_TIMEOUT)),
            ssl_private_key=first_present(details, "ssl_private_key", "ovn_ssl_private_key"),
            ssl_certificate=first_present(details, "ssl_certificate", "ovn_ssl_certificate"),
            ssl_ca_cert=first_present(details, "ssl_ca_cert", "ovn_ssl_ca_cert"),
            physnet=str(first_present(details, "ovn_physnet", "physicalnetworkname", "physnet", default="physnet1")),
            bridge_mappings=str(first_present(details, "bridge_mappings", "ovn_bridge_mappings", default="")),
            metadata_mode=str(first_present(details, "metadata_mode", default="static-route")),
            metadata_store=str(first_present(details, "metadata_store", default=DEFAULT_METADATA_STORE)),
            manage_lsp_for_nics=parse_bool(first_present(details, "manage_lsp_for_nics", default="true"), True),
            routing_mode=str(first_present(details, "routing_mode", default="routed")),
            default_domain=str(first_present(details, "domain", "default_domain", default="cloudstack.internal")),
            dry_run=parse_bool(first_present(details, "dry_run", default=os.environ.get("OVN_EXTENSION_DRY_RUN"))),
            pf_via_nat=parse_bool(first_present(details, "pf_via_nat", default="false"), False),
        )


@dataclasses.dataclass
class CommandContext:
    command: str
    args: Dict[str, Any]
    physical_details: Dict[str, Any]
    network_details: Dict[str, Any]
    config: ExtensionConfig

    @property
    def network_id(self) -> Optional[str]:
        return str(first_present(self.args, "network_id", default="")) or None

    @property
    def vpc_id(self) -> Optional[str]:
        return str(first_present(self.args, "vpc_id", default="")) or None

    @property
    def zone_id(self) -> Optional[str]:
        return str(first_present(self.args, "zone_id", default="")) or None

    @property
    def network_state(self) -> str:
        """Guest network state from payload: allocated/setup/implementing/implemented/shutdown/destroy."""
        return str(first_present(self.args, "network_state", default="") or "").lower()

    @property
    def vpc_state(self) -> str:
        """VPC state from payload: enabled/inactive."""
        return str(first_present(self.args, "vpc_state", default="") or "").lower()

    @property
    def guest_type(self) -> str:
        """Guest network type: 'isolated', 'shared', or 'l2'. Defaults to 'isolated'."""
        return str(first_present(self.args, "guest_type", default="isolated")).lower()

    @property
    def is_shared(self) -> bool:
        return self.guest_type == "shared"

    @property
    def routing_mode(self) -> str:
        # Shared networks have no virtual router — the upstream physical router
        # owns L3.  Always use bridged mode regardless of what the payload or
        # config says.  The Java side never sends routing_mode in the payload,
        # so without this guard ctx.routing_mode would fall through to the
        # config default ("routed") and ConnectivityService would try to create
        # a logical router for a shared network.
        if self.is_shared:
            return "bridged"
        return str(first_present(self.args, "routing_mode", default=self.config.routing_mode)).lower()

    def arg(self, key: str, default: Any = None) -> Any:
        return first_present(self.args, key.replace("-", "_"), default=default)


class OvnClient:
    """Thin ovsdbapp wrapper used by all services.

    The implementation sticks to ovsdbapp transactions and generic db_* calls
    where useful.  The schema-specific helpers are used for common OVN objects.
    """

    def __init__(self, config: ExtensionConfig):
        self.config = config
        self._nb_api = None
        self._sb_api = None

    def _configure_ssl(self) -> None:
        if not (self.config.ssl_private_key or self.config.ssl_certificate or self.config.ssl_ca_cert):
            return
        try:
            from ovs import stream
        except Exception as exc:
            raise ExtensionError("python ovs package is required for SSL OVSDB connections") from exc
        if self.config.ssl_private_key:
            stream.Stream.ssl_set_private_key_file(self.config.ssl_private_key)
        if self.config.ssl_certificate:
            stream.Stream.ssl_set_certificate_file(self.config.ssl_certificate)
        if self.config.ssl_ca_cert:
            stream.Stream.ssl_set_ca_cert_file(self.config.ssl_ca_cert)

    def _connect(self, remote: str, schema: str):
        try:
            from ovsdbapp.backend.ovs_idl import connection
        except Exception as exc:
            raise ExtensionError(
                "ovsdbapp is not installed. Install python3-ovsdbapp and python3-ovs on the CloudStack management server."
            ) from exc

        self._configure_ssl()
        idl = connection.OvsdbIdl.from_server(remote, schema)
        conn = connection.Connection(idl, self.config.timeout)
        if schema == "OVN_Northbound":
            from ovsdbapp.schema.ovn_northbound import impl_idl

            return impl_idl.OvnNbApiIdlImpl(conn)
        if schema == "OVN_Southbound":
            from ovsdbapp.schema.ovn_southbound import impl_idl

            return impl_idl.OvnSbApiIdlImpl(conn)
        raise ExtensionError(f"unsupported OVSDB schema: {schema}")

    @property
    def nb(self):
        if self._nb_api is None:
            self._nb_api = self._connect(self.config.nb_connection, "OVN_Northbound")
        return self._nb_api

    @property
    def sb(self):
        if not self.config.sb_connection:
            return None
        if self._sb_api is None:
            self._sb_api = self._connect(self.config.sb_connection, "OVN_Southbound")
        return self._sb_api

    @contextlib.contextmanager
    def txn(self) -> Iterator[Any]:
        if self.config.dry_run:
            LOG.info("dry-run: opening transaction")
        with self.nb.transaction(check_error=True) as txn:
            yield txn

    def execute(self, command: Any) -> Any:
        return command.execute(check_error=True)

    def table_exists(self, table: str) -> bool:
        return table in self.nb.tables

    def table_has_column(self, table: str, column: str) -> bool:
        try:
            return column in self.nb.tables[table].columns
        except Exception:
            return False

    def rows(self, table: str) -> List[Any]:
        if not self.table_exists(table):
            return []
        return list(self.execute(self.nb.db_list_rows(table)))

    def owned_rows(self, table: str, **filters: Any) -> List[Any]:
        rows = [r for r in self.rows(table) if is_owned(r)]
        for key, value in filters.items():
            if value is None:
                continue
            ext_key = f"{EXT_ID_PREFIX}{key.replace('_', '-')}"
            rows = [r for r in rows if row_external_ids(r).get(ext_key) == str(value)]
        return rows

    def by_name(self, table: str, name: str) -> Optional[Any]:
        for row in self.rows(table):
            if row_name(row) == name:
                return row
        return None

    def add_ext_ids(self, txn: Any, table: str, record: Any, updates: Mapping[str, Any]) -> None:
        row = record if hasattr(record, "external_ids") else self.by_name(table, str(record))
        txn.add(self.nb.db_set(table, record, ("external_ids", merge_ext_ids(row, updates)), if_exists=True))

    def destroy_referenced_row(
        self,
        txn: Any,
        parent_table: str,
        parent: Any,
        column: str,
        child_table: str,
        child: Any,
    ) -> None:
        child_id = row_uuid(child)
        txn.add(self.nb.db_remove(parent_table, parent, column, child_id, if_exists=True))
        txn.add(self.nb.db_destroy(child_table, child_id))

    def chassis_names(self) -> Set[str]:
        sb = self.sb
        if sb is None:
            return set()
        try:
            return {row_name(row) for row in sb.db_list_rows("Chassis").execute(check_error=True)}
        except Exception:
            LOG.debug("failed to list OVN SB chassis", exc_info=True)
            return set()


class Names:
    def __init__(self, ctx: CommandContext):
        self.ctx = ctx

    def switch(self, network_id: Optional[Any] = None) -> str:
        return safe_name("cs", "ls", "net", network_id or self.ctx.network_id)

    def vm_switch(self, network_id: Optional[Any] = None) -> str:
        """Return the LS where VM LSPs for this network should live.

        Shared networks place all their VM LSPs on the per-VLAN public LS so
        that every shared network on the same physical VLAN shares a single
        logical switch and a single localnet port — two shared networks on
        vlan54 both use cs-ls-public-physnet1-vlan54.

        Isolated/VPC networks use their own per-network LS (cs-ls-net-{id}).
        """
        if self.ctx.is_shared:
            vlan = self._normalise_vlan_id(self.ctx.arg("vlan"))
            if vlan == "untagged" or vlan.isdigit():
                return self.public_switch(vlan)
            # vlan is stale/invalid — the network's broadcast_uri was previously
            # set to ovn://cs-net-N, so Java extracted the URI host as the vlan
            # value.  Re-implement-network will fix the broadcast_uri; until then
            # fall back to the per-network LS to avoid touching the wrong switch.
            LOG.warning(
                "vm_switch: vlan %r for shared network %s is not a valid tag; "
                "run implement-network to refresh the broadcast_uri",
                vlan, self.ctx.network_id,
            )
            return self.switch(network_id)
        return self.switch(network_id)

    def router(self, network_id: Optional[Any] = None, vpc_id: Optional[Any] = None) -> str:
        vpc = vpc_id if vpc_id is not None else self.ctx.vpc_id
        net = network_id if network_id is not None else self.ctx.network_id
        if vpc:
            return safe_name("cs", "lr", "vpc", vpc)
        return safe_name("cs", "lr", "net", net)

    def tier_lrp(self, network_id: Optional[Any] = None) -> str:
        return safe_name("cs", "lrp", "net", network_id or self.ctx.network_id)

    def tier_router_lsp(self, network_id: Optional[Any] = None) -> str:
        return safe_name("cs", "lsp", "router", "net", network_id or self.ctx.network_id)

    @staticmethod
    def _normalise_vlan_id(value: Any) -> str:
        """Strip the ``vlan://`` URI prefix and return just the tag (or 'untagged')."""
        if value in (None, "", "untagged"):
            return "untagged"
        text = str(value).strip()
        if text.startswith("vlan://"):
            text = text[len("vlan://"):]
        # Strip any other URI scheme that leaks in.
        if "://" in text:
            text = text.split("://", 1)[1]
        return text or "untagged"

    def public_switch(self, public_vlan: Optional[Any] = None) -> str:
        vlan = self._normalise_vlan_id(public_vlan or self.ctx.arg("public_vlan"))
        return safe_name("cs", "ls", "public", self.ctx.config.physnet, f"vlan{vlan}")

    def public_localnet_lsp(self, public_vlan: Optional[Any] = None) -> str:
        vlan = self._normalise_vlan_id(public_vlan or self.ctx.arg("public_vlan"))
        return safe_name("cs", "lsp", "localnet", self.ctx.config.physnet, f"vlan{vlan}")

    def public_lrp(self, router: Optional[str] = None, public_vlan: Optional[Any] = None) -> str:
        router_name = router or self.router()
        vlan = self._normalise_vlan_id(public_vlan or self.ctx.arg("public_vlan"))
        return safe_name("cs", "lrp", "public", router_name, f"vlan{vlan}")

    def public_router_lsp(self, router: Optional[str] = None, public_vlan: Optional[Any] = None) -> str:
        router_name = router or self.router()
        vlan = self._normalise_vlan_id(public_vlan or self.ctx.arg("public_vlan"))
        return safe_name("cs", "lsp", "public-router", router_name, f"vlan{vlan}")

    def vm_lsp(self, mac: str, network_id: Optional[Any] = None, nic_uuid: Optional[str] = None) -> str:
        """Compute the Logical_Switch_Port name for a VM NIC.

        When ``nic_uuid`` is provided (CloudStack sends it on all per-NIC
        commands for Lswitch-type networks), it is used verbatim as the LSP
        name.  This guarantees the name matches the ``external_ids:iface-id``
        that libvirt writes on the OVS tap port so ovn-controller can bind
        the logical port automatically.

        Falls back to the MAC-based name ``cs-vif-net-<networkId>-<macFlat>``
        only when ``nic_uuid`` is absent (e.g. older framework versions or
        manual integration).
        """
        if nic_uuid:
            # Use the nic_uuid verbatim — it must match exactly the value
            # libvirt writes as ``external_ids:iface-id`` on the OVS tap.
            # ovn-controller compares it character-for-character against
            # Logical_Switch_Port.name to perform port binding.
            return str(nic_uuid)
        if not mac:
            return ""
        return safe_name("cs", "vif", "net", network_id or self.ctx.network_id, str(mac).replace(":", ""))

    def dhcp_row_key(self, network_id: Optional[Any] = None, ip: Optional[Any] = None) -> str:
        return safe_name("dhcp", "net", network_id or self.ctx.network_id, ip or "subnet")

    def dns_name(self, network_id: Optional[Any] = None) -> str:
        return safe_name("cs", "dns", "net", network_id or self.ctx.network_id)

    def metadata_lsp(self, network_id: Optional[Any] = None) -> str:
        return safe_name("cs", "metadata", "net", network_id or self.ctx.network_id)

    def lb(self, rule_id: Any) -> str:
        return safe_name("cs", "lb", "net", self.ctx.network_id, rule_id)

    def pf_lb(self, rule_id: Any) -> str:
        return safe_name("cs", "pf-lb", "net", self.ctx.network_id, rule_id)

    def address_set(self, kind: str, identifier: Any, version: int = 4) -> str:
        return sanitize_symbol(safe_name("cs", "as", kind, identifier, f"ip{version}").replace("-", "_"))

    def port_group(self, identifier: Any) -> str:
        return sanitize_symbol(safe_name("cs", "pg", "sg", identifier).replace("-", "_"))

    def vpc_acl_port_group(self, network_id: Optional[Any] = None) -> str:
        return sanitize_symbol(safe_name("cs", "pg", "acl", "net", network_id or self.ctx.network_id).replace("-", "_"))


class BaseService:
    service_name = "base"

    def __init__(self, ctx: CommandContext, ovn: OvnClient):
        self.ctx = ctx
        self.ovn = ovn
        self.names = Names(ctx)

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class ConnectivityService(BaseService):
    service_name = "connectivity"

    def parse_gateway_chassis(self) -> List[Tuple[str, int, str]]:
        details = self.ctx.physical_details
        raw_profiles = maybe_json(first_present(details, "chassis_profiles", "gateway_chassis_profiles"), {})
        chassis: List[Tuple[str, int, str]] = []

        for index, item in enumerate(list_csv(first_present(details, "gateway_chassis", "chassis", "hosts"))):
            parts = item.split(":")
            name = parts[0].strip()
            if not name:
                continue
            priority = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else max(1, 100 - index)
            datapath = parts[2] if len(parts) > 2 else ""
            profile = raw_profiles.get(name, {}) if isinstance(raw_profiles, dict) else {}
            datapath = str(profile.get("datapath_type") or profile.get("hardware_mode") or datapath or "system")
            priority = int(profile.get("priority", priority)) if isinstance(profile, dict) else priority
            chassis.append((name, priority, datapath))

        if not chassis and self.ctx.network_details.get("selected_chassis"):
            chassis.append((str(self.ctx.network_details["selected_chassis"]), 100, "system"))
        return chassis

    def ensure_network_device(self) -> Dict[str, Any]:
        candidates = self.parse_gateway_chassis()
        reachable = self.ovn.chassis_names()
        if reachable:
            candidates = [c for c in candidates if c[0] in reachable] or candidates

        current = self.ctx.network_details.get("selected_chassis")
        selected: Optional[Tuple[str, int, str]] = None
        for candidate in candidates:
            if candidate[0] == current:
                selected = candidate
                break
        if selected is None and candidates:
            key = str(self.ctx.vpc_id or self.ctx.network_id or random.random())
            index = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % len(candidates)
            selected = sorted(candidates, key=lambda item: (-item[1], item[0]))[index % len(candidates)]

        details = dict(self.ctx.network_details)
        details.update(
            {
                "schema": "cloudstack-ovn-v1",
                "network_id": self.ctx.network_id,
                "vpc_id": self.ctx.vpc_id,
                "ovn_nb_connection": self.ctx.config.nb_connection,
                "physnet": self.ctx.config.physnet,
                "routing_mode": self.ctx.routing_mode,
            }
        )
        if selected:
            details["selected_chassis"] = selected[0]
            details["datapath_type"] = selected[2]
            details["hardware_mode"] = "dpdk" if selected[2] == "netdev" else "kernel"
        details["gateway_chassis"] = [
            {"name": name, "priority": priority, "datapath_type": datapath}
            for name, priority, datapath in candidates
        ]
        return details

    def _network_external_ids(
        self,
        service: str = "connectivity",
        network_id: Optional[Any] = None,
        vpc_id: Optional[Any] = None,
        **extra: Any,
    ) -> Dict[str, str]:
        return ext_ids(
            service=service,
            network_id=network_id if network_id is not None else self.ctx.network_id,
            vpc_id=vpc_id if vpc_id is not None else self.ctx.vpc_id,
            zone_id=self.ctx.arg("zone_id"),
            **extra,
        )

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        network = desired.get("network", desired)
        network_id = str(first_present(network, "id", "network_id", default=self.ctx.network_id))
        vpc_id = first_present(network, "vpc_id", default=self.ctx.vpc_id)
        cidr = first_present(network, "cidr", default=self.ctx.arg("cidr"))
        gateway = first_present(network, "gateway", default=self.ctx.arg("gateway"))
        vlan = first_present(network, "vlan", default=self.ctx.arg("vlan"))
        extension_ip = first_present(network, "extension_ip", default=self.ctx.arg("extension_ip"))
        routing_mode = str(first_present(network, "routing_mode", default=self.ctx.routing_mode)).lower()

        if not network_id:
            raise ExtensionError("network id is required for connectivity sync")

        switch = self.names.switch(network_id)
        router = self.names.router(network_id, vpc_id)
        lrp = self.names.tier_lrp(network_id)
        router_lsp = self.names.tier_router_lsp(network_id)
        # Determine the broadcast URI for this network.
        # - Isolated (routed): OVN virtual URI — no physical VLAN in the URI;
        #   the VLAN is managed inside OVN as the public LRP attachment.
        # - Shared (bridged): keep the original VLAN URI ("vlan://100") so that
        #   CloudStack code that reads the VLAN ID from the broadcast URI
        #   (e.g. BroadcastDomainType.getValue()) continues to work.  The
        #   broadcast_domain_type=Lswitch is what tells the KVM agent to
        #   connect VMs via OVN (iface-id), regardless of the URI format.
        vlan_tag = self.names._normalise_vlan_id(vlan)
        if routing_mode == "bridged":
            # Always use vlan:// for bridged networks so that Java's
            # getVlanId() can extract the tag correctly.  "vlan://untagged"
            # means native (untagged) traffic on the localnet port.
            broadcast_uri = f"vlan://{vlan_tag}"
        else:
            broadcast_uri = f"ovn://cs-net-{network_id}"

        # For bridged (shared) networks the per-network LS is not used — all VM
        # LSPs go on the per-VLAN public LS shared with any isolated networks
        # that uplink to the same physical VLAN.  Report the public LS name.
        effective_switch = self.names.public_switch(vlan) if routing_mode == "bridged" else switch
        report = {
            "switch": effective_switch,
            "router": router if routing_mode == "routed" else None,
            # CloudStack's NetworkExtensionElement currently consumes the
            # singular keys below when applying post-implement updates back to
            # the NetworkVO.  The broadcast_domain_type is the implementation-
            # specific value chosen by this extension (Lswitch for OVN); it is
            # NOT hardcoded in the Java guru, keeping the guru generic.
            "network.broadcast_domain_type": "Lswitch",
            "network.broadcast_uri": broadcast_uri,
            # Keep the NIC hints for compatibility with callers/log readers,
            # but the framework's network update path uses only network.*.
            "nic.broadcast_uri": broadcast_uri,
            "nic.isolation_uri": broadcast_uri,
        }

        if routing_mode == "bridged":
            # Shared networks use the per-VLAN public LS as their logical switch.
            # All shared networks on the same physnet+VLAN share ONE LS and ONE
            # localnet port — lsp_add(may_exist=True) on the standard name is a
            # safe no-op when isolated-network setup already created the port.
            with self.ovn.txn() as txn:
                txn.add(
                    self.ovn.nb.ls_add(
                        effective_switch,
                        may_exist=True,
                        external_ids={
                            f"{EXT_ID_PREFIX}owner": OWNER,
                            f"{EXT_ID_PREFIX}service": "public",
                            f"{EXT_ID_PREFIX}object": "public-switch",
                            f"{EXT_ID_PREFIX}physnet": self.ctx.config.physnet,
                            f"{EXT_ID_PREFIX}public-vlan": str(self.names._normalise_vlan_id(vlan)),
                        },
                    )
                )
                self._ensure_localnet(txn, effective_switch, vlan, network_id)
            return report

        with self.ovn.txn() as txn:
            txn.add(
                self.ovn.nb.ls_add(
                    switch,
                    may_exist=True,
                    external_ids=self._network_external_ids(
                        network_id=network_id,
                        service="connectivity",
                        object="logical-switch",
                        routing_mode=routing_mode,
                        vlan=vlan,
                    ),
                )
            )

            if not (cidr and gateway):
                raise ExtensionError("cidr and gateway are required for routed network implementation")

            router_network = host_cidr(str(gateway), str(cidr))
            txn.add(
                self.ovn.nb.lr_add(
                    router,
                    may_exist=True,
                    external_ids=self._network_external_ids(
                        network_id=network_id,
                        service="connectivity",
                        object="logical-router",
                        vpc_id=vpc_id,
                    ),
                    options={
                        "always_learn_from_arp_request": "false",
                        "mac_binding_age_threshold": "300",
                    },
                )
            )
            txn.add(
                self.ovn.nb.lsp_add(
                    switch,
                    router_lsp,
                    may_exist=True,
                    type="router",
                    addresses=["router"],
                    options={"router-port": lrp},
                    external_ids=self._network_external_ids(
                        network_id=network_id,
                        service="connectivity",
                        object="router-lsp",
                    ),
                )
            )
            # See note in ensure_public_attachment: do NOT set peer= on LRP
            # for LR-to-LS attachment. The LSP we created above with
            # type=router and options:router-port is the canonical link.
            txn.add(
                self.ovn.nb.lrp_add(
                    router,
                    lrp,
                    stable_mac(lrp),
                    [router_network],
                    may_exist=True,
                    external_ids=self._network_external_ids(
                        network_id=network_id,
                        service="connectivity",
                        object="tier-lrp",
                        gateway=gateway,
                        cidr=cidr,
                        extension_ip=extension_ip,
                    ),
                )
            )
            if self.ovn.table_has_column("Logical_Router_Port", "options"):
                txn.add(self.ovn.nb.lrp_set_options(lrp, if_exists=True, **{"arp_proxy": "true"}))
            # For VPC tiers, create the Port_Group that ACL rules will be
            # attached to.  Each tier owns one Port_Group; VM ports are added
            # to it on prepare-nic so that NetworkACL rules apply only to VM
            # traffic and not to the router/localnet ports on the same LS.
            if vpc_id:
                pg_name = self.names.vpc_acl_port_group(network_id)
                txn.add(
                    self.ovn.nb.pg_add(
                        pg_name,
                        may_exist=True,
                        external_ids=self._network_external_ids(
                            network_id=network_id,
                            service="NetworkACL",
                            object="tier-acl-pg",
                            vpc_id=vpc_id,
                        ),
                    )
                )

        # For VPC tiers: propagate DNS rows that already exist for other tiers
        # in the same VPC to this newly created tier LS.  Without this step a
        # VM on tier2 cannot resolve hostnames of VMs on tier1 until the next
        # add-dns-entry call (which would propagate tier1 rows to tier2 via
        # _tier_switches()).  ls_add_dns_record is idempotent for existing refs.
        if vpc_id and routing_mode != "bridged":
            existing_vpc_dns = self.ovn.owned_rows("DNS", vpc_id=vpc_id)
            if existing_vpc_dns:
                with self.ovn.txn() as txn:
                    for dns_row in existing_vpc_dns:
                        txn.add(self.ovn.nb.ls_add_dns_record(switch, _uuid.UUID(row_uuid(dns_row))))

        return report

    def implement_vpc(self) -> Dict[str, Any]:
        if not self.ctx.vpc_id:
            raise ExtensionError("vpc id is required for implement-vpc")
        router = self.names.router(vpc_id=self.ctx.vpc_id)
        # Java sends vpc_cidr (not plain cidr) in the implement-vpc payload.
        vpc_cidr = self.ctx.arg("vpc_cidr") or self.ctx.arg("cidr")
        with self.ovn.txn() as txn:
            txn.add(
                self.ovn.nb.lr_add(
                    router,
                    may_exist=True,
                    external_ids=self._network_external_ids(
                        network_id=None,
                        vpc_id=self.ctx.vpc_id,
                        service="connectivity",
                        object="vpc-logical-router",
                        cidr=vpc_cidr,
                    ),
                    options={
                        "always_learn_from_arp_request": "false",
                        "mac_binding_age_threshold": "300",
                    },
                )
            )
        result: Dict[str, Any] = {"vpc_id": self.ctx.vpc_id, "router": router}

        # During VPC restart-with-cleanup CloudStack re-passes the already-
        # allocated SourceNAT IP inside implement-vpc (source_nat=true).
        # Restore the public attachment and SNAT rule here so the VPC is
        # fully operational without a separate assign-ip call.
        if parse_bool(self.ctx.arg("source_nat"), False) and self.ctx.arg("public_ip"):
            nat = NatService(self.ctx, self.ovn)
            result["source_nat"] = nat.add_vpc_source_nat_from_args()

        return result

    def shutdown_vpc(self) -> Dict[str, Any]:
        if not self.ctx.vpc_id:
            raise ExtensionError("vpc id is required for shutdown-vpc")
        router = self.names.router(vpc_id=self.ctx.vpc_id)
        removed_public_lsp = 0
        with self.ovn.txn() as txn:
            for lsp in self.ovn.rows("Logical_Switch_Port"):
                if getattr(lsp, "type", "") != "router":
                    continue
                router_port = row_options(lsp).get("router-port", "")
                if router_port.startswith(safe_name("cs", "lrp", "public", router)):
                    txn.add(self.ovn.nb.lsp_del(row_name(lsp), if_exists=True))
                    removed_public_lsp += 1
            txn.add(self.ovn.nb.lr_del(router, if_exists=True))
        result: Dict[str, Any] = {"vpc_id": self.ctx.vpc_id, "router": router, "public_lsps_removed": removed_public_lsp}
        pruned_acls = self.prune_orphan_public_acls(router=router)
        if pruned_acls:
            result["orphan_public_acls_pruned"] = pruned_acls
        return result

    def _ensure_localnet(self, txn: Any, switch: str, vlan: Any, network_id: Any,
                         localnet_name: Optional[str] = None) -> None:
        # Both isolated networks (via ensure_public_attachment) and shared
        # networks (via sync bridged path) converge on the same per-VLAN
        # localnet port name.  lsp_add(may_exist=True) is a safe no-op when
        # the port already exists on the same LS.
        localnet = localnet_name if localnet_name else self.names.public_localnet_lsp(vlan)
        columns = {
            "type": "localnet",
            "addresses": ["unknown"],
            "options": {"network_name": self.ctx.config.physnet},
            "external_ids": self._network_external_ids(
                network_id=network_id,
                service="connectivity",
                object="localnet-lsp",
                vlan=vlan,
                physnet=self.ctx.config.physnet,
            ),
        }
        # vlan can arrive as int, plain string ("54"), or URI form
        # ("vlan://54"). Strip the URI scheme before checking and tag.
        vlan_tag = self.names._normalise_vlan_id(vlan)
        txn.add(self.ovn.nb.lsp_add(switch, localnet, may_exist=True, **columns))
        if vlan_tag != "untagged" and vlan_tag.isdigit():
            txn.add(self.ovn.nb.db_set("Logical_Switch_Port", localnet, ("tag", int(vlan_tag)), if_exists=True))

    def ensure_public_attachment(
        self,
        txn: Any,
        router: str,
        public_ip: Optional[str],
        public_cidr: Optional[str],
        public_gateway: Optional[str],
        public_vlan: Optional[str],
    ) -> Dict[str, str]:
        if not (public_cidr and public_gateway):
            return {}
        pswitch = self.names.public_switch(public_vlan)
        localnet = self.names.public_localnet_lsp(public_vlan)
        lrp = self.names.public_lrp(router, public_vlan)
        lsp = self.names.public_router_lsp(router, public_vlan)
        lrp_ip = host_cidr(public_ip or str(ipaddress.ip_network(public_cidr, strict=False)[1]), public_cidr)

        txn.add(
            self.ovn.nb.ls_add(
                pswitch,
                may_exist=True,
                external_ids=self._network_external_ids(
                    service="public",
                    object="public-switch",
                    public_vlan=public_vlan,
                    physnet=self.ctx.config.physnet,
                ),
            )
        )
        self._ensure_localnet(txn, pswitch, public_vlan, self.ctx.network_id)
        txn.add(
            self.ovn.nb.lsp_add(
                pswitch,
                lsp,
                may_exist=True,
                type="router",
                addresses=["router"],
                options={"router-port": lrp},
                external_ids=self._network_external_ids(service="public", object="public-router-lsp"),
            )
        )
        # NOTE: do NOT set ``peer=`` on the LRP. ``Logical_Router_Port.peer``
        # is for LRP-to-LRP cross-router links (transit networks). The
        # LRP-to-switch attachment is established by the switch-side LSP
        # ``options:router-port`` (set above), and northd treats any LRP
        # whose ``peer`` references a switch port as a misconfiguration:
        # it logs ``Bad configuration: The peer of router port X is a
        # switch port`` and refuses to generate logical flows for the LR.
        lrp_ext_ids = self._network_external_ids(
            service="public",
            object="public-lrp",
            public_gateway=public_gateway,
            public_cidr=public_cidr,
            public_vlan=public_vlan,
        )
        if self.ovn.by_name("Logical_Router_Port", lrp) is None:
            txn.add(self.ovn.nb.lrp_add(router, lrp, stable_mac(lrp), [lrp_ip],
                                          external_ids=lrp_ext_ids))
        else:
            # LRP exists — lrp_add(may_exist=True) would raise when the IP changed
            # (e.g. update-vpc-source-nat-ip), so update networks and ext_ids directly.
            txn.add(self.ovn.nb.db_set("Logical_Router_Port", lrp,
                                        ("networks", [lrp_ip]), if_exists=True))
            self.ovn.add_ext_ids(txn, "Logical_Router_Port", lrp, lrp_ext_ids)
        txn.add(self.ovn.nb.lr_route_add(router, "0.0.0.0/0", public_gateway, may_exist=True))

        for name, priority, datapath in self.parse_gateway_chassis():
            txn.add(self.ovn.nb.lrp_set_gateway_chassis(lrp, name, priority))
            self._mark_hardware(txn, "Logical_Router_Port", lrp, datapath)
        return {"public_switch": pswitch, "public_lrp": lrp, "public_lsp": lsp}

    def _mark_hardware(self, txn: Any, table: str, record: str, datapath_type: str) -> None:
        self.ovn.add_ext_ids(
            txn,
            table,
            record,
            {
                f"{EXT_ID_PREFIX}datapath-type": datapath_type,
                f"{EXT_ID_PREFIX}hardware-mode": "dpdk" if datapath_type == "netdev" else "kernel",
            },
        )

    def delete_network(self, network_id: str, vpc_id: Optional[str], hard: bool = False) -> Dict[str, Any]:
        switch = self.names.switch(network_id)
        router = self.names.router(network_id, vpc_id)
        lrp = self.names.tier_lrp(network_id)
        router_lsp = self.names.tier_router_lsp(network_id)

        # Public router LSPs sit on the PUBLIC Logical_Switch, not the guest
        # LS, so they are NOT cascade-deleted when ls_del(guest_switch) runs.
        # Collect them before the transaction so we can delete explicitly.
        #
        # IMPORTANT: for VPC tiers the public-router-lsp is SHARED across all
        # tiers in the VPC — it is the single LSP that connects the public LS
        # to the VPC router.  It must NOT be deleted when one tier is removed
        # while other tiers (and their LBs, SourceNAT, etc.) are still alive.
        # The LSP carries the tier's network_id in ext_ids if it was first
        # created/updated from an assign-ip context, which can make it look
        # tier-specific even though it is VPC-level.
        # Guard: skip any LSP that also carries a vpc_id — those are VPC-level
        # and are cleaned up by shutdown_vpc() when the whole VPC is torn down.
        public_lsps = [
            row for row in self.ovn.owned_rows("Logical_Switch_Port", network_id=network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}object") == "public-router-lsp"
            and not row_external_ids(row).get(f"{EXT_ID_PREFIX}vpc-id")
        ]

        # DHCP_Options rows (both the subnet row from config-dhcp-subnet and
        # per-lease rows) have no cascade relationship with the LS — they must
        # be deleted explicitly.
        dhcp_rows = self.ovn.owned_rows("DHCP_Options", network_id=network_id)

        # PublicFirewall default-deny ACLs and per-IP Firewall allow-rules are
        # installed on the PUBLIC Logical_Switch, not the guest LS, so they
        # survive ls_del(guest_switch).  Collect them before the transaction
        # and remove them by UUID — equivalent to:
        #   ovn-nbctl remove Logical_Switch <public-ls> acls <uuid>
        public_acls: List[Any] = [
            row for row in self.ovn.owned_rows("ACL", network_id=network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}kind") in {
                "public-default-deny", "public-firewall-rule"
            }
        ]

        deleted = {"switch": switch, "router": None if vpc_id else router}
        with self.ovn.txn() as txn:
            for pub_lsp in public_lsps:
                txn.add(self.ovn.nb.lsp_del(row_uuid(pub_lsp), if_exists=True))
            for dhcp_row in dhcp_rows:
                txn.add(self.ovn.nb.dhcp_options_del(row_uuid(dhcp_row)))
            for acl_row in public_acls:
                ext = row_external_ids(acl_row)
                # apply_public_ip_firewall() stores the public-ls name in
                # ext_ids so we can dereference by UUID without a table scan.
                pub_ls = ext.get(f"{EXT_ID_PREFIX}public-ls")
                if pub_ls:
                    # acl_del atomically removes the ACL from the LS acls set
                    # and destroys the row (db_destroy alone silently fails for
                    # ACLs still referenced by a Logical_Switch.acls strong ref).
                    txn.add(
                        self.ovn.nb.acl_del(
                            pub_ls,
                            getattr(acl_row, "direction", None),
                            getattr(acl_row, "priority", None),
                            getattr(acl_row, "match", None),
                        )
                    )
                else:
                    txn.add(self.ovn.nb.db_destroy("ACL", row_uuid(acl_row)))
            txn.add(self.ovn.nb.lsp_del(router_lsp, if_exists=True))
            txn.add(self.ovn.nb.lrp_del(lrp, router=router, if_exists=True))
            txn.add(self.ovn.nb.ls_del(switch, if_exists=True))
            if not vpc_id:
                txn.add(self.ovn.nb.lr_del(router, if_exists=True))
            else:
                # The ACL Port_Group is per-tier; delete it with the tier.
                # Cascade-deletes its ACL rows automatically.
                txn.add(self.ovn.nb.pg_del(self.names.vpc_acl_port_group(network_id), if_exists=True))
        if public_lsps:
            deleted["public_lsps_removed"] = len(public_lsps)
        if dhcp_rows:
            deleted["dhcp_options_removed"] = len(dhcp_rows)
        if public_acls:
            deleted["public_acls_removed"] = len(public_acls)

        # Remove Logical_Router_Policy rows for this tier from the VPC router.
        # When the entire VPC is torn down, lr_del() cascade-deletes all policies;
        # but when only one tier is removed (vpc_id is still alive), we must
        # clean them up explicitly.
        if vpc_id and self.ovn.table_exists("Logical_Router_Policy"):
            lr_policies = self.ovn.owned_rows("Logical_Router_Policy", network_id=network_id)
            if lr_policies:
                with self.ovn.txn() as txn:
                    for lrp_row in lr_policies:
                        txn.add(self.ovn.nb.db_remove(
                            "Logical_Router", router, "policies", row_uuid(lrp_row), if_exists=True,
                        ))
                        txn.add(self.ovn.nb.db_destroy("Logical_Router_Policy", row_uuid(lrp_row)))
                deleted["lr_policies_removed"] = len(lr_policies)

        pruned = self.prune_orphan_gateway_chassis()
        if pruned:
            deleted["gateway_chassis_pruned"] = pruned
        pruned_acls = self.prune_orphan_public_acls(router=self.names.router())
        if pruned_acls:
            deleted["orphan_public_acls_pruned"] = pruned_acls
        pruned_dns = self.prune_orphan_dns(network_id=network_id)
        if pruned_dns:
            deleted["orphan_dns_pruned"] = pruned_dns
        pruned_dhcp = self.prune_orphan_dhcp(network_id=network_id)
        if pruned_dhcp:
            deleted["orphan_dhcp_pruned"] = pruned_dhcp
        return deleted

    def prune_orphan_gateway_chassis(self) -> int:
        """Remove Gateway_Chassis rows that no longer reference a live chassis.

        ``ovn-northd`` keeps publishing Logical_Flows for Gateway_Chassis
        entries even after the underlying chassis has been removed from the
        SB cluster.  Stale entries can pin traffic to a dead host and slow
        down failover to the surviving gateway.  This helper scans owned
        Gateway_Chassis rows, compares the ``chassis_name`` column against
        the live SB Chassis set, and destroys the orphans.

        Mirrors the OVN plugin's commit "OVN plugin: clean up per-IP
        artifacts on release and prune stale gateway chassis".
        """
        if not self.ovn.table_exists("Gateway_Chassis"):
            return 0
        live = self.ovn.chassis_names()
        if not live:
            # No SB endpoint configured -- be conservative, do not prune.
            return 0
        pruned = 0
        with self.ovn.txn() as txn:
            for row in self.ovn.rows("Gateway_Chassis"):
                chassis_name = getattr(row, "chassis_name", "") or ""
                if not chassis_name or chassis_name in live:
                    continue
                # Detach from any LRP that still references it.
                for lrp_row in self.ovn.rows("Logical_Router_Port"):
                    refs = [row_uuid(gc) for gc in getattr(lrp_row, "gateway_chassis", [])]
                    if row_uuid(row) in refs:
                        txn.add(self.ovn.nb.db_remove(
                            "Logical_Router_Port",
                            row_uuid(lrp_row),
                            "gateway_chassis",
                            row_uuid(row),
                            if_exists=True,
                        ))
                txn.add(self.ovn.nb.db_destroy("Gateway_Chassis", row_uuid(row)))
                pruned += 1
        return pruned

    def prune_orphan_public_acls(self, router: Optional[str] = None) -> int:
        """Remove public-switch ACLs whose referenced outport LSP no longer exists.

        Called after network/VPC teardown as a safety net.  Covers two gaps:

        1. ``shutdown_vpc()`` deletes the VPC public LSP and LR but never
           explicitly removes the ``public-default-deny`` / ``public-firewall-rule``
           ACLs that were installed on the public LS for individual public IPs.

        2. ``delete-static-nat`` creates a ``public-default-deny`` ACL via
           ``apply_public_ip_firewall(force=True)`` whose ``network_id`` can
           differ from the one used later by ``release-ip``, causing
           ``revoke_public_ip_firewall()`` to miss it.

        Pass ``router`` (e.g. ``cs-lr-net-123`` or ``cs-lr-vpc-45``) to scope
        cleanup to ACLs belonging to that specific router only.  Without it the
        function scans all cloudstack-owned ACLs, which is too broad and may
        touch entries from unrelated networks.
        """
        existing_lsp_names = {row_name(r) for r in self.ovn.rows("Logical_Switch_Port") if row_name(r)}

        orphans = []
        for acl in self.ovn.owned_rows("ACL"):
            ext = row_external_ids(acl)
            kind = ext.get(f"{EXT_ID_PREFIX}kind", "")
            if kind not in {"public-default-deny", "public-firewall-rule"}:
                continue
            public_lsp = ext.get(f"{EXT_ID_PREFIX}public-lsp")
            if not public_lsp:
                match_expr = str(getattr(acl, "match", "") or "")
                m = re.search(r'outport\s*==\s*"([^"]+)"', match_expr)
                if m:
                    public_lsp = m.group(1)
            if not public_lsp:
                continue
            if router and not public_lsp.startswith(f"cs-lsp-public-router-{router}-vlan"):
                continue
            if public_lsp not in existing_lsp_names:
                orphans.append((acl, public_lsp))

        if not orphans:
            return 0

        # Build a map from ACL UUID to its parent LS row.  Must be done outside
        # the transaction so reads do not run concurrently with pending writes.
        acl_to_ls: Dict[str, Any] = {}
        for ls in self.ovn.rows("Logical_Switch"):
            for a in getattr(ls, "acls", []) or []:
                acl_to_ls[row_uuid(a)] = ls

        with self.ovn.txn() as txn:
            for acl, public_lsp in orphans:
                acl_id = row_uuid(acl)
                ls = acl_to_ls.get(acl_id)
                if ls:
                    # acl_del atomically removes the ACL from the LS acls set
                    # and destroys the row — the same as _destroy_acl_everywhere.
                    txn.add(
                        self.ovn.nb.acl_del(
                            row_name(ls),
                            getattr(acl, "direction", None),
                            getattr(acl, "priority", None),
                            getattr(acl, "match", None),
                        )
                    )
                else:
                    txn.add(self.ovn.nb.db_destroy("ACL", acl_id))
                LOG.info("prune_orphan_public_acls: removed orphaned ACL %s (LSP %s gone)",
                         acl_id, public_lsp)

        return len(orphans)

    def prune_orphan_dns(self, network_id: Optional[Any] = None) -> int:
        """Remove DNS rows for a network whose guest LS no longer exists.

        Called after ``delete_network`` to clean up DNS rows that
        ``remove_subnet`` may have failed to delete (the ``db_destroy``
        path silently no-ops when the DNS row is still strongly referenced by
        any surviving LS's ``dns_records`` set).  By the time this prune runs
        the guest LS has been destroyed, so ``dns_del`` can remove the row
        without first mutating the parent.
        """
        if network_id is None:
            return 0
        existing_ls_names = {row_name(r) for r in self.ovn.rows("Logical_Switch") if row_name(r)}
        orphans = []
        for row in self.ovn.owned_rows("DNS", network_id=network_id):
            net_id = row_external_ids(row).get(f"{EXT_ID_PREFIX}network-id")
            if not net_id:
                continue
            if safe_name("cs", "ls", "net", net_id) not in existing_ls_names:
                orphans.append((row, net_id))
        if not orphans:
            return 0
        with self.ovn.txn() as txn:
            for row, net_id in orphans:
                txn.add(self.ovn.nb.dns_del(row_uuid(row)))
                LOG.info("prune_orphan_dns: removed orphaned DNS %s (cs-ls-net-%s gone)",
                         row_uuid(row), net_id)
        return len(orphans)

    def prune_orphan_dhcp(self, network_id: Optional[Any] = None) -> int:
        """Remove DHCP_Options rows for a network whose guest LS no longer exists.

        Called after ``delete_network`` when the DHCP cleanup inside the main
        transaction may have been skipped (e.g. the LS was already absent and
        ``owned_rows`` returned nothing for the right ``network_id``).

        Pass ``network_id`` to scope the scan to one specific network.
        """
        if network_id is None:
            return 0
        existing_ls_names = {row_name(r) for r in self.ovn.rows("Logical_Switch") if row_name(r)}
        if safe_name("cs", "ls", "net", network_id) in existing_ls_names:
            return 0
        orphans = self.ovn.owned_rows("DHCP_Options", network_id=network_id)
        if not orphans:
            return 0
        with self.ovn.txn() as txn:
            for row in orphans:
                txn.add(self.ovn.nb.dhcp_options_del(row_uuid(row)))
                LOG.info("prune_orphan_dhcp: removed orphaned DHCP_Options %s (cs-ls-net-%s gone)",
                         row_uuid(row), network_id)
        return len(orphans)


class NatService(BaseService):
    service_name = "nat"

    def _router(self) -> str:
        return self.names.router()

    def _nat_key(self, rule: Mapping[str, Any], kind: str) -> str:
        return str(first_present(rule, "id", "rule_id", default=compact_json(rule))) + f":{kind}"

    def _desired_nat_rows(self, desired: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        network_id = self.ctx.network_id
        vpc_id = self.ctx.vpc_id
        cidr = str(first_present(desired, "cidr", default=self.ctx.arg("cidr") or ""))
        rows: Dict[str, Dict[str, Any]] = {}

        source_nat = desired.get("source_nat")
        if source_nat:
            public_ip = str(first_present(source_nat, "public_ip", "ip", default=self.ctx.arg("public_ip")))
            logical_ip = str(first_present(source_nat, "logical_ip", "cidr", default=cidr))
            rows[f"snat:{public_ip}:{logical_ip}"] = {
                "type": "snat",
                "external_ip": public_ip,
                "logical_ip": logical_ip,
                "external_ids": ext_ids(
                    service="SourceNat",
                    network_id=network_id,
                    vpc_id=vpc_id,
                    rule_id=f"snat:{public_ip}",
                    kind="source-nat",
                ),
            }

        for rule in desired.get("static_nats", []) or []:
            public_ip = str(first_present(rule, "public_ip", "publicIp"))
            private_ip = str(first_present(rule, "private_ip", "privateIp"))
            rule_id = self._nat_key(rule, "static")
            columns = {
                "type": "dnat_and_snat",
                "external_ip": public_ip,
                "logical_ip": private_ip,
                "external_ids": ext_ids(
                    service="StaticNat",
                    network_id=network_id,
                    vpc_id=vpc_id,
                    rule_id=rule_id,
                    kind="static-nat",
                    public_ip=public_ip,
                    private_ip=private_ip,
                ),
            }
            if rule.get("logical_port"):
                columns["logical_port"] = str(rule["logical_port"])
            if rule.get("external_mac"):
                columns["external_mac"] = str(rule["external_mac"])
            rows[f"static:{rule_id}"] = columns

        # PortForwarding is routed through OVN Load_Balancer by default --
        # multiple PF rules on the same public IP coexist cleanly there,
        # whereas Logical_Router.nat collides on (external_ip, protocol,
        # port) tuples and the public IP becomes a foot-gun the moment a
        # second rule is added.  Set physical-network detail
        # ``pf_via_nat=true`` to opt back in to NAT-row PF for OVN
        # deployments that need it.
        if self.ctx.config.pf_via_nat:
            for rule in desired.get("port_forwards", []) or []:
                rows[f"pf:{self._nat_key(rule, 'pf')}"] = self._pf_nat_columns(rule)
        return rows

    def _pf_nat_columns(self, rule: Mapping[str, Any]) -> Dict[str, Any]:
        public_ip = str(first_present(rule, "public_ip", "publicIp"))
        private_ip = str(first_present(rule, "private_ip", "privateIp"))
        public_port = normalize_port_range(first_present(rule, "public_port", "publicPort"))
        private_port = normalize_port_range(first_present(rule, "private_port", "privatePort", default=public_port))
        protocol = str(first_present(rule, "protocol", default="tcp")).lower()
        rule_id = self._nat_key(rule, "pf")
        match = f"ip4 && ip4.dst == {public_ip} && {protocol_match(protocol, public_port)}"
        columns = {
            "type": "dnat",
            "external_ip": public_ip,
            "logical_ip": private_ip,
            "external_ids": ext_ids(
                service="PortForwarding",
                network_id=self.ctx.network_id,
                vpc_id=self.ctx.vpc_id,
                rule_id=rule_id,
                kind="port-forward",
                public_ip=public_ip,
                private_ip=private_ip,
                public_port=public_port,
                private_port=private_port,
                protocol=protocol,
            ),
        }
        if self.ovn.table_has_column("NAT", "match"):
            columns["match"] = match
        if self.ovn.table_has_column("NAT", "priority"):
            columns["priority"] = int(first_present(rule, "priority", default=20000))
        if self.ovn.table_has_column("NAT", "external_port_range"):
            columns["external_port_range"] = public_port
        if self.ovn.table_has_column("NAT", "logical_port_range"):
            columns["logical_port_range"] = private_port
        return columns

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        router = self._router()

        # VPC: SourceNAT is shared across all tiers and lives on the VPC
        # router, not on individual tier routers.  Delegate it to
        # sync_vpc_source_nat() and strip it so the per-network path below
        # does not create a duplicate network-scoped SNAT row.
        vpc_snat_result: Optional[Dict[str, Any]] = None
        if self.ctx.vpc_id and desired.get("source_nat"):
            source_nat = desired["source_nat"]
            public_ip = str(first_present(source_nat, "public_ip", "ip", default=""))
            logical_ip = str(first_present(source_nat, "logical_ip", "cidr", default=self._vpc_logical_ip()))
            if public_ip and logical_ip:
                vpc_snat_result = self.sync_vpc_source_nat(public_ip, logical_ip)
            desired = {k: v for k, v in desired.items() if k != "source_nat"}

        desired_rows = self._desired_nat_rows(desired)

        # Scope the reconciliation to only the service types present in
        # *desired*.  Without this, add_source_nat_from_args / add_static_nat_from_args
        # call sync() with only their own rule type, sync() then sees all
        # existing PortForwarding NAT rows as "not desired" and deletes them.
        services_in_scope: Set[str] = set()
        if desired.get("source_nat"):
            services_in_scope.add("SourceNat")
        if desired.get("static_nats"):
            services_in_scope.add("StaticNat")
        if desired.get("port_forwards") and self.ctx.config.pf_via_nat:
            services_in_scope.add("PortForwarding")

        current = {
            row_external_ids(row).get(f"{EXT_ID_PREFIX}rule-id", row_uuid(row)): row
            for row in self.ovn.owned_rows("NAT", network_id=self.ctx.network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}service") in services_in_scope
        }

        created = 0
        updated = 0
        deleted = 0
        with self.ovn.txn() as txn:
            for key, columns in desired_rows.items():
                rule_id = columns["external_ids"].get(f"{EXT_ID_PREFIX}rule-id")
                row = current.get(rule_id)
                if row is None:
                    create = txn.add(self.ovn.nb.db_create_row("NAT", **columns))
                    txn.add(self.ovn.nb.db_add("Logical_Router", router, "nat", create))
                    created += 1
                else:
                    values = [(col, val) for col, val in columns.items()]
                    txn.add(self.ovn.nb.db_set("NAT", row_uuid(row), *values, if_exists=True))
                    updated += 1

            desired_rule_ids = {
                columns["external_ids"].get(f"{EXT_ID_PREFIX}rule-id") for columns in desired_rows.values()
            }
            for rule_id, row in current.items():
                if rule_id not in desired_rule_ids:
                    self.ovn.destroy_referenced_row(txn, "Logical_Router", router, "nat", "NAT", row)
                    deleted += 1

        self._sync_pf_lb_fallback(desired)
        if desired.get("source_nat"):
            self.refresh_source_nat_announcements(self.ctx.arg("public_vlan"))
        result: Dict[str, Any] = {"created": created, "updated": updated, "deleted": deleted}
        if vpc_snat_result is not None:
            result["vpc_source_nat"] = vpc_snat_result
        return result

    def _sync_pf_lb_fallback(self, desired: Mapping[str, Any]) -> None:
        if "port_forwards" not in desired:
            # This sync call is not managing port-forwarding (e.g. it was
            # triggered by add_source_nat_from_args or add_static_nat_from_args).
            # Do not touch PF-LB rows — they are managed independently.
            return
        rules = desired.get("port_forwards", []) or []
        if not rules:
            LoadBalancerService(self.ctx, self.ovn).sync_pf_rules([])
            return
        if self.ctx.config.pf_via_nat:
            # Legacy NAT path: only fall back to LB when the OVN schema
            # cannot represent the port remap natively.
            remapped = [
                rule for rule in rules
                if normalize_port_range(first_present(rule, "public_port", "publicPort"))
                != normalize_port_range(first_present(rule, "private_port", "privatePort", default=first_present(rule, "public_port", "publicPort")))
                and not self.ovn.table_has_column("NAT", "logical_port_range")
            ]
            if remapped:
                LoadBalancerService(self.ctx, self.ovn).sync_pf_rules(
                    [self._pf_to_lb(rule) for rule in remapped]
                )
            return
        # Default path: every PF rule becomes a Load_Balancer row.
        LoadBalancerService(self.ctx, self.ovn).sync_pf_rules(
            [self._pf_to_lb(rule) for rule in rules]
        )

    def _pf_to_lb(self, rule: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "id": f"pf-{first_present(rule, 'id', 'rule_id', default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:8])}",
            "name": f"pf-{first_present(rule, 'id', 'rule_id', default='rule')}",
            "publicIp": first_present(rule, "public_ip", "publicIp"),
            "publicPort": int(str(first_present(rule, "public_port", "publicPort")).split("-", 1)[0]),
            "privatePort": int(str(first_present(rule, "private_port", "privatePort")).split("-", 1)[0]),
            "protocol": first_present(rule, "protocol", default="tcp"),
            "algorithm": "source",
            "backends": [{"ip": first_present(rule, "private_ip", "privateIp"), "port": int(str(first_present(rule, "private_port", "privatePort")).split("-", 1)[0])}],
            "source": "port-forward-fallback",
        }

    def add_source_nat_from_args(self) -> Dict[str, Any]:
        if self.ctx.vpc_id:
            return self.add_vpc_source_nat_from_args()
        router = self._router()
        if self.ovn.by_name("Logical_Router", router) is None:
            if self.ctx.network_state in {"shutdown", "destroy", "allocated"}:
                LOG.warning("assign-ip: logical router %r not found during %s — skipping", router, self.ctx.network_state)
                return {"skipped": "lr-missing", "network_state": self.ctx.network_state}
            raise ExtensionError(f"assign-ip: logical router {router!r} not found; network may have been removed")
        desired = {
            "cidr": self.ctx.arg("cidr"),
            "source_nat": {
                "public_ip": self.ctx.arg("public_ip"),
                "logical_ip": self.ctx.arg("cidr"),
            },
        }
        connectivity = ConnectivityService(self.ctx, self.ovn)
        with self.ovn.txn() as txn:
            connectivity.ensure_public_attachment(
                txn,
                self._router(),
                self.ctx.arg("public_ip"),
                self.ctx.arg("public_cidr"),
                self.ctx.arg("public_gateway"),
                self.ctx.arg("public_vlan"),
            )
        result = self.sync(desired)
        self.refresh_source_nat_announcements(self.ctx.arg("public_vlan"))
        # Do NOT install a PublicFirewall default-deny for the SourceNAT IP.
        # The public switch's conntrack zone is never populated for traffic
        # that traverses the router (router LSPs bypass ls_in_pre_acl at
        # priority 110), so a to-lport drop at the public LS would match
        # SNAT return traffic (which arrives as ct.new in the public switch
        # zone) and silently break all VM-initiated outbound connections.
        # Inbound protection for the SNAT IP is provided by the LR itself:
        # unsolicited traffic has no DNAT/reverse-SNAT entry and is dropped
        # at the router level.  Egress policy (default_egress_allow) is
        # enforced via _base_acls() on the guest LS where conntrack works.
        return result

    def add_vpc_source_nat_from_args(self) -> Dict[str, Any]:
        public_ip = str(self.ctx.arg("public_ip") or "")
        logical_ip = self._vpc_logical_ip()
        if not public_ip or not logical_ip:
            raise ExtensionError("public_ip and VPC cidr are required for VPC SourceNat")

        # Capture old SourceNat IP before overwriting so we can revoke its
        # public-IP firewall ACL when the IP changes (update-vpc-source-nat-ip).
        old_ip: Optional[str] = None
        for row in self.ovn.rows("NAT"):
            if (row_external_ids(row).get(f"{EXT_ID_PREFIX}service") == "SourceNat"
                    and row_external_ids(row).get(f"{EXT_ID_PREFIX}vpc-id") == str(self.ctx.vpc_id)
                    and getattr(row, "type", "") == "snat"):
                old_ip = str(getattr(row, "external_ip", "") or "")
                break

        connectivity = ConnectivityService(self.ctx, self.ovn)
        router = self._router()
        public_vlan = self.ctx.arg("public_vlan")
        public_cidr = self.ctx.arg("public_cidr")
        with self.ovn.txn() as txn:
            connectivity.ensure_public_attachment(
                txn,
                router,
                public_ip,
                public_cidr,
                self.ctx.arg("public_gateway"),
                public_vlan,
            )
            # lrp_add(may_exist=True) is a no-op when the public LRP already
            # exists, so the networks column retains the old IP.  Explicitly
            # overwrite it so OVN generates correct ARP/SNAT flows for the new
            # IP (handles the update-vpc-source-nat-ip case).
            if public_cidr:
                lrp_name = self.names.public_lrp(router, public_vlan)
                lrp_ip = host_cidr(public_ip, public_cidr)
                txn.add(self.ovn.nb.db_set(
                    "Logical_Router_Port", lrp_name,
                    ("networks", [lrp_ip]),
                    if_exists=True,
                ))

        if old_ip and old_ip != public_ip:
            FirewallService(self.ctx, self.ovn).revoke_public_ip_firewall(old_ip)

        result = self.sync_vpc_source_nat(public_ip, logical_ip)
        self.refresh_source_nat_announcements(public_vlan)
        FirewallService(self.ctx, self.ovn).apply_public_ip_firewall(public_ip, public_vlan)
        return result

    def _vpc_logical_ip(self) -> str:
        router = self.ovn.by_name("Logical_Router", self._router())
        if router is not None:
            cidr = row_external_ids(router).get(f"{EXT_ID_PREFIX}cidr", "")
            if cidr:
                return cidr
        return str(self.ctx.arg("vpc_cidr") or self.ctx.arg("vpc-cidr") or self.ctx.arg("cidr") or "")

    def sync_vpc_source_nat(self, public_ip: str, logical_ip: str) -> Dict[str, Any]:
        router = self._router()
        current = [
            row
            for row in self.ovn.rows("NAT")
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}service") == "SourceNat"
            and row_external_ids(row).get(f"{EXT_ID_PREFIX}vpc-id") == str(self.ctx.vpc_id)
            and getattr(row, "type", "") == "snat"
        ]
        keep = next(
            (
                row
                for row in current
                if getattr(row, "external_ip", "") == public_ip
                and getattr(row, "logical_ip", "") == logical_ip
            ),
            current[0] if current else None,
        )
        columns = {
            "type": "snat",
            "external_ip": public_ip,
            "logical_ip": logical_ip,
            "external_ids": ext_ids(
                service="SourceNat",
                vpc_id=self.ctx.vpc_id,
                rule_id=f"snat:{public_ip}",
                kind="vpc-source-nat",
            ),
        }
        created = 0
        updated = 0
        deleted = 0
        with self.ovn.txn() as txn:
            if keep is None:
                create = txn.add(self.ovn.nb.db_create_row("NAT", **columns))
                txn.add(self.ovn.nb.db_add("Logical_Router", router, "nat", create))
                created = 1
            else:
                txn.add(self.ovn.nb.db_set("NAT", row_uuid(keep), *[(col, val) for col, val in columns.items()], if_exists=True))
                updated = 1
            keep_id = row_uuid(keep) if keep is not None else None
            for row in current:
                if row_uuid(row) != keep_id:
                    self.ovn.destroy_referenced_row(txn, "Logical_Router", router, "nat", "NAT", row)
                    deleted += 1
        return {"created": created, "updated": updated, "deleted": deleted, "logical_ip": logical_ip, "public_ip": public_ip}

    def refresh_source_nat_announcements(self, public_vlan: Optional[Any] = None) -> Dict[str, Any]:
        """Refresh public router LSP gARP options for SourceNat IPs.

        OVN's ``nat-addresses=router`` shorthand does not announce plain SNAT
        rows. The in-tree OVN plugin writes an explicit
        ``<router-mac> <source-nat-ip> ...`` value so ovn-controller emits
        gratuitous ARP when it claims the gateway chassis port.
        """
        router = self._router()
        lrp = self.names.public_lrp(router, public_vlan)
        lsp = self.names.public_router_lsp(router, public_vlan)
        nat_rows = (
            self.ovn.owned_rows("NAT", vpc_id=self.ctx.vpc_id)
            if self.ctx.vpc_id
            else self.ovn.owned_rows("NAT", network_id=self.ctx.network_id)
        )
        public_ips = sorted(
            {
                str(getattr(row, "external_ip", ""))
                for row in nat_rows
                if row_external_ids(row).get(f"{EXT_ID_PREFIX}service") == "SourceNat"
                and getattr(row, "type", "") == "snat"
                and getattr(row, "external_ip", "")
            }
        )
        value = " ".join([stable_mac(lrp)] + public_ips) if public_ips else "router"
        with self.ovn.txn() as txn:
            txn.add(
                self.ovn.nb.db_set(
                    "Logical_Switch_Port",
                    lsp,
                    (
                        "options",
                        {
                            "router-port": lrp,
                            "nat-addresses": value,
                            "exclude-lb-vips-from-garp": "true",
                        },
                    ),
                    if_exists=True,
                )
            )
        return {"public_lsp": lsp, "nat_addresses": value, "source_nat_ips": public_ips}

    def add_static_nat_from_args(self) -> Dict[str, Any]:
        return self.sync(
            {
                "static_nats": [
                    {
                        "id": self.ctx.arg("public_ip"),
                        "public_ip": self.ctx.arg("public_ip"),
                        "private_ip": self.ctx.arg("private_ip"),
                    }
                ]
            }
        )

    def add_pf_from_args(self) -> Dict[str, Any]:
        rule = {
            "id": f"{self.ctx.arg('public_ip')}:{self.ctx.arg('protocol')}:{self.ctx.arg('public_port')}",
            "public_ip": self.ctx.arg("public_ip"),
            "public_port": self.ctx.arg("public_port"),
            "private_ip": self.ctx.arg("private_ip"),
            "private_port": self.ctx.arg("private_port"),
            "protocol": self.ctx.arg("protocol", "tcp"),
        }
        # Create/update the Load_Balancer row for this PF rule.
        # Do NOT call NatService.sync() — that performs a full NAT-table sync
        # and would delete existing SourceNat/StaticNat rows since they are
        # absent from the "desired" set passed here.
        if self.ctx.config.pf_via_nat:
            # Explicit NAT-based PF when operator has opted in.
            columns = self._pf_nat_columns(rule)
            rule_id = columns["external_ids"].get(f"{EXT_ID_PREFIX}rule-id")
            router = self._router()
            existing = next(
                (row for row in self.ovn.owned_rows("NAT", network_id=self.ctx.network_id)
                 if row_external_ids(row).get(f"{EXT_ID_PREFIX}rule-id") == rule_id),
                None,
            )
            with self.ovn.txn() as txn:
                if existing is None:
                    create = txn.add(self.ovn.nb.db_create_row("NAT", **columns))
                    txn.add(self.ovn.nb.db_add("Logical_Router", router, "nat", create))
                else:
                    txn.add(self.ovn.nb.db_set(
                        "NAT", row_uuid(existing),
                        *list(columns.items()), if_exists=True,
                    ))
            return {"created": int(existing is None), "updated": int(existing is not None)}
        return LoadBalancerService(self.ctx, self.ovn).add_pf_lb_rule(self._pf_to_lb(rule))

    def delete_by_args(self, service: str) -> Dict[str, Any]:
        router = self._router()
        if self.ovn.by_name("Logical_Router", router) is None:
            LOG.warning("delete %s: logical router %r not found; network may have been removed — skipping", service, router)
            return {"deleted": 0, "warning": "router-not-found"}
        public_ip = self.ctx.arg("public_ip")
        private_ip = self.ctx.arg("private_ip")
        deleted = 0
        with self.ovn.txn() as txn:
            for row in self.ovn.owned_rows("NAT", network_id=self.ctx.network_id):
                ext = row_external_ids(row)
                if ext.get(f"{EXT_ID_PREFIX}service") != service:
                    continue
                if public_ip and ext.get(f"{EXT_ID_PREFIX}public-ip", getattr(row, "external_ip", "")) != public_ip:
                    continue
                if private_ip and ext.get(f"{EXT_ID_PREFIX}private-ip", getattr(row, "logical_ip", "")) != private_ip:
                    continue
                self.ovn.destroy_referenced_row(txn, "Logical_Router", router, "nat", "NAT", row)
                deleted += 1
        # When releasing a SourceNat IP, also remove its targeted public-LS
        # firewall ACL so the public LS does not accumulate stale drops.
        if service == "SourceNat" and public_ip:
            FirewallService(self.ctx, self.ovn).revoke_public_ip_firewall(public_ip)
            self.refresh_source_nat_announcements(self.ctx.arg("public_vlan"))
        # When releasing a StaticNat IP, block it at the public LS so that in
        # flat-network environments (public IP pool on the same L2 as the
        # management network) the VPC router no longer forwards the packet to
        # the physical device at that IP via connected-subnet routing.
        # This mirrors what isolated-network PublicFirewall does for released
        # IPs; for VPC it is specifically needed post-DNAT-removal.
        if service == "StaticNat" and deleted > 0 and public_ip:
            FirewallService(self.ctx, self.ovn).apply_public_ip_firewall(
                public_ip, self.ctx.arg("public_vlan"), force=True
            )
            # Stale gateway chassis can pin failover to a dead host; prune
            # entries that no longer match a live SB Chassis.
            ConnectivityService(self.ctx, self.ovn).prune_orphan_gateway_chassis()
        # PortForwarding rules now live in Load_Balancer rows by default;
        # mirror the delete there.
        if service == "PortForwarding":
            switch = self.names.switch()
            with self.ovn.txn() as txn:
                for row in self.ovn.owned_rows("Load_Balancer", network_id=self.ctx.network_id):
                    ext = row_external_ids(row)
                    if ext.get(f"{EXT_ID_PREFIX}service") != "PortForwarding-LB":
                        continue
                    if public_ip and public_ip not in (
                        ":".join(getattr(row, "vips", {}).keys()) if isinstance(getattr(row, "vips", None), dict) else ""
                    ):
                        continue
                    txn.add(self.ovn.nb.lr_lb_del(router, row_uuid(row), if_exists=True))
                    txn.add(self.ovn.nb.ls_lb_del(switch, row_uuid(row), if_exists=True))
                    txn.add(self.ovn.nb.db_destroy("Load_Balancer", row_uuid(row)))
                    deleted += 1
        return {"deleted": deleted}


class FirewallService(BaseService):
    service_name = "firewall"

    # ------------------------------------------------------------------
    # Public-IP firewall (default-deny on unsolicited inbound).
    #
    # The naive approach -- install a high-priority "drop ip on the public
    # LS" ACL -- breaks in OVN because router and localnet LSPs bypass
    # ``ct_next`` in the ``ls_in_pre_acl`` pipeline (priority 110).  The LS
    # conntrack zone never gets populated for traffic traversing the
    # router, so any ``ct.est``/``ct.rpl`` predicate evaluates false and
    # legitimate replies to VM-initiated outbound flows get dropped along
    # with unsolicited inbound.
    #
    # Until the enforcement is moved to ``Logical_Router_Policy`` (where
    # the LR conntrack zone IS populated by ``ct_dnat``/``ct_snat``), we
    # restrict the public-LS firewall to a *targeted* ICMP echo-request
    # drop.  This matches the operator-visible default-deny semantic for
    # ping without touching TCP/UDP, where stateless filtering would break
    # active flows.
    #
    # Tracked as a follow-up: refactor to LR policies so TCP/UDP
    # unsolicited inbound can be dropped safely.
    # ------------------------------------------------------------------
    def apply_public_ip_firewall(self, public_ip: str, public_vlan: Optional[Any] = None,
                                force: bool = False) -> Dict[str, Any]:
        """Install a default-deny ACL for *public_ip* on the public LS.

        Drops all inbound IPv4 traffic at priority 50.  Explicit ALLOW-RELATED
        rules installed by apply-fw-rules at priority 1000 take precedence and
        open only the ports the operator configured.

        **Do NOT call this for SourceNAT IPs.**  The public switch's conntrack
        zone is never populated for traffic that traverses the router (router-
        type LSPs bypass ``ls_in_pre_acl`` at priority 110).  A ``to-lport``
        drop on the public LS therefore matches SNAT return traffic (which
        arrives as ``ct.new`` in the public switch zone) and silently breaks
        all VM-initiated outbound connections.  Inbound protection for the
        SourceNAT IP is provided by the LR itself — unsolicited traffic has no
        reverse-SNAT entry and is dropped at the router level.  Use this only
        for StaticNat / PortForwarding / LB IPs, which are DNAT-inbound and
        do not have VM-initiated-outbound return-traffic concerns.

        For VPC networks this is normally a no-op: traffic to VPC public IPs
        is governed by the VPC router's NAT rules and the per-tier NetworkACL
        Port_Group.  Installing a default-deny here would block all traffic
        before NAT processing can occur.

        Pass ``force=True`` to override the VPC skip.  This is used by
        ``delete-static-nat`` to block the released IP at the public LS so that
        in flat-network environments (where the public IP pool overlaps with the
        management network) traffic no longer reaches the physical device at that
        IP via the VPC router's connected-subnet routing.
        """
        if not public_ip:
            return {"installed": 0}
        if self.ctx.vpc_id and not force:
            return {"installed": 0, "reason": "vpc-no-public-firewall"}
        public_ls = self.names.public_switch(public_vlan)
        if self.ovn.by_name("Logical_Switch", public_ls) is None:
            LOG.debug("public LS %s not present yet; skipping public-IP firewall", public_ls)
            return {"installed": 0, "reason": "public-ls-missing"}
        public_lsp = self.names.public_router_lsp(public_vlan=public_vlan)
        match = f'outport == "{public_lsp}" && ip4 && ip4.dst == {public_ip}'
        rule_id = f"public-fw-default-deny-{public_ip}"
        with self.ovn.txn() as txn:
            txn.add(
                self.ovn.nb.acl_add(
                    public_ls,
                    "to-lport",
                    50,
                    match,
                    "drop",
                    may_exist=True,
                    **ext_ids(
                        service="PublicFirewall",
                        network_id=self.ctx.network_id,
                        vpc_id=self.ctx.vpc_id,
                        rule_id=rule_id,
                        kind="public-default-deny",
                        public_ip=public_ip,
                        public_ls=public_ls,
                        public_lsp=public_lsp,
                    ),
                )
            )
        return {"installed": 1, "match": match}

    def revoke_public_ip_firewall(self, public_ip: str) -> Dict[str, Any]:
        """Remove all PublicFirewall ACLs for *public_ip*."""
        if not public_ip:
            return {"removed": 0}
        removed = 0
        with self.ovn.txn() as txn:
            for row in self.ovn.owned_rows("ACL", network_id=self.ctx.network_id):
                ext = row_external_ids(row)
                if ext.get(f"{EXT_ID_PREFIX}service") != "PublicFirewall":
                    continue
                if ext.get(f"{EXT_ID_PREFIX}public-ip") != public_ip:
                    continue
                for ls in self.ovn.rows("Logical_Switch"):
                    if row_uuid(row) in [row_uuid(a) for a in getattr(ls, "acls", [])]:
                        txn.add(self.ovn.nb.db_remove("Logical_Switch", row_uuid(ls), "acls", row_uuid(row), if_exists=True))
                txn.add(self.ovn.nb.db_destroy("ACL", row_uuid(row)))
                removed += 1
        return {"removed": removed}

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        # CloudStack may send a flat rule list instead of {"rules": [...], ...}.
        # Normalise here so the rest of the method always sees a mapping.
        if isinstance(desired, list):
            desired = {"rules": desired}

        switch = self.names.switch()
        # The framework can call apply-fw-rules before the network has been
        # implement()-ed (e.g. during a pre-implement firewall pass). When
        # the LS does not yet exist, there is nothing to apply -- return a
        # benign no-op rather than crashing on RowNotFound.
        if self.ovn.by_name("Logical_Switch", switch) is None:
            LOG.info("apply-fw-rules: LS %s does not exist yet; skipping (network not implemented)", switch)
            return {"acl_count": 0, "replaced": 0, "skipped": "ls-missing"}
        default_egress_allow = parse_bool(desired.get("default_egress_allow"), True)
        cidr = str(first_present(desired, "cidr", default=self.ctx.arg("cidr") or "0.0.0.0/0"))
        rules = desired.get("rules", []) or []

        # VPC tiers use a Port_Group-based ACL list; isolated networks use
        # LS-level ACLs.
        if self.ctx.vpc_id:
            return self._sync_vpc_acl(default_egress_allow, cidr, rules)

        current = [
            row
            for row in self.ovn.owned_rows("ACL", network_id=self.ctx.network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}service") in {"Firewall", "NetworkACL"}
        ]

        acl_specs = [
            {**spec, "switch": switch}
            for spec in self._base_acls(default_egress_allow)
        ]
        for rule in rules:
            if self._is_public_firewall_rule(rule):
                acl_specs.extend(self._public_acls_from_rule(rule))
            else:
                spec = self._acl_from_rule(rule, cidr, default_egress_allow)
                if spec:
                    acl_specs.append({**spec, "switch": switch})
        acl_specs = [spec for spec in acl_specs if spec]

        with self.ovn.txn() as txn:
            for row in current:
                self._destroy_acl_everywhere(txn, row)
            for spec in acl_specs:
                txn.add(
                    self.ovn.nb.acl_add(
                        spec["switch"],
                        spec["direction"],
                        spec["priority"],
                        spec["match"],
                        spec["action"],
                        may_exist=True,
                        **spec["external_ids"],
                    )
                )
        return {"acl_count": len(acl_specs), "replaced": len(current)}

    def _destroy_acl_everywhere(self, txn: Any, row: Any) -> None:
        acl_id = row_uuid(row)
        referenced = False
        for ls in self.ovn.rows("Logical_Switch"):
            if acl_id in [row_uuid(a) for a in getattr(ls, "acls", [])]:
                referenced = True
                txn.add(
                    self.ovn.nb.acl_del(
                        row_name(ls),
                        getattr(row, "direction", None),
                        getattr(row, "priority", None),
                        getattr(row, "match", None),
                    )
                )
        if not referenced:
            txn.add(self.ovn.nb.db_destroy("ACL", acl_id))

    def _is_public_firewall_rule(self, rule: Mapping[str, Any]) -> bool:
        return first_present(rule, "publicIp", "public_ip", "publicIP", "sourceIp", "source_ip") not in (None, "")

    def _public_firewall_targets(self, public_ip: str) -> List[Tuple[str, str]]:
        targets: List[Tuple[str, str]] = []

        # Primary path: SourceNat IP is listed in the router LSP nat-addresses.
        for ls in self.ovn.rows("Logical_Switch"):
            for lsp in getattr(ls, "ports", []) or []:
                if getattr(lsp, "type", "") != "router":
                    continue
                if public_ip and public_ip not in row_options(lsp).get("nat-addresses", "").split():
                    continue
                targets.append((row_name(ls), row_name(lsp)))
        if targets:
            return targets

        # Fallback A: look up public_ls / public_lsp stored in the
        # PublicFirewall ACL (populated by apply_public_ip_firewall in new code).
        for row in self.ovn.owned_rows("ACL", network_id=self.ctx.network_id):
            ext = row_external_ids(row)
            if ext.get(f"{EXT_ID_PREFIX}service") != "PublicFirewall":
                continue
            if ext.get(f"{EXT_ID_PREFIX}public-ip") != public_ip:
                continue
            stored_ls = ext.get(f"{EXT_ID_PREFIX}public-ls")
            stored_lsp = ext.get(f"{EXT_ID_PREFIX}public-lsp")
            if stored_ls and stored_lsp:
                targets.append((stored_ls, stored_lsp))
        if targets:
            return targets

        # Fallback B: find any owned public-router-lsp for this network.
        # The first nat-addresses scan works because lsp.options is reliably
        # populated in the IDL; lsp.external_ids is equally reliable.
        # All public IPs in a zone share the same public LS / LSP, so the
        # first matching LSP is correct for any public IP on this network.
        for ls in self.ovn.rows("Logical_Switch"):
            for lsp in getattr(ls, "ports", []) or []:
                if getattr(lsp, "type", "") != "router":
                    continue
                lsp_ext = row_external_ids(lsp)
                if lsp_ext.get(f"{EXT_ID_PREFIX}owner") != OWNER:
                    continue
                if lsp_ext.get(f"{EXT_ID_PREFIX}network-id") != str(self.ctx.network_id):
                    continue
                if lsp_ext.get(f"{EXT_ID_PREFIX}service") != "public":
                    continue
                if lsp_ext.get(f"{EXT_ID_PREFIX}object") != "public-router-lsp":
                    continue
                targets.append((row_name(ls), row_name(lsp)))
        if targets:
            return targets

        # Last resort: derive from public_vlan in the current payload.
        public_vlan = self.ctx.arg("public_vlan")
        if public_vlan:
            public_ls = self.names.public_switch(public_vlan)
            public_lsp = self.names.public_router_lsp(public_vlan=public_vlan)
            if self.ovn.by_name("Logical_Switch", public_ls) is not None:
                return [(public_ls, public_lsp)]
        return []

    def _public_acls_from_rule(self, rule: Mapping[str, Any]) -> List[Dict[str, Any]]:
        public_ip = str(first_present(rule, "publicIp", "public_ip", "publicIP", "sourceIp", "source_ip"))
        targets = self._public_firewall_targets(public_ip)
        if not targets:
            LOG.warning("apply-fw-rules: public IP %s has no public router LSP; skipping public firewall rule", public_ip)
            return []

        protocol = str(first_present(rule, "protocol", default="all")).lower()
        port_start = first_present(rule, "portStart", "startport", "start_port", "public_port", "publicPort")
        port_end = first_present(rule, "portEnd", "endport", "end_port")
        port_range = None
        if port_start not in (None, "", -1, "-1"):
            port_range = f"{port_start}-{port_end or port_start}"

        base_matches = ["ip4", f"ip4.dst == {public_ip}"]
        sources = rule.get("sourceCidrs") or rule.get("source_cidrs") or ["0.0.0.0/0"]
        source_expr = ip_set_expr("ip4.src", list_csv(sources) if isinstance(sources, str) else list(sources))
        if source_expr and source_expr != "ip4.src == 0.0.0.0/0":
            base_matches.append(source_expr)

        if protocol not in {"all", "any", "ip", ""}:
            base_matches.append(protocol_match(protocol, port_range))
        if protocol == "icmp":
            icmp_type = first_present(rule, "icmpType", "icmptype", "icmp_type")
            icmp_code = first_present(rule, "icmpCode", "icmpcode", "icmp_code")
            if icmp_type not in (None, "", -1, "-1"):
                base_matches.append(f"icmp4.type == {int(icmp_type)}")
            if icmp_code not in (None, "", -1, "-1"):
                base_matches.append(f"icmp4.code == {int(icmp_code)}")

        rule_id = first_present(rule, "id", "rule_id", default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12])
        specs = []
        for public_ls, public_lsp in targets:
            match = " && ".join([f'outport == "{public_lsp}"'] + [m for m in base_matches if m])
            specs.append({
                "switch": public_ls,
                "direction": "to-lport",
                "priority": int(first_present(rule, "priority", default=1000)),
                "match": match,
                "action": "allow-related",
                "external_ids": ext_ids(
                    service="Firewall",
                    network_id=self.ctx.network_id,
                    vpc_id=self.ctx.vpc_id,
                    rule_id=rule_id,
                    kind="public-firewall-rule",
                    public_ip=public_ip,
                ),
            })
        return specs

    def _base_acls(self, default_egress_allow: bool, cidr: Optional[str] = None) -> List[Dict[str, Any]]:
        # Isolated networks need an explicit egress floor ACL when
        # default_egress_allow=True.  Without it, OVN's implicit priority-0
        # drop in ls_out_acl blocks return traffic for VM-initiated outbound
        # connections: the outbound packet leaves (from-lport) but the reply
        # arrives as a fresh ct.new packet and is dropped because no
        # ct.est entry exists in the LS conntrack zone.  Gateway-originated
        # replies (LRP→VM) bypass this because OVN's ls_out_pre_acl priority-
        # 110 flow skips ACL processing for packets whose inport is a router-
        # type LSP.
        #
        # Use allow-related so OVN commits the connection to its LS conntrack
        # zone; the automatic ct.est && !ct.inv flow at priority 65535 in
        # ls_out_acl then permits the return packets.
        #
        # Note: the earlier OFPBAC_MATCH_INCONSISTENT crash in OVN 24.03.6 /
        # OVS 3.3.4 was caused by installing BOTH a stateful ingress base ACL
        # (to-lport drop) AND a stateful egress base ACL (from-lport
        # allow-related) simultaneously.  Installing only the egress floor
        # does not trigger that bug.
        #
        # VPC tiers are different: OVN's rule is "no ACLs on an LS = allow
        # all traffic".  A freshly-created tier, or one whose ACL list is
        # empty (default-deny), would therefore be wide-open until the first
        # explicit allow rule arrives.  Install a pair of low-priority (1)
        # ACLs so the LS is in the correct default state from the moment it
        # is created.
        if not self.ctx.vpc_id:
            # Egress policy is enforced here, at the guest LS level, where
            # OVN's conntrack zone is correctly populated for VM-initiated
            # outbound flows.  It must NOT live on the public LS: the public
            # switch's conntrack zone is never populated for traffic that
            # transits the router (router-type LSPs bypass ls_in_pre_acl at
            # priority 110), so any ct.est / ct.rpl check there always
            # evaluates false and SNAT return traffic is silently dropped.
            rule_id = "default-egress-allow" if default_egress_allow else "default-egress-deny"
            kind = "default-allow" if default_egress_allow else "default-deny"
            action = "allow-related" if default_egress_allow else "drop"
            return [{
                "direction": "from-lport",
                "priority": 1,
                "match": "ip",
                "action": action,
                "external_ids": ext_ids(
                    service="Firewall",
                    network_id=self.ctx.network_id,
                    rule_id=rule_id,
                    kind=kind,
                ),
            }]
        # CloudStack VPC ACL semantics (from the specification):
        #   - Ingress: default deny  — unmatched inbound traffic is dropped
        #   - Egress:  default allow — unmatched outbound traffic is permitted
        #   - Rules are stateful: an allowed connection's return traffic is
        #     automatically permitted in the opposite direction
        #   - Intra-subnet traffic (VM↔gateway, VM↔VM in the same tier) is
        #     NEVER subject to ACL rules; only cross-tier and external traffic
        #     is controlled by the ACL list.
        #
        # The intra-subnet bypass is installed at priority 4000, which is
        # higher than the maximum user-ACL priority of 3999 (number=1 maps
        # to 4000-1=3999).  This ensures that even an explicit "deny all"
        # rule in the ACL list cannot block same-subnet traffic.
        base: List[Dict[str, Any]] = [
            {
                "direction": "to-lport",
                "priority": 1,
                "match": "ip4",
                "action": "drop",
                "external_ids": ext_ids(
                    service="NetworkACL",
                    network_id=self.ctx.network_id,
                    vpc_id=self.ctx.vpc_id,
                    rule_id="vpc-default-deny-ingress",
                    kind="default-deny",
                ),
            },
            {
                "direction": "from-lport",
                "priority": 1,
                "match": "ip4",
                "action": "allow-related",
                "external_ids": ext_ids(
                    service="NetworkACL",
                    network_id=self.ctx.network_id,
                    vpc_id=self.ctx.vpc_id,
                    rule_id="vpc-default-allow-egress",
                    kind="default-allow",
                ),
            },
        ]
        # Intra-subnet bypass: allow all IP traffic whose source (for ingress)
        # or destination (for egress) is within the tier's own CIDR.  This
        # covers VM↔gateway (LRP IP is inside the CIDR) and VM↔VM on the
        # same LS regardless of what ACL list is applied.
        if cidr and cidr not in {"0.0.0.0/0", ""}:
            src_expr = ip_set_expr("ip4.src", [cidr])
            dst_expr = ip_set_expr("ip4.dst", [cidr])
            if src_expr:
                base.append({
                    "direction": "to-lport",
                    "priority": 4000,
                    "match": src_expr,
                    "action": "allow-related",
                    "external_ids": ext_ids(
                        service="NetworkACL",
                        network_id=self.ctx.network_id,
                        vpc_id=self.ctx.vpc_id,
                        rule_id="vpc-intra-subnet-ingress",
                        kind="intra-subnet",
                    ),
                })
            if dst_expr:
                base.append({
                    "direction": "from-lport",
                    "priority": 4000,
                    "match": dst_expr,
                    "action": "allow-related",
                    "external_ids": ext_ids(
                        service="NetworkACL",
                        network_id=self.ctx.network_id,
                        vpc_id=self.ctx.vpc_id,
                        rule_id="vpc-intra-subnet-egress",
                        kind="intra-subnet",
                    ),
                })
        return base

    def _sync_vpc_acl(self, default_egress_allow: bool, cidr: str, rules: List[Any]) -> Dict[str, Any]:
        """Replace all ACLs on the VPC tier's Port_Group AND all LR policies on the VPC
        router for this tier with the desired set.

        Two-layer enforcement:
        1. Port_Group ACLs (cs_pg_acl_net_<id>) — apply to VM ports on the tier's LS.
           These handle intra-subnet traffic (VM↔gateway, VM↔VM same tier).
           OVN's ls_in_pre_acl priority-110 flow bypasses LS ACLs for traffic arriving
           from router-type LSPs, so LS ACLs alone cannot control NAT/LB/PF access.
        2. Logical_Router_Policy on the VPC router — run in lr_in_policy (after lr_in_dnat),
           never bypassed.  These enforce the ACL for all cross-tier and external traffic
           including static-NAT, port-forwarding, and load-balancer backends.
        """
        pg_name = self.names.vpc_acl_port_group()
        pg_row = self.ovn.by_name("Port_Group", pg_name)
        if pg_row is None:
            LOG.warning("apply-network-acl: Port_Group %s not found; creating it (tier not yet implemented?)", pg_name)
            with self.ovn.txn() as txn:
                txn.add(self.ovn.nb.pg_add(
                    pg_name,
                    may_exist=True,
                    external_ids=ext_ids(
                        service="NetworkACL",
                        network_id=self.ctx.network_id,
                        vpc_id=self.ctx.vpc_id,
                        object="tier-acl-pg",
                    ),
                ))
            pg_row = self.ovn.by_name("Port_Group", pg_name)

        prior_pg_count = len(list(getattr(pg_row, "acls", []))) if pg_row else 0

        user_rules = [r for r in rules if not self._is_public_firewall_rule(r)]

        # --- Layer 1: Port_Group ACLs (intra-subnet + stateful tracking base) ---
        acl_specs = list(self._base_acls(default_egress_allow, cidr))
        for rule in user_rules:
            spec = self._acl_from_rule(rule, cidr, default_egress_allow)
            if spec:
                acl_specs.append(spec)

        with self.ovn.txn() as txn:
            txn.add(self.ovn.nb.pg_acl_del(pg_name))
            for spec in acl_specs:
                txn.add(
                    self.ovn.nb.pg_acl_add(
                        pg_name,
                        spec["direction"],
                        spec["priority"],
                        spec["match"],
                        spec["action"],
                        may_exist=True,
                        **spec["external_ids"],
                    )
                )

        result: Dict[str, Any] = {"acl_count": len(acl_specs), "replaced": prior_pg_count}

        # --- Layer 2: Logical_Router_Policy (cross-tier and external traffic) ---
        if cidr and cidr not in {"0.0.0.0/0", ""} and self.ovn.table_exists("Logical_Router_Policy"):
            router = self.names.router(vpc_id=self.ctx.vpc_id)
            existing_lr = self.ovn.owned_rows("Logical_Router_Policy", network_id=self.ctx.network_id)
            lr_policies = self._build_lr_policies(cidr, user_rules)
            with self.ovn.txn() as txn:
                for ep in existing_lr:
                    txn.add(self.ovn.nb.db_remove(
                        "Logical_Router", router, "policies", row_uuid(ep), if_exists=True,
                    ))
                    txn.add(self.ovn.nb.db_destroy("Logical_Router_Policy", row_uuid(ep)))
                for policy in lr_policies:
                    create = txn.add(self.ovn.nb.db_create_row("Logical_Router_Policy", **policy))
                    txn.add(self.ovn.nb.db_add("Logical_Router", router, "policies", create))
            result["lr_policy_count"] = len(lr_policies)

        return result

    def _build_lr_policies(self, cidr: str, rules: List[Any]) -> List[Dict[str, Any]]:
        """Build Logical_Router_Policy rows for a VPC tier.

        - Default deny ingress at priority 1000: blocks new cross-tier/external
          connections to this tier that don't match a higher-priority rule.
        - User ACL rules at priority 1001-2000: allow or deny specific flows.
        - No default drop for egress: OVN LR allows unmatched traffic by default,
          matching CloudStack's 'outgoing traffic not matched → allowed' semantics.

        All drop policies include `ct.new` so they fire only for new connection
        attempts — NOT for established/reply packets (ct.est, ct.rel, ct.dnat).
        This is the standard OVN stateful-policy idiom.  It ensures that:
        - Return traffic for VM-initiated outbound connections (SNAT replies) is
          never dropped even with a default-deny-ingress policy, because
          lr_in_unsnat marks those packets as ct.est/ct.dnat, not ct.new.
        - Reply traffic for explicitly allowed ingress connections is not blocked
          by a subsequent egress deny rule (ct.est bypasses all ct.new drops).
        """
        # Base priority for the default deny; user rules sit at base+1 to base+1000.
        BASE = 1000
        policies: List[Dict[str, Any]] = []

        # Default deny ingress for NEW connections only.  Established/related
        # packets (ct.est, ct.rel) are not ct.new and fall through to the
        # implicit OVN allow for unmatched LR policies.
        policies.append({
            "priority": BASE,
            "match": f"ip4.dst == {cidr} && ct.new",
            "action": "drop",
            "external_ids": ext_ids(
                service="NetworkACL",
                network_id=self.ctx.network_id,
                vpc_id=self.ctx.vpc_id,
                rule_id="lr-default-deny-ingress",
                kind="lr-policy-default",
            ),
        })

        for rule in rules:
            spec = self._lr_policy_from_rule(rule, cidr, BASE + 1)
            if spec:
                policies.append(spec)

        return policies

    def _lr_policy_from_rule(self, rule: Mapping[str, Any], cidr: str, base_priority: int) -> Optional[Dict[str, Any]]:
        """Convert one CloudStack ACL rule to an OVN Logical_Router_Policy spec."""
        rule_type = str(first_present(rule, "type", "trafficType", default="ingress")).lower()
        protocol = str(first_present(rule, "protocol", default="all")).lower()
        port_start = first_present(rule, "portStart", "startport")
        port_end = first_present(rule, "portEnd", "endport")
        port_range = None
        if port_start not in (None, "", -1, "-1"):
            port_range = f"{port_start}-{port_end or port_start}"

        matches: List[str] = []

        if rule_type == "ingress":
            matches.append(f"ip4.dst == {cidr}")
            sources = rule.get("sourceCidrs") or rule.get("source_cidrs") or []
            src_list = list_csv(sources) if isinstance(sources, str) else list(sources)
            src_expr = ip_set_expr("ip4.src", src_list)
            if src_expr and src_expr != "ip4.src == 0.0.0.0/0":
                matches.append(src_expr)
        else:
            matches.append(f"ip4.src == {cidr}")
            dests = rule.get("destCidrs") or rule.get("dest_cidrs") or []
            dst_list = list_csv(dests) if isinstance(dests, str) else list(dests)
            dst_expr = ip_set_expr("ip4.dst", dst_list)
            if dst_expr and dst_expr != "ip4.dst == 0.0.0.0/0":
                matches.append(dst_expr)

        if protocol not in {"all", "any", "ip", ""}:
            proto = protocol_match(protocol, port_range)
            if proto and proto != "ip":
                matches.append(proto)
            if protocol == "icmp":
                icmp_type = first_present(rule, "icmpType", "icmptype")
                icmp_code = first_present(rule, "icmpCode", "icmpcode")
                if icmp_type not in (None, "", -1, "-1"):
                    matches.append(f"icmp4.type == {int(icmp_type)}")
                if icmp_code not in (None, "", -1, "-1"):
                    matches.append(f"icmp4.code == {int(icmp_code)}")

        # Explicit action field (VPC ACL) takes precedence over legacy deny/revoke flag.
        rule_action = str(first_present(rule, "action", default="")).strip().lower()
        if rule_action in {"deny", "drop", "reject"}:
            action = "drop"
        else:
            action = "allow"

        # Drop rules are stateful: only fire for ct.new (new connection attempts).
        # This preserves established connections (ct.est / ct.rel) from being
        # interrupted when rules change, and lets reply traffic for allowed
        # connections flow back without needing a matching egress allow rule.
        if action == "drop":
            matches.append("ct.new")

        # Priority: lower ACL number = higher OVN priority (same mapping as Port_Group).
        rule_number = first_present(rule, "number", default=None)
        if rule_number is not None:
            priority = base_priority + max(0, 1000 - int(rule_number))
        else:
            priority = int(first_present(rule, "priority", default=base_priority))

        rule_id = first_present(rule, "id", "rule_id", default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12])
        match_str = " && ".join(m for m in matches if m)
        if not match_str:
            return None
        return {
            "priority": priority,
            "match": match_str,
            "action": action,
            "external_ids": ext_ids(
                service="NetworkACL",
                network_id=self.ctx.network_id,
                vpc_id=self.ctx.vpc_id,
                rule_id=rule_id,
                kind="lr-policy-rule",
            ),
        }

    def _acl_from_rule(self, rule: Mapping[str, Any], cidr: str, default_egress_allow: bool) -> Optional[Dict[str, Any]]:
        rule_type = str(first_present(rule, "type", "trafficType", default="ingress")).lower()
        direction = "to-lport" if rule_type == "ingress" else "from-lport"
        protocol = str(first_present(rule, "protocol", default="all")).lower()
        port_start = first_present(rule, "portStart", "startport", "public_port")
        port_end = first_present(rule, "portEnd", "endport")
        port_range = None
        if port_start not in (None, "", -1, "-1"):
            port_range = f"{port_start}-{port_end or port_start}"

        matches = [protocol_match(protocol, port_range)]
        if protocol == "icmp":
            icmp_type = first_present(rule, "icmpType", "icmptype")
            icmp_code = first_present(rule, "icmpCode", "icmpcode")
            if icmp_type not in (None, "", -1, "-1"):
                matches.append(f"icmp4.type == {int(icmp_type)}")
            if icmp_code not in (None, "", -1, "-1"):
                matches.append(f"icmp4.code == {int(icmp_code)}")

        if rule_type == "ingress":
            sources = rule.get("sourceCidrs") or rule.get("source_cidrs") or ["0.0.0.0/0"]
            expr = ip_set_expr("ip4.src", list_csv(sources) if isinstance(sources, str) else list(sources))
            if expr:
                matches.append(expr)
            # Isolated-network (LS-level) ACLs need an explicit destination
            # match to scope the rule to this tier's subnet.  VPC tier ACLs
            # are applied via a Port_Group whose members are already the VM
            # ports — no ip4.dst needed.
            if not self.ctx.vpc_id:
                dst_expr = ip_set_expr("ip4.dst", [cidr])
                if dst_expr:
                    matches.append(dst_expr)
        else:
            dests = rule.get("destCidrs") or rule.get("dest_cidrs") or ["0.0.0.0/0"]
            expr = ip_set_expr("ip4.dst", list_csv(dests) if isinstance(dests, str) else list(dests))
            if expr:
                matches.append(expr)

        # Determine OVN action.
        # Modern CloudStack sends an explicit "action" field (allow/deny) for
        # both VPC ACL rules and isolated-network firewall rules.  Legacy
        # payloads omit it and rely on the deny/revoke flag instead.
        #
        # VPC stateful semantics: allowed connections track state so return
        # traffic is automatically permitted in the opposite direction.
        # Use allow-related (not plain allow) for every allow action.
        rule_action = str(first_present(rule, "action", default="")).strip().lower()
        if rule_action in {"allow", "permit"}:
            action = "allow-related"
        elif rule_action in {"deny", "drop", "reject"}:
            action = "drop"
        elif rule_type == "ingress":
            # Legacy ingress rules are always allow-list entries.
            action = "allow-related"
        elif not default_egress_allow:
            # default_egress_allow=False: base ACL already blocks all egress;
            # explicit rules in this context are allow-list entries.
            action = "allow-related"
        else:
            # default_egress_allow=True: base ACL already permits all egress;
            # explicit rules in this context are block rules.  Legacy payloads
            # that set deny=false explicitly are honoured as allow-related;
            # anything else (including no deny field) defaults to drop.
            deny_flag = first_present(rule, "deny", default=None)
            action = "allow-related" if deny_flag is not None and not parse_bool(deny_flag) else "drop"

        rule_id = first_present(rule, "id", "rule_id", default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12])

        # VPC Network ACL rules are tagged differently from isolated-network
        # firewall rules so cleanup scoping is semantically correct.
        is_vpc_acl = bool(self.ctx.vpc_id)
        service = "NetworkACL" if is_vpc_acl else "Firewall"
        kind = "network-acl-rule" if is_vpc_acl else "firewall-rule"

        # VPC ACL rules use CloudStack's 'number' field for ordering: lower
        # number = higher priority in CloudStack → higher OVN priority number.
        # Isolated-network rules use an explicit 'priority' field directly.
        rule_number = first_present(rule, "number", default=None)
        if is_vpc_acl and rule_number is not None:
            priority = max(3000, min(3999, 4000 - int(rule_number)))
        else:
            priority = int(first_present(rule, "priority", default=3000))

        return {
            "direction": direction,
            "priority": priority,
            "match": " && ".join(m for m in matches if m),
            "action": action,
            "external_ids": ext_ids(
                service=service,
                network_id=self.ctx.network_id,
                vpc_id=self.ctx.vpc_id,
                rule_id=rule_id,
                kind=kind,
            ),
        }


class SecurityGroupService(BaseService):
    service_name = "security-groups"

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        groups = desired.get("security_groups", desired.get("groups", [])) or []
        updated = 0
        with self.ovn.txn() as txn:
            for group in groups:
                self._sync_group(txn, group)
                updated += 1
        return {"security_groups": updated}

    def _sync_group(self, txn: Any, group: Mapping[str, Any]) -> None:
        group_id = str(first_present(group, "id", "name"))
        pg = self.names.port_group(group_id)
        members = group.get("members", []) or []
        ips_v4 = [m["ip"] for m in members if m.get("ip") and ip_version(str(m["ip"])) == 4]
        ips_v6 = [m["ip"] for m in members if m.get("ip") and ip_version(str(m["ip"])) == 6]
        as4 = self.names.address_set("sg", group_id, 4)
        as6 = self.names.address_set("sg", group_id, 6)

        txn.add(
            self.ovn.nb.pg_add(
                pg,
                may_exist=True,
                external_ids=ext_ids(service="SecurityGroup", network_id=self.ctx.network_id, vpc_id=self.ctx.vpc_id, group_id=group_id),
            )
        )
        for member in members:
            member_mac = str(member.get("mac") or "")
            lsp = member.get("lsp") or (
                self.names.vm_lsp(member_mac, nic_uuid=member.get("nic_uuid"))
                if member_mac or member.get("nic_uuid") else None
            )
            if lsp:
                txn.add(self.ovn.nb.pg_add_ports(pg, lsp))

        for name, addresses in ((as4, ips_v4), (as6, ips_v6)):
            txn.add(
                self.ovn.nb.address_set_add(
                    name,
                    addresses=addresses,
                    may_exist=True,
                    external_ids=ext_ids(service="SecurityGroup", network_id=self.ctx.network_id, vpc_id=self.ctx.vpc_id, group_id=group_id),
                )
            )
            txn.add(self.ovn.nb.db_set("Address_Set", name, ("addresses", addresses), if_exists=True))

        for row in self.ovn.owned_rows("ACL", group_id=group_id):
            self.ovn.destroy_referenced_row(txn, "Port_Group", pg, "acls", "ACL", row)

        for direction_name, acl_direction in (("ingress", "to-lport"), ("egress", "from-lport")):
            for rule in group.get(direction_name, []) or []:
                spec = self._sg_acl(group_id, rule, acl_direction)
                txn.add(
                    self.ovn.nb.pg_acl_add(
                        pg,
                        spec["direction"],
                        spec["priority"],
                        spec["match"],
                        "allow-related",
                        may_exist=True,
                        **spec["external_ids"],
                    )
                )

    def _sg_acl(self, group_id: str, rule: Mapping[str, Any], direction: str) -> Dict[str, Any]:
        protocol = str(first_present(rule, "protocol", default="all")).lower()
        port_range = None
        if first_present(rule, "portStart", "startport") not in (None, "", -1, "-1"):
            port_range = f"{first_present(rule, 'portStart', 'startport')}-{first_present(rule, 'portEnd', 'endport', default=first_present(rule, 'portStart', 'startport'))}"
        matches = [protocol_match(protocol, port_range)]
        remote_group = first_present(rule, "remote_group_id", "securitygroupid")
        cidrs = rule.get("cidrs") or rule.get("sourceCidrs") or rule.get("destCidrs")
        if remote_group:
            as_name = self.names.address_set("sg", remote_group, 4)
            field = "ip4.src" if direction == "to-lport" else "ip4.dst"
            matches.append(f"{field} == ${as_name}")
        elif cidrs:
            field = "ip4.src" if direction == "to-lport" else "ip4.dst"
            matches.append(ip_set_expr(field, list_csv(cidrs) if isinstance(cidrs, str) else list(cidrs)))
        rule_id = first_present(rule, "id", "rule_id", default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12])
        return {
            "direction": direction,
            "priority": int(first_present(rule, "priority", default=3100)),
            "match": " && ".join(m for m in matches if m),
            "external_ids": ext_ids(
                service="SecurityGroup",
                network_id=self.ctx.network_id,
                vpc_id=self.ctx.vpc_id,
                group_id=group_id,
                rule_id=rule_id,
            ),
        }


class DhcpService(BaseService):
    service_name = "dhcp"

    DHCP_CODE_MAP = {
        "1": "netmask",
        "3": "router",
        "6": "dns_server",
        "15": "domain_name",
        "26": "mtu",
        "28": "broadcast_address",
        "51": "lease_time",
        "121": "classless_static_route",
        "119": "domain_search",
    }

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        count = 0
        for subnet in desired.get("subnets", []) or []:
            self.configure_subnet(subnet)
            count += 1
        for lease in desired.get("leases", []) or []:
            self.add_entry(lease)
            count += 1
        return {"dhcp_objects": count}

    def configure_subnet(self, subnet: Mapping[str, Any]) -> Dict[str, Any]:
        cidr = str(first_present(subnet, "cidr", default=self.ctx.arg("cidr")))
        gateway = str(first_present(subnet, "gateway", default=self.ctx.arg("gateway")))
        dns = list_csv(first_present(subnet, "dns", default=self.ctx.arg("dns")))
        domain = str(first_present(subnet, "domain", default=self.ctx.arg("domain") or self.ctx.config.default_domain))
        options = self._base_options(cidr, gateway, dns, domain, first_present(subnet, "mtu", default=self.ctx.arg("mtu")))
        row = self._find_subnet_options(cidr)
        with self.ovn.txn() as txn:
            if row is None:
                create = txn.add(
                    self.ovn.nb.dhcp_options_add(
                        cidr,
                        **ext_ids(service="Dhcp", network_id=self.ctx.network_id, vpc_id=self.ctx.vpc_id, kind="subnet", cidr=cidr),
                    )
                )
                txn.add(self.ovn.nb.dhcp_options_set_options(create, **options))
            else:
                txn.add(self.ovn.nb.dhcp_options_set_options(row_uuid(row), **options))
                self.ovn.add_ext_ids(txn, "DHCP_Options", row_uuid(row), ext_ids(service="Dhcp", network_id=self.ctx.network_id, vpc_id=self.ctx.vpc_id, kind="subnet", cidr=cidr))
        return {"cidr": cidr}

    def add_entry(self, lease: Mapping[str, Any]) -> Dict[str, Any]:
        mac = str(first_present(lease, "mac", default=self.ctx.arg("mac")))
        ip = str(first_present(lease, "ip", default=self.ctx.arg("ip")))
        hostname = str(first_present(lease, "hostname", default=self.ctx.arg("hostname") or "vm"))
        cidr = str(first_present(lease, "cidr", default=self.ctx.arg("cidr")))
        gateway = str(first_present(lease, "gateway", default=self.ctx.arg("gateway")))
        dns = list_csv(first_present(lease, "dns", default=self.ctx.arg("dns")))
        domain = str(first_present(lease, "domain", default=self.ctx.arg("domain") or self.ctx.config.default_domain))
        nic_uuid = first_present(lease, "nic_uuid", default=self.ctx.arg("nic_uuid"))
        lsp = str(first_present(lease, "lsp", default=self.names.vm_lsp(mac, nic_uuid=nic_uuid)))
        options = self._base_options(cidr, gateway, dns, domain, first_present(lease, "mtu", default=self.ctx.arg("mtu")))
        options["hostname"] = f'"{hostname}"'
        extra = maybe_json(first_present(lease, "options", default=self.ctx.arg("options")), {}) or {}
        options.update(self._translate_options(extra))

        # Avoid duplicate LSPs for the same VM NIC.  When the framework
        # supplied a nic_uuid the canonical LSP name is the UUID-based one;
        # any MAC-based LSP from a previous run is stale and would confuse
        # ovn-controller (two ports with the same MAC address). Remove it.
        if nic_uuid and mac:
            mac_lsp = self.names.vm_lsp(mac)  # MAC-based name (no nic_uuid)
            if mac_lsp and mac_lsp != lsp and self.ovn.by_name("Logical_Switch_Port", mac_lsp) is not None:
                LOG.info("removing stale MAC-based LSP %s in favour of nic_uuid LSP %s", mac_lsp, lsp)
                with self.ovn.txn() as txn:
                    txn.add(self.ovn.nb.lsp_del(mac_lsp, if_exists=True))

        # First transaction: create LSP and DHCP_Options (if needed) and
        # set the DHCP option fields. Cannot link the LSP to the
        # DHCP_Options in this same transaction because
        # ``lsp_set_dhcpv4_options`` resolves its DHCP_Options argument
        # via ``api.lookup("DHCP_Options", uuid)`` and that lookup runs
        # before the ``dhcp_options_add`` command's result UUID is
        # populated -- so the link silently fails to take and the LSP
        # ends up with an empty ``dhcpv4_options`` column.
        row = self._find_port_options(mac, ip)
        create_cmd = None
        with self.ovn.txn() as txn:
            if self.ctx.config.manage_lsp_for_nics:
                txn.add(
                    self.ovn.nb.lsp_add(
                        self.names.vm_switch(),
                        lsp,
                        may_exist=True,
                        addresses=[f"{mac} {ip}"],
                        port_security=[f"{mac} {ip}"],
                        external_ids=ext_ids(
                            service="Dhcp",
                            network_id=self.ctx.network_id,
                            vpc_id=self.ctx.vpc_id,
                            mac=mac,
                            ip=ip,
                            hostname=hostname,
                            kind="vm-lsp",
                        ),
                    )
                )
                # For VPC tiers, add the VM port to the tier's ACL Port_Group
                # so that NetworkACL rules apply to it.  pg_add(may_exist=True)
                # is a safety net for the case where implement-network has not
                # yet run (e.g. out-of-order calls).
                if self.ctx.vpc_id:
                    pg_name = self.names.vpc_acl_port_group()
                    txn.add(self.ovn.nb.pg_add(
                        pg_name,
                        may_exist=True,
                        external_ids=ext_ids(
                            service="NetworkACL",
                            network_id=self.ctx.network_id,
                            vpc_id=self.ctx.vpc_id,
                            object="tier-acl-pg",
                        ),
                    ))
                    txn.add(self.ovn.nb.pg_add_ports(pg_name, lsp))
            if row is None:
                create_cmd = txn.add(
                    self.ovn.nb.dhcp_options_add(
                        cidr,
                        **ext_ids(service="Dhcp", network_id=self.ctx.network_id, vpc_id=self.ctx.vpc_id, mac=mac, ip=ip, hostname=hostname, kind="lease"),
                    )
                )
                txn.add(self.ovn.nb.dhcp_options_set_options(create_cmd, **options))
            else:
                txn.add(self.ovn.nb.dhcp_options_set_options(row_uuid(row), **options))

        # Second transaction: link the LSP to the DHCP_Options row.  Cannot
        # be done in the same txn because ``lsp_set_dhcpv4_options`` looks
        # up the DHCP_Options argument BEFORE ``dhcp_options_add`` populates
        # its result UUID.
        #
        # Empirically the ovsdbapp helper ``lsp_set_dhcpv4_options`` reports
        # "Transaction caused no change" when called immediately after the
        # first commit -- the IDL cache for the freshly created LSP/
        # DHCP_Options rows is not fully reconciled yet, so the IDL diff
        # produced by ``port.dhcpv4_options = [dhcp_opt]`` ends up empty.
        # To avoid that pitfall we:
        #   (1) force an IDL ``run()`` to drain monitor updates,
        #   (2) re-resolve the DHCP_Options row from the NB,
        #   (3) write the link with an explicit ``db_set(... uuid.UUID(...))``
        #       so the ovsdb operation is a plain reference assignment that
        #       does not rely on IDL Row state.
        try:
            self.ovn.nb.idl.run()
        except Exception:
            pass

        dhcp_row = self._find_port_options(mac, ip)
        dhcp_uuid_str: Optional[str] = None
        if dhcp_row is not None:
            dhcp_uuid_str = row_uuid(dhcp_row)
        elif create_cmd is not None and getattr(create_cmd, "result", None) is not None:
            # Fall back to the freshly committed row's UUID.
            dhcp_uuid_str = row_uuid(create_cmd.result)
        elif row is not None:
            dhcp_uuid_str = row_uuid(row)

        if not dhcp_uuid_str:
            LOG.warning(
                "add-dhcp-entry: DHCP_Options row for mac=%s ip=%s not found after create; LSP %s left without dhcpv4_options",
                mac, ip, lsp,
            )
            return {"lsp": lsp, "ip": ip, "dhcp_options": None}

        try:
            dhcp_uuid_obj = _uuid.UUID(dhcp_uuid_str)
        except (TypeError, ValueError):
            LOG.warning(
                "add-dhcp-entry: DHCP_Options uuid %r is not parseable; LSP %s left without dhcpv4_options",
                dhcp_uuid_str, lsp,
            )
            return {"lsp": lsp, "ip": ip, "dhcp_options": dhcp_uuid_str}

        LOG.debug("add-dhcp-entry: linking LSP %s -> DHCP_Options %s", lsp, dhcp_uuid_obj)
        with self.ovn.txn() as txn:
            # ``db_set`` writes the column directly via a low-level ovsdb
            # operation: for a set<DHCP_Options> column ovsdbapp serialises
            # ``uuid.UUID`` atoms as proper ovsdb UUID references, so this
            # bypasses ``lsp_set_dhcpv4_options``'s IDL-Row-based path that
            # was silently producing "no change".
            txn.add(
                self.ovn.nb.db_set(
                    "Logical_Switch_Port",
                    lsp,
                    ("dhcpv4_options", [dhcp_uuid_obj]),
                )
            )
        return {"lsp": lsp, "ip": ip, "dhcp_options": dhcp_uuid_str}

    def remove_entry(self, lease: Mapping[str, Any]) -> Dict[str, Any]:
        mac = str(first_present(lease, "mac", default=self.ctx.arg("mac") or ""))
        ip = str(first_present(lease, "ip", default=self.ctx.arg("ip") or ""))
        nic_uuid = first_present(lease, "nic_uuid", default=self.ctx.arg("nic_uuid"))
        lsp = str(first_present(lease, "lsp", default=self.names.vm_lsp(mac, nic_uuid=nic_uuid) if (mac or nic_uuid) else ""))
        deleted = 0
        with self.ovn.txn() as txn:
            if lsp:
                if self.ctx.config.manage_lsp_for_nics:
                    txn.add(self.ovn.nb.lsp_del(lsp, if_exists=True))
                else:
                    txn.add(self.ovn.nb.db_clear("Logical_Switch_Port", lsp, "dhcpv4_options"))
            for row in self.ovn.owned_rows("DHCP_Options", network_id=self.ctx.network_id):
                ext = row_external_ids(row)
                if (mac and ext.get(f"{EXT_ID_PREFIX}mac") == mac) or (ip and ext.get(f"{EXT_ID_PREFIX}ip") == ip):
                    txn.add(self.ovn.nb.dhcp_options_del(row_uuid(row)))
                    deleted += 1
        return {"deleted": deleted}

    def set_options(self) -> Dict[str, Any]:
        options = maybe_json(self.ctx.arg("options"), {}) or {}
        translated = self._translate_options(options)
        nic_id = self.ctx.arg("nic_id")
        updated = 0
        with self.ovn.txn() as txn:
            for row in self.ovn.owned_rows("DHCP_Options", network_id=self.ctx.network_id):
                ext = row_external_ids(row)
                if nic_id and ext.get(f"{EXT_ID_PREFIX}nic-id") != str(nic_id):
                    continue
                current = row_options(row)
                current.update(translated)
                txn.add(self.ovn.nb.dhcp_options_set_options(row_uuid(row), **current))
                self.ovn.add_ext_ids(txn, "DHCP_Options", row_uuid(row), {f"{EXT_ID_PREFIX}nic-id": nic_id})
                updated += 1
        return {"updated": updated}

    def _base_options(self, cidr: str, gateway: str, dns: Sequence[str], domain: str, mtu: Any = None) -> Dict[str, str]:
        network = ipaddress.ip_network(cidr, strict=False)
        options = {
            "server_id": gateway,
            "server_mac": stable_mac(f"dhcp:{self.ctx.network_id}"),
            "router": gateway,
            "lease_time": "3600",
            "mtu": str(mtu or "1450"),
        }
        if network.version == 4:
            options["netmask"] = str(network.netmask)
            options["broadcast_address"] = str(network.broadcast_address)

        # Prepend the gateway so it appears as the first DNS server.
        # OVN intercepts all DNS queries at the Logical Switch level (port 53,
        # any destination IP) and answers from its DNS rows, so internal VM
        # hostnames are resolved regardless of which server the VM is querying.
        # External queries that don't match OVN DNS rows fall through to the
        # subsequent servers in the list.
        if gateway and not dns:
            dns = [gateway]
        elif gateway and gateway not in dns:
            dns = [gateway] + dns
        if dns:
            options["dns_server"] = "{" + ", ".join(dns) + "}"
        if domain:
            options["domain_name"] = f'"{domain}"'
        if self.ctx.config.metadata_mode == "static-route" and self.ctx.arg("extension_ip"):
            options["classless_static_route"] = f'{{{METADATA_IP}/32,{self.ctx.arg("extension_ip")},0.0.0.0/0,{gateway}}}'
        return options

    def _translate_options(self, options: Mapping[str, Any]) -> Dict[str, str]:
        translated: Dict[str, str] = {}
        for key, value in options.items():
            ovn_key = self.DHCP_CODE_MAP.get(str(key), str(key))
            if isinstance(value, (list, tuple)):
                translated[ovn_key] = "{" + ", ".join(str(v) for v in value) + "}"
            else:
                translated[ovn_key] = str(value)
        return translated

    def _find_subnet_options(self, cidr: str) -> Optional[Any]:
        for row in self.ovn.owned_rows("DHCP_Options", network_id=self.ctx.network_id):
            ext = row_external_ids(row)
            if ext.get(f"{EXT_ID_PREFIX}kind") == "subnet" and getattr(row, "cidr", None) == cidr:
                return row
        return None

    def _find_port_options(self, mac: str, ip: str) -> Optional[Any]:
        for row in self.ovn.owned_rows("DHCP_Options", network_id=self.ctx.network_id):
            ext = row_external_ids(row)
            if ext.get(f"{EXT_ID_PREFIX}kind") == "lease" and (
                ext.get(f"{EXT_ID_PREFIX}mac") == mac or ext.get(f"{EXT_ID_PREFIX}ip") == ip
            ):
                return row
        return None

    def remove_subnet(self) -> Dict[str, Any]:
        """Delete the subnet-level DHCP_Options row for this network."""
        subnet_rows = [
            row for row in self.ovn.owned_rows("DHCP_Options", network_id=self.ctx.network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}kind") == "subnet"
        ]
        deleted = 0
        with self.ovn.txn() as txn:
            for row in subnet_rows:
                txn.add(self.ovn.nb.dhcp_options_del(row_uuid(row)))
                deleted += 1
        return {"deleted": deleted}


class DnsService(BaseService):
    service_name = "dns"

    def _tier_switches(self) -> List[str]:
        """Return the LS names where DNS rows must be attached.

        For VPC tiers, OVN answers DNS queries at the LS level, so every DNS
        row must be registered on *every* tier LS in the VPC — otherwise a VM
        on tier2 cannot resolve hostnames of VMs on tier1.
        For isolated networks a single LS is sufficient.
        """
        if not self.ctx.vpc_id:
            return [self.names.vm_switch()]
        return [
            row_name(row)
            for row in self.ovn.owned_rows("Logical_Switch", vpc_id=self.ctx.vpc_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}object") == "logical-switch"
        ]

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        domain = str(first_present(desired, "domain", default=self.ctx.arg("domain") or self.ctx.config.default_domain)).strip(".")
        switches = self._tier_switches()

        # Index existing per-VM DNS rows by hostname so we can update rather than recreate.
        existing: Dict[str, Any] = {}
        for row in self.ovn.owned_rows("DNS", network_id=self.ctx.network_id, kind="vm"):
            hostname = row_external_ids(row).get(f"{EXT_ID_PREFIX}hostname", "")
            if hostname:
                existing[hostname] = row

        linked = 0
        seen_hostnames: set = set()
        with self.ovn.txn() as txn:
            for item in desired.get("records", []) or []:
                host = str(first_present(item, "hostname", "name"))
                ip = str(first_present(item, "ip", "address"))
                if not host or not ip:
                    continue
                seen_hostnames.add(host)
                vm_records: Dict[str, str] = {host: ip}
                if domain and "." not in host:
                    vm_records[f"{host}.{domain}"] = ip
                row = existing.get(host)
                if row is None:
                    create = txn.add(self.ovn.nb.dns_add(
                        records=vm_records,
                        external_ids=ext_ids(service="Dns", network_id=self.ctx.network_id,
                                             vpc_id=self.ctx.vpc_id, kind="vm", hostname=host),
                    ))
                    for sw in switches:
                        txn.add(self.ovn.nb.ls_add_dns_record(sw, create))
                else:
                    txn.add(self.ovn.nb.dns_set_records(row_uuid(row), **vm_records))
                    for sw in switches:
                        txn.add(self.ovn.nb.ls_add_dns_record(sw, _uuid.UUID(row_uuid(row))))
                linked += 1
            # Prune DNS rows whose hostname is no longer in the desired set
            # (handles VM renames — old hostname row is deleted, new one created above).
            for hostname, stale_row in existing.items():
                if hostname not in seen_hostnames:
                    txn.add(self.ovn.nb.dns_del(row_uuid(stale_row)))
        return {"records": linked}

    def add_entry(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        hostname = str(first_present(entry, "hostname", default=self.ctx.arg("hostname")))
        ip = str(first_present(entry, "ip", default=self.ctx.arg("ip")))
        domain = str(first_present(entry, "domain", default=self.ctx.arg("domain") or self.ctx.config.default_domain)).strip(".")

        records: Dict[str, str] = {hostname: ip}
        if domain and "." not in hostname:
            records[f"{hostname}.{domain}"] = ip

        row = self._find_dns_row(hostname=hostname)

        if row is None:
            # Txn A: create DNS row with records already embedded so we never
            # need dns_add_record (which replaces the whole records map rather
            # than inserting into it, wiping other hostnames).
            with self.ovn.txn() as txn:
                create_cmd = txn.add(self.ovn.nb.dns_add(
                    records=records,
                    external_ids=ext_ids(service="Dns", network_id=self.ctx.network_id,
                                         vpc_id=self.ctx.vpc_id, kind="vm", hostname=hostname),
                ))
            dns_uuid = row_uuid(create_cmd.result) if getattr(create_cmd, "result", None) else None
            LOG.debug("add-dns-entry: created DNS row %s for hostname=%s with records %s", dns_uuid, hostname, records)
        else:
            # Txn A: add/update keys in the existing row.
            # db_add on a map column → OVSDB mutate/insert: additive, does NOT
            # replace other keys already present in the map.
            dns_uuid = row_uuid(row)
            with self.ovn.txn() as txn:
                txn.add(self.ovn.nb.db_add("DNS", dns_uuid, "records", records))

        if not dns_uuid:
            LOG.warning("add-dns-entry: DNS row UUID unavailable for %s; dns_records not updated", hostname)
            return {"hostname": hostname, "ip": ip, "records": 0}

        # Txn B: register the DNS row on all tier LSes so cross-tier hostname
        # resolution works.  db_add → OVSDB mutate/insert (additive, idempotent).
        switches = self._tier_switches()
        with self.ovn.txn() as txn:
            for sw in switches:
                LOG.debug("add-dns-entry: adding DNS row %s to switch %s dns_records", dns_uuid, sw)
                txn.add(self.ovn.nb.ls_add_dns_record(sw, _uuid.UUID(dns_uuid)))

        return {"hostname": hostname, "ip": ip, "records": len(records)}

    def remove_entry(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        hostname = str(first_present(entry, "hostname", default=self.ctx.arg("hostname") or ""))
        domain = str(first_present(entry, "domain", default=self.ctx.arg("domain") or self.ctx.config.default_domain)).strip(".")
        if not hostname:
            return {"deleted": 0}
        row = self._find_dns_row(hostname=hostname)
        LOG.debug("remove-dns-entry: removing hostname=%s domain=%s (existing row: %s)", hostname, domain, row_uuid(row) if row else None)
        if row is None:
            return {"deleted": 0}
        keys_to_remove = [hostname]
        if domain and "." not in hostname:
            keys_to_remove.append(f"{hostname}.{domain}")
        removed = 0
        with self.ovn.txn() as txn:
            for key in keys_to_remove:
                LOG.debug("remove-dns-entry: removing DNS record %s from DNS row %s", key, row_uuid(row))
                txn.add(self.ovn.nb.db_remove("DNS", row_uuid(row), "records", key))
                removed += 1
        return {"deleted": removed}

    def remove_subnet(self) -> Dict[str, Any]:
        rows = self.list_dns_rows()
        if not rows:
            return {"deleted": 0}
        # For VPC tiers, each DNS row was attached to all tier LSes in the VPC;
        # remove from all of them before destroying the row.
        switches = self._tier_switches()
        with self.ovn.txn() as txn:
            for row in rows:
                for sw in switches:
                    txn.add(self.ovn.nb.db_remove(
                        "Logical_Switch", sw, "dns_records", row_uuid(row), if_exists=True,
                    ))
                txn.add(self.ovn.nb.db_destroy("DNS", row_uuid(row)))
        return {"deleted": len(rows)}

    def list_dns_rows(self) -> List[Any]:
        """Return all owned DNS rows for this network."""
        return self.ovn.owned_rows("DNS", network_id=self.ctx.network_id)

    def _find_dns_row(self, hostname: str) -> Optional[Any]:
        """Return an owned DNS row for this network.

        When *hostname* is ``None`` (default) the first owned row is returned
        — the original behaviour used by ``sync`` and ``remove_subnet``.

        When *hostname* is provided, the method searches for a row whose
        ``records`` map contains that hostname as a key (short name or FQDN).
        Returns ``None`` if no matching row is found.
        """
        rows = self.ovn.owned_rows("DNS", network_id=self.ctx.network_id)
        if not rows:
            return None
        for row in rows:
            ext = row_external_ids(row)
            if ext.get(f"{EXT_ID_PREFIX}kind") == "vm" and ext.get(f"{EXT_ID_PREFIX}hostname") == hostname:
                LOG.debug("_find_dns_row: found matching row %s for hostname=%s", row_uuid(row), hostname)
                return row
        LOG.debug("_find_dns_row: no matching row found for hostname=%s", hostname)
        return None


class MetadataService(BaseService):
    service_name = "metadata"

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        self.ensure_metadata_path()
        count = 0
        for vm in desired.get("vms", []) or []:
            if vm.get("vm_data"):
                self.save_vm_data({"ip": vm.get("ip"), "vm_data": vm.get("vm_data")})
                count += 1
        return {"metadata_vms": count}

    def ensure_metadata_path(self) -> Dict[str, Any]:
        mode = self.ctx.config.metadata_mode
        if mode == "disabled":
            return {"mode": mode}
        if mode == "ovn-metadata-agent":
            return self._ensure_localport()
        return self._ensure_static_route()

    def _ensure_static_route(self) -> Dict[str, Any]:
        extension_ip = self.ctx.arg("extension_ip")
        if not extension_ip:
            return {"mode": "static-route", "configured": False}
        # Shared (bridged) networks have no logical router; the gateway lives on
        # the upstream physical router and OVN cannot inject routes there.
        router = self.names.router()
        if self.ovn.by_name("Logical_Router", router) is None:
            LOG.debug(
                "_ensure_static_route: no logical router for network %s "
                "(shared/bridged network) — metadata static route skipped",
                self.ctx.network_id,
            )
            return {"mode": "static-route", "configured": False, "reason": "no-router"}
        with self.ovn.txn() as txn:
            txn.add(self.ovn.nb.lr_route_add(router, f"{METADATA_IP}/32", extension_ip, may_exist=True))
        return {"mode": "static-route", "next_hop": extension_ip}

    def _ensure_localport(self) -> Dict[str, Any]:
        lsp = self.names.metadata_lsp()
        options = {}
        selected = self.ctx.network_details.get("selected_chassis")
        if selected:
            options["requested-chassis"] = str(selected)
        with self.ovn.txn() as txn:
            txn.add(
                self.ovn.nb.lsp_add(
                    self.names.vm_switch(),
                    lsp,
                    may_exist=True,
                    type="localport",
                    addresses=[f"{stable_mac(lsp)} {METADATA_IP}"],
                    options=options,
                    external_ids=ext_ids(
                        service="UserData",
                        network_id=self.ctx.network_id,
                        vpc_id=self.ctx.vpc_id,
                        kind="metadata-localport",
                    ),
                )
            )
        return {"mode": "ovn-metadata-agent", "lsp": lsp}

    def save_vm_data(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        ip = str(first_present(payload, "ip", default=self.ctx.arg("ip")))
        data = payload.get("vm_data")
        if data is None:
            data = maybe_json(self.ctx.arg("vm_data"), [])
        if not data and self.ctx.arg("vm_data_file"):
            with open(str(self.ctx.arg("vm_data_file")), "r", encoding="utf-8") as fh:
                data = json.loads(fh.read().strip())
        if not data:
            data = []
        root = self._vm_root(ip)
        for entry in data:
            self._write_metadata_file(root, str(entry["dir"]), str(entry["file"]), entry.get("content", ""))
        return {"ip": ip, "entries": len(data)}

    def save_password(self) -> Dict[str, Any]:
        ip = str(self.ctx.arg("ip"))
        self._write_metadata_file(self._vm_root(ip), "password", "vm_password", str(self.ctx.arg("password")))
        return {"ip": ip}

    def save_userdata(self) -> Dict[str, Any]:
        ip = str(self.ctx.arg("ip"))
        self._write_metadata_file(self._vm_root(ip), "userdata", "user-data", str(self.ctx.arg("userdata")))
        return {"ip": ip}

    def save_sshkey(self) -> Dict[str, Any]:
        ip = str(self.ctx.arg("ip"))
        self._write_metadata_file(self._vm_root(ip), "meta-data", "public-keys/0/openssh-key", str(self.ctx.arg("sshkey")))
        return {"ip": ip}

    def save_hypervisor_hostname(self) -> Dict[str, Any]:
        ip = str(self.ctx.arg("ip"))
        self._write_metadata_file(self._vm_root(ip), "meta-data", "availability-zone", str(self.ctx.arg("hypervisor_hostname")))
        return {"ip": ip}

    def remove_vm(self, entry: Mapping[str, Any]) -> Dict[str, Any]:
        ip = str(first_present(entry, "ip", default=self.ctx.arg("ip") or ""))
        if not ip:
            return {"removed": False}
        vm_dir = self._vm_root(ip).parent
        if vm_dir.exists():
            import shutil
            shutil.rmtree(str(vm_dir), ignore_errors=True)
            LOG.debug("remove_vm: removed metadata dir %s", vm_dir)
            return {"removed": True, "ip": ip}
        return {"removed": False, "ip": ip}

    def _vm_root(self, ip: str) -> pathlib.Path:
        safe_ip = sanitize_symbol(ip)
        return pathlib.Path(self.ctx.config.metadata_store) / f"net-{self.ctx.network_id}" / safe_ip / "latest"

    def _write_metadata_file(self, root: pathlib.Path, directory: str, filename: str, content: str) -> None:
        relative = pathlib.PurePosixPath(directory) / pathlib.PurePosixPath(filename)
        if ".." in relative.parts or relative.is_absolute():
            raise ExtensionError(f"unsafe metadata path: {relative}")
        target = root / pathlib.Path(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class MetadataHttpHandler(http.server.BaseHTTPRequestHandler):
    server: "MetadataHttpServer"

    PATH_ALIASES = {
        "meta-data": "metadata",
        "user-data": "userdata/user-data",
        "password": "password/vm_password",
    }

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("metadata-http %s - %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        self._serve()

    def do_HEAD(self) -> None:
        self._serve(head_only=True)

    def _serve(self, head_only: bool = False) -> None:
        try:
            target = self.server.resolve_request_path(self)
            if target is None:
                self.send_error(404)
                return
            if target.is_dir():
                body = self._directory_listing(target)
                self._send_bytes(body, "text/plain; charset=utf-8", head_only)
                return
            if not target.is_file():
                self.send_error(404)
                return
            self._send_bytes(target.read_bytes(), "text/plain; charset=utf-8", head_only)
        except ExtensionError as exc:
            LOG.warning("metadata-http rejected request from %s: %s", self.client_address[0], exc)
            self.send_error(404)
        except Exception:
            LOG.exception("metadata-http failed request from %s path=%s", self.client_address[0], self.path)
            self.send_error(500)

    def _send_bytes(self, body: bytes, content_type: str, head_only: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    @staticmethod
    def _directory_listing(path: pathlib.Path) -> bytes:
        names = []
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            names.append(child.name + ("/" if child.is_dir() else ""))
        return ("\n".join(names) + ("\n" if names else "")).encode("utf-8")


class MetadataHttpServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: Tuple[str, int], ctx: CommandContext):
        super().__init__(server_address, MetadataHttpHandler)
        self.ctx = ctx
        self.store = pathlib.Path(ctx.config.metadata_store)
        self.network_id = ctx.network_id
        self.client_ip_header = str(ctx.arg("client_ip_header") or "").strip()

    def resolve_request_path(self, handler: MetadataHttpHandler) -> Optional[pathlib.Path]:
        client_ip = self._client_ip(handler)
        vm_root = self._vm_root(client_ip)
        request_path = urllib.parse.urlsplit(handler.path).path
        relative = self._metadata_relative_path(request_path)
        if relative is None:
            return None
        target = vm_root / relative
        try:
            target.resolve().relative_to(vm_root.resolve())
        except ValueError:
            raise ExtensionError(f"unsafe metadata path: {request_path}")
        return target

    def _client_ip(self, handler: MetadataHttpHandler) -> str:
        if self.client_ip_header:
            header = handler.headers.get(self.client_ip_header, "")
            first = header.split(",", 1)[0].strip()
            if first:
                return first
        return handler.client_address[0]

    def _vm_root(self, client_ip: str) -> pathlib.Path:
        safe_ip = sanitize_symbol(client_ip)
        if self.network_id:
            root = self.store / f"net-{self.network_id}" / safe_ip / "latest"
            if root.exists():
                return root
            raise ExtensionError(f"metadata for network={self.network_id} ip={client_ip} was not found")

        matches = sorted(self.store.glob(f"net-*/{safe_ip}/latest"))
        matches = [path for path in matches if path.is_dir()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ExtensionError(f"metadata for ip={client_ip} was not found")
        raise ExtensionError(f"metadata for ip={client_ip} is ambiguous; run one server per network with --network-id")

    def _metadata_relative_path(self, request_path: str) -> Optional[pathlib.Path]:
        clean = request_path.strip("/")
        if not clean:
            clean = "latest"
        parts = pathlib.PurePosixPath(clean).parts
        if parts and parts[0] == "openstack":
            # CloudStack metadata is EC2-style. Return a clean 404 for
            # OpenStack probes so cloud-init falls through quickly.
            return None
        if parts and parts[0] == "latest":
            parts = parts[1:]
        if not parts:
            return pathlib.Path(".")

        head = parts[0]
        mapped = MetadataHttpHandler.PATH_ALIASES.get(head, head)
        mapped_parts = pathlib.PurePosixPath(mapped).parts + tuple(parts[1:])
        relative = pathlib.PurePosixPath(*mapped_parts)
        if ".." in relative.parts or relative.is_absolute():
            raise ExtensionError(f"unsafe metadata path: {request_path}")
        return pathlib.Path(*relative.parts)


def serve_metadata_http(ctx: CommandContext) -> Dict[str, Any]:
    host = str(ctx.arg("listen", ctx.arg("host", "127.0.0.1")))
    port = int(ctx.arg("port", 8080))
    metadata_store = ctx.arg("metadata_store")
    if metadata_store:
        ctx.config.metadata_store = str(metadata_store)
    server = MetadataHttpServer((host, port), ctx)
    LOG.info(
        "serving metadata HTTP on %s:%s store=%s network_id=%s",
        host, port, ctx.config.metadata_store, ctx.network_id or "*",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"metadata_http": "stopped", "listen": host, "port": port}


class LoadBalancerService(BaseService):
    service_name = "load-balancer"

    def _rule_scheme(self, rule: Mapping[str, Any]) -> str:
        scheme = str(first_present(rule, "scheme", "lbScheme", "lb_scheme", default="")).strip().lower()
        if scheme in {"internal", "public"}:
            return scheme
        # Extension payloads from different CloudStack versions are not
        # perfectly consistent.  Internal LB rules usually carry sourceIp
        # without publicIp, while public rules normally carry publicIp.
        if first_present(rule, "publicIp", "public_ip", "publicIP") in (None, "") and first_present(
            rule, "sourceIp", "source_ip", "sourceIP", "internalIp", "internal_ip"
        ) not in (None, ""):
            return "internal"
        return "public"

    def _rule_vip_ip(self, rule: Mapping[str, Any], scheme: str) -> Optional[str]:
        if scheme == "internal":
            value = first_present(
                rule,
                "sourceIp",
                "source_ip",
                "sourceIP",
                "internalIp",
                "internal_ip",
                "privateIp",
                "private_ip",
                "publicIp",
                "public_ip",
                "publicIP",
            )
        else:
            value = first_present(rule, "publicIp", "public_ip", "publicIP", "sourceIp", "source_ip", "sourceIP")
        return str(value) if value not in (None, "") else None

    def _rule_vip_port(self, rule: Mapping[str, Any]) -> Optional[int]:
        value = first_present(
            rule,
            "publicPort",
            "public_port",
            "sourcePort",
            "source_port",
            "sourcePortStart",
            "source_port_start",
            "port",
        )
        if value in (None, ""):
            return None
        return int(value)

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        if isinstance(desired, list):
            rules = desired
        else:
            rules = desired.get("rules", desired.get("load_balancers", [])) or []
        router = self.names.router()
        switch = self.names.switch()
        wanted: Dict[str, Dict[str, Any]] = {}
        revoked_ids: Set[str] = set()
        rejected: List[Dict[str, Any]] = []
        for rule in rules:
            rule_id = str(first_present(rule, "id", "name", default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12]))
            if parse_bool(rule.get("revoke"), False):
                revoked_ids.add(rule_id)
                continue
            scheme = self._rule_scheme(rule)
            vip_ip = self._rule_vip_ip(rule, scheme)
            vip_port = self._rule_vip_port(rule)
            if not vip_ip or vip_port is None:
                rejected.append({
                    "id": first_present(rule, "id", "name"),
                    "scheme": scheme,
                    "reason": "missing LB VIP address or port",
                })
                continue
            backends = [
                f"{b['ip']}:{int(first_present(b, 'port', default=first_present(rule, 'privatePort', 'private_port')))}"
                for b in rule.get("backends", []) or []
                if not parse_bool(b.get("revoked"), False)
            ]
            if not backends:
                continue
            vip = f"{vip_ip}:{vip_port}"
            wanted[rule_id] = {
                "name": self.names.lb(rule_id),
                "protocol": str(first_present(rule, "protocol", default="tcp")).lower(),
                "vips": {vip: ",".join(backends)},
                "selection_fields": self._selection_fields(str(first_present(rule, "algorithm", default="roundrobin"))),
                "external_ids": ext_ids(
                    service="Lb",
                    network_id=self.ctx.network_id,
                    vpc_id=self.ctx.vpc_id,
                    rule_id=rule_id,
                    algorithm=first_present(rule, "algorithm", default="roundrobin"),
                    kind=first_present(rule, "source", default=f"{scheme}-load-balancer"),
                    scheme=scheme.title(),
                    vip=vip_ip,
                ),
            }

        current = {
            row_external_ids(row).get(f"{EXT_ID_PREFIX}rule-id", row_name(row)): row
            for row in self.ovn.owned_rows("Load_Balancer", network_id=self.ctx.network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}service") == "Lb"
        }
        # Shared (bridged) networks have no logical router; attach the LB only
        # to the Logical Switch so internal/private VIPs still function.
        router_exists = self.ovn.by_name("Logical_Router", router) is not None
        created = updated = deleted = 0
        with self.ovn.txn() as txn:
            for rule_id, columns in wanted.items():
                row = current.get(rule_id) or self.ovn.by_name("Load_Balancer", columns["name"])
                if row is None:
                    create = txn.add(self.ovn.nb.db_create_row("Load_Balancer", **columns))
                    if router_exists:
                        txn.add(self.ovn.nb.lr_lb_add(router, create, may_exist=True))
                    txn.add(self.ovn.nb.ls_lb_add(switch, create, may_exist=True))
                    created += 1
                else:
                    txn.add(self.ovn.nb.db_clear("Load_Balancer", row_uuid(row), "vips"))
                    txn.add(self.ovn.nb.db_set("Load_Balancer", row_uuid(row), *[(k, v) for k, v in columns.items()], if_exists=True))
                    if router_exists:
                        txn.add(self.ovn.nb.lr_lb_add(router, row_uuid(row), may_exist=True))
                    txn.add(self.ovn.nb.ls_lb_add(switch, row_uuid(row), may_exist=True))
                    updated += 1
            for rule_id, row in current.items():
                if rule_id in revoked_ids:
                    if router_exists:
                        txn.add(self.ovn.nb.lr_lb_del(router, row_uuid(row), if_exists=True))
                    txn.add(self.ovn.nb.ls_lb_del(switch, row_uuid(row), if_exists=True))
                    txn.add(self.ovn.nb.db_destroy("Load_Balancer", row_uuid(row)))
                    deleted += 1
        result: Dict[str, Any] = {"created": created, "updated": updated, "deleted": deleted}
        if rejected:
            result["rejected"] = rejected
        return result

    def _selection_fields(self, algorithm: str) -> List[str]:
        alg = algorithm.lower()
        if alg in {"source", "source_ip", "source-ip"}:
            return ["ip_src"]
        if alg in {"leastconn", "least_conn", "least-connections"}:
            return ["ip_src", "tp_src"]
        return []

    # ------------------------------------------------------------------
    # PortForwarding-as-LoadBalancer helpers.

    def _pf_lb_columns(self, rule: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """Build Load_Balancer column dict for one PF rule, or None if no backends."""
        backends = [
            f"{b['ip']}:{int(first_present(b, 'port', default=first_present(rule, 'privatePort', 'private_port')))}"
            for b in rule.get("backends", []) or []
            if not parse_bool(b.get("revoked"), False)
        ]
        if not backends:
            return None
        rule_id = str(first_present(rule, "id", "name",
                                    default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12]))
        vip = f"{first_present(rule, 'publicIp', 'public_ip')}:{int(first_present(rule, 'publicPort', 'public_port'))}"
        return {
            "name": self.names.pf_lb(rule_id),
            "protocol": str(first_present(rule, "protocol", default="tcp")).lower(),
            "vips": {vip: ",".join(backends)},
            "selection_fields": self._selection_fields(str(first_present(rule, "algorithm", default="source"))),
            "external_ids": ext_ids(
                service="PortForwarding-LB",
                network_id=self.ctx.network_id,
                vpc_id=self.ctx.vpc_id,
                rule_id=rule_id,
                kind="port-forward",
            ),
        }

    def add_pf_lb_rule(self, rule: Mapping[str, Any]) -> Dict[str, Any]:
        """Create or update a single PF Load_Balancer row without touching others.

        Unlike sync_pf_rules() this method performs an upsert only — it never
        deletes existing PF-LB rows.  Use it from add_pf_from_args so that
        adding rule N does not remove rules 1 … N-1.
        """
        router = self.names.router()
        switch = self.names.switch()
        columns = self._pf_lb_columns(rule)
        if columns is None:
            return {"created": 0, "updated": 0}
        rule_id = columns["external_ids"].get(f"{EXT_ID_PREFIX}rule-id")
        existing = (
            next(
                (r for r in self.ovn.owned_rows("Load_Balancer", network_id=self.ctx.network_id)
                 if row_external_ids(r).get(f"{EXT_ID_PREFIX}rule-id") == rule_id
                 and row_external_ids(r).get(f"{EXT_ID_PREFIX}service") == "PortForwarding-LB"),
                None,
            ) or self.ovn.by_name("Load_Balancer", columns["name"])
        )
        router_exists = self.ovn.by_name("Logical_Router", router) is not None
        with self.ovn.txn() as txn:
            if existing is None:
                create = txn.add(self.ovn.nb.db_create_row("Load_Balancer", **columns))
                if router_exists:
                    txn.add(self.ovn.nb.lr_lb_add(router, create, may_exist=True))
                txn.add(self.ovn.nb.ls_lb_add(switch, create, may_exist=True))
                return {"created": 1, "updated": 0}
            txn.add(self.ovn.nb.db_clear("Load_Balancer", row_uuid(existing), "vips"))
            txn.add(self.ovn.nb.db_set("Load_Balancer", row_uuid(existing),
                                        *[(k, v) for k, v in columns.items()], if_exists=True))
            if router_exists:
                txn.add(self.ovn.nb.lr_lb_add(router, row_uuid(existing), may_exist=True))
            txn.add(self.ovn.nb.ls_lb_add(switch, row_uuid(existing), may_exist=True))
            return {"created": 0, "updated": 1}

    # ------------------------------------------------------------------
    # PortForwarding-as-LoadBalancer reconciliation.
    #
    # OVN ``Logical_Router.nat`` collides on (external_ip, protocol, port)
    # tuples, so two PF rules on the same public IP cannot coexist there.
    # ``Load_Balancer`` rows have no such limitation -- multiple rules on
    # the same VIP are first-class.  This method reconciles only the rows
    # we tag as PF-sourced (external_ids:cloudstack:service = "PortForwarding-LB"),
    # leaving user-created LB rules (service = "Lb") untouched.
    # ------------------------------------------------------------------
    def sync_pf_rules(self, rules: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        router = self.names.router()
        switch = self.names.switch()
        wanted: Dict[str, Dict[str, Any]] = {}
        for rule in rules:
            if parse_bool(rule.get("revoke"), False):
                continue
            backends = [
                f"{b['ip']}:{int(first_present(b, 'port', default=first_present(rule, 'privatePort', 'private_port')))}"
                for b in rule.get("backends", []) or []
                if not parse_bool(b.get("revoked"), False)
            ]
            if not backends:
                continue
            rule_id = str(first_present(rule, "id", "name", default=hashlib.sha1(compact_json(rule).encode()).hexdigest()[:12]))
            vip = f"{first_present(rule, 'publicIp', 'public_ip')}:{int(first_present(rule, 'publicPort', 'public_port'))}"
            wanted[rule_id] = {
                "name": self.names.pf_lb(rule_id),
                "protocol": str(first_present(rule, "protocol", default="tcp")).lower(),
                "vips": {vip: ",".join(backends)},
                "selection_fields": self._selection_fields(str(first_present(rule, "algorithm", default="source"))),
                "external_ids": ext_ids(
                    service="PortForwarding-LB",
                    network_id=self.ctx.network_id,
                    vpc_id=self.ctx.vpc_id,
                    rule_id=rule_id,
                    kind="port-forward",
                ),
            }
        current = {
            row_external_ids(row).get(f"{EXT_ID_PREFIX}rule-id", row_name(row)): row
            for row in self.ovn.owned_rows("Load_Balancer", network_id=self.ctx.network_id)
            if row_external_ids(row).get(f"{EXT_ID_PREFIX}service") == "PortForwarding-LB"
        }
        router_exists = self.ovn.by_name("Logical_Router", router) is not None
        created = updated = deleted = 0
        with self.ovn.txn() as txn:
            for rule_id, columns in wanted.items():
                row = current.get(rule_id) or self.ovn.by_name("Load_Balancer", columns["name"])
                if row is None:
                    create = txn.add(self.ovn.nb.db_create_row("Load_Balancer", **columns))
                    if router_exists:
                        txn.add(self.ovn.nb.lr_lb_add(router, create, may_exist=True))
                    txn.add(self.ovn.nb.ls_lb_add(switch, create, may_exist=True))
                    created += 1
                else:
                    txn.add(self.ovn.nb.db_clear("Load_Balancer", row_uuid(row), "vips"))
                    txn.add(self.ovn.nb.db_set("Load_Balancer", row_uuid(row), *[(k, v) for k, v in columns.items()], if_exists=True))
                    if router_exists:
                        txn.add(self.ovn.nb.lr_lb_add(router, row_uuid(row), may_exist=True))
                    txn.add(self.ovn.nb.ls_lb_add(switch, row_uuid(row), may_exist=True))
                    updated += 1
            for rule_id, row in current.items():
                if rule_id not in wanted:
                    if router_exists:
                        txn.add(self.ovn.nb.lr_lb_del(router, row_uuid(row), if_exists=True))
                    txn.add(self.ovn.nb.ls_lb_del(switch, row_uuid(row), if_exists=True))
                    txn.add(self.ovn.nb.db_destroy("Load_Balancer", row_uuid(row)))
                    deleted += 1
        return {"pf_lb_created": created, "pf_lb_updated": updated, "pf_lb_deleted": deleted}


class CompositeSyncService(BaseService):
    service_name = "sync"

    def sync(self, desired: Mapping[str, Any]) -> Dict[str, Any]:
        report: Dict[str, Any] = {}
        if desired.get("network") or {"id", "network_id", "cidr", "gateway"} & set(desired.keys()):
            report["connectivity"] = ConnectivityService(self.ctx, self.ovn).sync(desired)
        if desired.get("public"):
            public = desired["public"]
            router = self.names.router()
            with self.ovn.txn() as txn:
                report["public"] = ConnectivityService(self.ctx, self.ovn).ensure_public_attachment(
                    txn,
                    router,
                    first_present(public, "ip", "public_ip"),
                    first_present(public, "cidr", "public_cidr"),
                    first_present(public, "gateway", "public_gateway"),
                    first_present(public, "vlan", "public_vlan"),
                )
        if desired.get("nat"):
            report["nat"] = NatService(self.ctx, self.ovn).sync(desired["nat"])
        if desired.get("firewall"):
            report["firewall"] = FirewallService(self.ctx, self.ovn).sync(desired["firewall"])
        if desired.get("security_groups"):
            report["security_groups"] = SecurityGroupService(self.ctx, self.ovn).sync(desired)
        if desired.get("dhcp"):
            report["dhcp"] = DhcpService(self.ctx, self.ovn).sync(desired["dhcp"])
        if desired.get("dns"):
            report["dns"] = DnsService(self.ctx, self.ovn).sync(desired["dns"])
        if desired.get("metadata"):
            report["metadata"] = MetadataService(self.ctx, self.ovn).sync(desired["metadata"])
        if desired.get("load_balancers"):
            report["load_balancers"] = LoadBalancerService(self.ctx, self.ovn).sync(desired["load_balancers"])
        return report


def capabilities() -> Dict[str, Any]:
    services = [
        "SourceNat",
        "StaticNat",
        "PortForwarding",
        "Firewall",
        "Lb",
        "Dhcp",
        "Dns",
        "UserData",
        "Gateway",
        "NetworkACL",
        "CustomAction",
    ]
    service_capabilities = {
        "SourceNat": {"SupportedSourceNatTypes": "peraccount", "RedundantRouter": "false"},
        "StaticNat": {"Supported": "true"},
        "PortForwarding": {"SupportedProtocols": "tcp,udp"},
        "Firewall": {
            "TrafficStatistics": "per public ip",
            "SupportedProtocols": "tcp,udp,icmp,all",
            "SupportedEgressProtocols": "tcp,udp,icmp,all",
            "SupportedTrafficDirection": "ingress,egress",
            "MultipleIps": "true",
        },
        "Lb": {
            "SupportedLBAlgorithms": "roundrobin,source,leastconn",
            "SupportedLBIsolation": "dedicated",
            "SupportedProtocols": "tcp,udp,sctp",
            "LbSchemes": "Public,Internal",
            "SslTermination": "false",
            "VmAutoScaling": "false",
        },
        "Dhcp": {"DhcpAccrossMultipleSubnets": "true"},
        "Dns": {"AllowDnsSuffixModification": "true", "ExternalDns": "true"},
        "Gateway": {"RedundantRouter": "false"},
        "NetworkACL": {"SupportedProtocols": "tcp,udp,icmp,all"},
        "UserData": {"Supported": "true"},
    }
    return {
        "network.services": ",".join(services),
        "network.service.capabilities": service_capabilities
    }


class Dispatcher:
    def __init__(self, ctx: CommandContext):
        self.ctx = ctx
        self.ovn = OvnClient(ctx.config)

    def _run_with_shutdown_guard(self, fn: Callable[[], Any]) -> Any:
        """Call *fn*; if it raises during a teardown operation, treat the failure as success —
        OVN may already be torn down.  Teardown is detected by network_state being 'shutdown',
        'destroy', or 'allocated', or vpc_state being 'inactive'."""
        try:
            return fn()
        except Exception as exc:
            if self.ctx.network_state in {"shutdown", "destroy", "allocated"} or self.ctx.vpc_state == "inactive":
                LOG.warning(
                    "%s: OVN error (network_state=%s, vpc_state=%s) — treating as success: %s",
                    self.ctx.command, self.ctx.network_state, self.ctx.vpc_state, exc,
                )
                return {"skipped": "ovn-unreachable", "network_state": self.ctx.network_state}
            raise

    def run(self) -> Any:
        return self._run_with_shutdown_guard(self._dispatch)

    def _dispatch(self) -> Any:
        command = self.ctx.command
        if command == "ensure-network-device":
            return ConnectivityService(self.ctx, self.ovn).ensure_network_device()
        if command == "implement-vpc":
            return ConnectivityService(self.ctx, self.ovn).implement_vpc()
        if command == "shutdown-vpc":
            if self.ctx.network_state == "allocated":
                return {"skipped": "never-implemented", "network_state": "allocated"}
            return ConnectivityService(self.ctx, self.ovn).shutdown_vpc()
        if command == "update-vpc-source-nat-ip":
            return NatService(self.ctx, self.ovn).add_vpc_source_nat_from_args()
        if command in {"implement", "implement-network"}:
            return ConnectivityService(self.ctx, self.ovn).sync(self._network_desired_from_args())
        if command in {"shutdown", "shutdown-network", "destroy", "destroy-network"}:
            if self.ctx.network_state == "allocated":
                LOG.info("%s: network_state=allocated — network was never implemented; no OVN resources to clean up", command)
                return {"skipped": "never-implemented", "network_state": "allocated"}
            hard = command in {"destroy", "destroy-network"}
            return ConnectivityService(self.ctx, self.ovn).delete_network(
                str(self.ctx.network_id), self.ctx.vpc_id, hard=hard
            )
        if command == "assign-ip":
            if self.ctx.is_shared:
                # Shared networks have no virtual router and no public IP/NAT.
                return {"skipped": "shared-network-no-public-ip"}
            if parse_bool(self.ctx.arg("source_nat"), False):
                return NatService(self.ctx, self.ovn).add_source_nat_from_args()
            # Non-SourceNat public IPs (firewall-on-IP, PortForward, StaticNat,
            # LB) do NOT get their own attachment on the public Logical_Router_Port.
            # The plugin behaves the same way: ``applyIps`` only touches the LRP
            # for the SourceNat IP, and any extra public IP in the same /20
            # subnet is reachable through that same LRP — its per-IP NAT/DNAT
            # rows are added later by the dedicated callbacks (apply-fw-rules,
            # apply-pf-rules, add-static-nat, apply-lb-rules).
            #
            # Calling ``ensure_public_attachment`` here for a non-SourceNat IP
            # would invoke ``lrp_add`` with a different ``networks`` value than
            # the one already on the public LRP, and ovsdbapp's ``lrp_add``
            # raises ``Port <name> exists with different networks`` — which
            # surfaces in CloudStack as ``Failed to assign-ip`` and aborts
            # whatever rule (Firewall/PF/StaticNat/LB) triggered the assign.
            # Install a default-deny ACL for this non-SourceNat public IP so
            # it is unreachable until the operator creates firewall rules.
            # StaticNat / PF / LB IPs are only used for DNAT-inbound so there
            # is no VM-initiated-outbound return-traffic concern (unlike the
            # SourceNat IP which only gets an ICMP-ping drop).
            public_ip = self.ctx.arg("public_ip")
            public_vlan = self.ctx.arg("public_vlan")
            fw_result = FirewallService(self.ctx, self.ovn).apply_public_ip_firewall(
                public_ip, public_vlan
            )
            return {
                "public_ip": public_ip,
                "public_lrp": self.names.public_lrp(self.names.router(), public_vlan),
                "firewall": fw_result,
            }
        if command == "release-ip":
            if self.ctx.is_shared:
                return {"skipped": "shared-network-no-public-ip"}
            public_ip = self.ctx.arg("public_ip")
            result = NatService(self.ctx, self.ovn).delete_by_args("SourceNat")
            # Also revoke any PublicFirewall ACLs for this IP (covers both
            # SourceNat ICMP-drop and non-SourceNat default-deny rules).
            FirewallService(self.ctx, self.ovn).revoke_public_ip_firewall(public_ip)
            return result
        if command == "add-static-nat":
            if self.ctx.is_shared:
                return {"skipped": "no-nat-for-shared-network"}
            return NatService(self.ctx, self.ovn).add_static_nat_from_args()
        if command == "delete-static-nat":
            if self.ctx.is_shared:
                return {"skipped": "no-nat-for-shared-network"}
            return NatService(self.ctx, self.ovn).delete_by_args("StaticNat")
        if command == "add-port-forward":
            if self.ctx.is_shared:
                return {"skipped": "no-nat-for-shared-network"}
            return NatService(self.ctx, self.ovn).add_pf_from_args()
        if command == "delete-port-forward":
            if self.ctx.is_shared:
                return {"skipped": "no-nat-for-shared-network"}
            return NatService(self.ctx, self.ovn).delete_by_args("PortForwarding")
        if command in {"apply-fw-rules", "apply-network-acl"}:
            if self.ctx.is_shared:
                return {"skipped": "no-firewall-chains-for-shared-network"}
            # VPC tiers do not support the Firewall service (per-IP ingress/egress
            # firewall rules).  ACL rules are applied via apply-network-acl instead.
            if command == "apply-fw-rules" and self.ctx.vpc_id:
                return {"skipped": "vpc-does-not-support-firewall-rules"}
            # fw_rules / acl_rules are JSON objects/arrays in the payload.
            desired = decode_json_payload(self.ctx.arg("fw_rules") or self.ctx.arg("acl_rules"), {})
            return FirewallService(self.ctx, self.ovn).sync(desired)
        if command == "prepare-nic":
            # Create the OVN Logical Switch Port and bind DHCP options for the NIC.
            # Defensive: if the Logical_Switch does not exist yet (implement-network
            # was skipped or previously failed — e.g. due to a routing_mode bug),
            # run the connectivity sync now so the LS + localnet port are created
            # before attempting lsp_add.
            self._ensure_ls_exists()
            return DhcpService(self.ctx, self.ovn).add_entry(self.ctx.args)
        if command == "release-nic":
            result: Dict[str, Any] = {}
            # Always remove the VM's LSP and DHCP_Options row.  For isolated
            # networks this duplicates what remove-dhcp-entry does (harmless
            # double-delete); for shared networks remove-dhcp-entry is never
            # called by CloudStack (DHCP is not an extension-provided service
            # on shared networks), so this is the only place the LSP is freed.
            with contextlib.suppress(Exception):
                result["dhcp"] = DhcpService(self.ctx, self.ovn).remove_entry(self.ctx.args)
            with contextlib.suppress(Exception):
                result["metadata"] = MetadataService(self.ctx, self.ovn).remove_vm(self.ctx.args)
            return result
        if command == "config-dhcp-subnet":
            return DhcpService(self.ctx, self.ovn).configure_subnet(self.ctx.args)
        if command == "remove-dhcp-subnet":
            return DhcpService(self.ctx, self.ovn).remove_subnet()
        if command == "add-dhcp-entry":
            self._ensure_ls_exists()
            return DhcpService(self.ctx, self.ovn).add_entry(self.ctx.args)
        if command == "remove-dhcp-entry":
            return DhcpService(self.ctx, self.ovn).remove_entry(self.ctx.args)
        if command == "set-dhcp-options":
            return DhcpService(self.ctx, self.ovn).set_options()
        if command == "config-dns-subnet":
            # OVN DNS is managed per-VM via add-dns-entry (one DNS row per VM).
            # There is no subnet-level DNS object to configure; calling sync()
            # with empty records here would clear every existing DNS row.
            return {"configured": True}
        if command == "remove-dns-subnet":
            return DnsService(self.ctx, self.ovn).remove_subnet()
        if command == "add-dns-entry":
            return DnsService(self.ctx, self.ovn).add_entry(self.ctx.args)
        if command == "remove-dns-entry":
            return DnsService(self.ctx, self.ovn).remove_entry(self.ctx.args)
        if command == "save-vm-data":
            return MetadataService(self.ctx, self.ovn).save_vm_data(self.ctx.args)
        if command == "save-password":
            return MetadataService(self.ctx, self.ovn).save_password()
        if command == "save-userdata":
            return MetadataService(self.ctx, self.ovn).save_userdata()
        if command == "save-sshkey":
            return MetadataService(self.ctx, self.ovn).save_sshkey()
        if command == "save-hypervisor-hostname":
            return MetadataService(self.ctx, self.ovn).save_hypervisor_hostname()
        if command == "apply-lb-rules":
            return LoadBalancerService(self.ctx, self.ovn).sync(decode_json_payload(self.ctx.arg("lb_rules"), []))
        if command == "restore-network":
            return self._restore_network()
        if command == "sync":
            return CompositeSyncService(self.ctx, self.ovn).sync(decode_json_payload(self.ctx.arg("desired_state"), {}))
        if command == "custom-action":
            return self._custom_action()
        if command == "capabilities":
            return capabilities()
        raise ExtensionError(f"unknown command: {command}")

    @property
    def names(self) -> Names:
        return Names(self.ctx)

    def _ensure_ls_exists(self) -> None:
        """Create the guest Logical_Switch if it is missing.

        implement-network should always run before prepare-nic / add-dhcp-entry,
        but if it was skipped or previously failed (e.g. the routing_mode NameError
        that left shared-network LSes un-created), the Logical_Switch may be absent
        and lsp_add would raise RowNotFound.  Calling ConnectivityService.sync()
        here is a no-op when the LS already exists (ls_add uses may_exist=True).
        """
        switch = self.names.vm_switch()
        if self.ovn.by_name("Logical_Switch", switch) is None:
            LOG.warning(
                "ensure-ls: Logical_Switch %s not found for network %s; "
                "running implement-network now (was it skipped or did it fail?)",
                switch, self.ctx.network_id,
            )
            ConnectivityService(self.ctx, self.ovn).sync(self._network_desired_from_args())

    def _network_desired_from_args(self) -> Dict[str, Any]:
        # ctx.routing_mode already returns "bridged" for shared networks
        # (derived from guest_type); no override needed here.
        return {
            "network": {
                "id": self.ctx.network_id,
                "vpc_id": self.ctx.vpc_id,
                "zone_id": self.ctx.zone_id,
                "guest_type": self.ctx.guest_type,
                "vlan": self.ctx.arg("vlan"),
                "gateway": self.ctx.arg("gateway"),
                "cidr": self.ctx.arg("cidr"),
                "extension_ip": self.ctx.arg("extension_ip"),
                "routing_mode": self.ctx.routing_mode,
            }
        }

    def _restore_network(self) -> Dict[str, Any]:
        raw_data = self.ctx.arg("restore_data")
        rd_file = self.ctx.arg("restore_data_file")
        if not raw_data and rd_file:
            with open(str(rd_file), "r", encoding="utf-8") as fh:
                restore = json.load(fh)
        else:
            restore = decode_json_payload(raw_data, {})
        report: Dict[str, Any] = {}
        if parse_bool(restore.get("dhcp_enabled"), False):
            dhcp = DhcpService(self.ctx, self.ovn)
            dhcp.configure_subnet(self.ctx.args)
            for vm in restore.get("vms", []) or []:
                lease = dict(self.ctx.args)
                lease.update(vm)
                dhcp.add_entry(lease)
            report["dhcp"] = len(restore.get("vms", []) or [])
        if parse_bool(restore.get("dns_enabled"), False):
            records = [{"hostname": vm.get("hostname"), "ip": vm.get("ip")} for vm in restore.get("vms", []) or []]
            report["dns"] = DnsService(self.ctx, self.ovn).sync({"records": records, "domain": self.ctx.arg("domain")})
        if parse_bool(restore.get("userdata_enabled"), False):
            metadata = MetadataService(self.ctx, self.ovn)
            metadata.ensure_metadata_path()
            for vm in restore.get("vms", []) or []:
                if vm.get("vm_data"):
                    metadata.save_vm_data({"ip": vm.get("ip"), "vm_data": vm.get("vm_data")})
            report["metadata"] = len(restore.get("vms", []) or [])
        return report

    def _custom_action(self) -> Any:
        action = str(self.ctx.arg("action") or "")
        params = decode_json_payload(self.ctx.arg("action_params"), {})
        if action == "capabilities":
            data: Any = capabilities()
            printmessage = True
        elif action == "sync":
            data = CompositeSyncService(self.ctx, self.ovn).sync(params)
            printmessage = False
        elif action == "diagnostics":
            data = self._diagnostics(params)
            printmessage = True
        else:
            raise ExtensionError(f"unsupported custom action: {action}")
        return {"status": "success", "message": data, "printmessage": printmessage}

    def _diagnostics(self, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Return OVN state for the given network or VPC.

        Collects logical switches (with ports, ACLs, DNS), logical routers
        (with ports, NAT, static routes, policies), DHCP options, ACLs,
        port groups, address sets, load balancers, and southbound port
        bindings / chassis info.
        """
        p = params or {}
        network_id = str(first_present(p, "network_id", default=self.ctx.network_id) or "") or None
        vpc_id = str(first_present(p, "vpc_id", default=self.ctx.vpc_id) or "") or None

        def row_dict(row: Any, table: str) -> Dict[str, Any]:
            d: Dict[str, Any] = {"uuid": row_uuid(row)}
            try:
                cols = list(self.ovn.nb.tables[table].columns.keys())
            except Exception:
                cols = []
            for col in cols:
                try:
                    d[col] = _diag_serialize(getattr(row, col))
                except Exception:
                    pass
            return d

        # Strict ownership+scope filter.  Unlike same_network()/same_vpc(),
        # this does NOT short-circuit to True when an id is None — so a
        # vpc-only query won't accidentally match every owned row in the cluster.
        def matches(row: Any) -> bool:
            if not network_id and not vpc_id:
                return True
            ext = row_external_ids(row)
            if network_id and ext.get(f"{EXT_ID_PREFIX}network-id") == str(network_id):
                return True
            if vpc_id and ext.get(f"{EXT_ID_PREFIX}vpc-id") == str(vpc_id):
                return True
            return False

        def owned_match(row: Any) -> bool:
            return is_owned(row) and matches(row)

        result: Dict[str, Any] = {
            "network_id": network_id,
            "vpc_id": vpc_id,
            "nb_connection": self.ctx.config.nb_connection,
            "sb_connection": self.ctx.config.sb_connection,
            "chassis": sorted(self.ovn.chassis_names()),
            "capabilities": capabilities(),
        }

        if not (network_id or vpc_id):
            return result

        # --- Logical Switches ---
        logical_switches = []
        for ls in self.ovn.rows("Logical_Switch"):
            if not owned_match(ls):
                continue
            d = row_dict(ls, "Logical_Switch")
            # Filter each child collection to the queried network/vpc so that
            # shared public switches don't pull in hundreds of foreign ACLs/ports.
            d["ports"] = [row_dict(p, "Logical_Switch_Port") for p in getattr(ls, "ports", []) or [] if owned_match(p)]
            d["acls"] = [row_dict(a, "ACL") for a in getattr(ls, "acls", []) or [] if owned_match(a)]
            d["dns_records"] = [row_dict(dns, "DNS") for dns in getattr(ls, "dns_records", []) or [] if owned_match(dns)]
            d["load_balancer"] = [{"uuid": row_uuid(lb), "name": row_name(lb)} for lb in getattr(ls, "load_balancer", []) or [] if owned_match(lb)]
            logical_switches.append(d)

        # --- Logical Routers ---
        logical_routers = []
        for lr in self.ovn.rows("Logical_Router"):
            if not owned_match(lr):
                continue
            d = row_dict(lr, "Logical_Router")
            ports = []
            for lrp in getattr(lr, "ports", []) or []:
                if not owned_match(lrp):
                    continue
                pd = row_dict(lrp, "Logical_Router_Port")
                pd["gateway_chassis"] = [row_dict(gc, "Gateway_Chassis") for gc in getattr(lrp, "gateway_chassis", []) or []]
                ports.append(pd)
            d["ports"] = ports
            d["nat"] = [row_dict(nat, "NAT") for nat in getattr(lr, "nat", []) or [] if owned_match(nat)]
            d["static_routes"] = [
                row_dict(rt, "Logical_Router_Static_Route")
                for rt in getattr(lr, "static_routes", []) or []
            ]
            d["policies"] = [
                row_dict(pol, "Logical_Router_Policy")
                for pol in getattr(lr, "policies", []) or []
                if owned_match(pol)
            ]
            d["load_balancer"] = [{"uuid": row_uuid(lb), "name": row_name(lb)} for lb in getattr(lr, "load_balancer", []) or [] if owned_match(lb)]
            logical_routers.append(d)

        # --- DHCP Options ---
        seen_dhcp: Set[str] = set()
        dhcp_options = []
        for dhcp in (self.ovn.owned_rows("DHCP_Options", network_id=network_id) if network_id else []):
            uid = row_uuid(dhcp)
            if uid not in seen_dhcp:
                dhcp_options.append(row_dict(dhcp, "DHCP_Options"))
                seen_dhcp.add(uid)
        if vpc_id:
            for dhcp in self.ovn.owned_rows("DHCP_Options", vpc_id=vpc_id):
                uid = row_uuid(dhcp)
                if uid not in seen_dhcp:
                    dhcp_options.append(row_dict(dhcp, "DHCP_Options"))
                    seen_dhcp.add(uid)

        # --- ACLs (flat list; includes public-LS firewall rules) ---
        seen_acls: Set[str] = set()
        acls: List[Dict[str, Any]] = []
        for acl_row in (self.ovn.owned_rows("ACL", network_id=network_id) if network_id else []):
            uid = row_uuid(acl_row)
            if uid not in seen_acls:
                acls.append(row_dict(acl_row, "ACL"))
                seen_acls.add(uid)
        if vpc_id:
            for acl_row in self.ovn.owned_rows("ACL", vpc_id=vpc_id):
                uid = row_uuid(acl_row)
                if uid not in seen_acls:
                    acls.append(row_dict(acl_row, "ACL"))
                    seen_acls.add(uid)

        # --- Port Groups (with their ACLs) ---
        port_groups = []
        if self.ovn.table_exists("Port_Group"):
            for pg in self.ovn.rows("Port_Group"):
                if not owned_match(pg):
                    continue
                d = row_dict(pg, "Port_Group")
                d["acls"] = [row_dict(a, "ACL") for a in getattr(pg, "acls", []) or [] if owned_match(a)]
                port_groups.append(d)

        # --- Address Sets ---
        address_sets = []
        if self.ovn.table_exists("Address_Set"):
            for as_row in self.ovn.rows("Address_Set"):
                if owned_match(as_row):
                    address_sets.append(row_dict(as_row, "Address_Set"))

        # --- Load Balancers ---
        load_balancers = []
        for lb in self.ovn.rows("Load_Balancer"):
            if owned_match(lb):
                load_balancers.append(row_dict(lb, "Load_Balancer"))

        result.update({
            "logical_switches": logical_switches,
            "logical_routers": logical_routers,
            "dhcp_options": dhcp_options,
            "acls": acls,
            "port_groups": port_groups,
            "address_sets": address_sets,
            "load_balancers": load_balancers,
        })

        # --- Southbound: chassis detail + port bindings for our ports ---
        if self.ovn.sb is not None:
            sb: Dict[str, Any] = {}
            try:
                chassis_rows = self.ovn.sb.db_list_rows("Chassis").execute(check_error=True)
                sb["chassis"] = [
                    {
                        "uuid": row_uuid(ch),
                        "name": row_name(ch),
                        "hostname": _diag_serialize(getattr(ch, "hostname", "")),
                        "encaps": [
                            {"type": getattr(enc, "type", ""), "ip": getattr(enc, "ip", "")}
                            for enc in (getattr(ch, "encaps", []) or [])
                        ],
                        "external_ids": _diag_serialize(getattr(ch, "external_ids", {})),
                    }
                    for ch in chassis_rows
                ]
            except Exception as exc:
                sb["chassis_error"] = str(exc)

            try:
                our_lsp_names: Set[str] = {
                    p.get("name", "")
                    for sw in logical_switches
                    for p in sw.get("ports", [])
                    if p.get("name")
                }
                if our_lsp_names:
                    bindings = []
                    for pb in self.ovn.sb.db_list_rows("Port_Binding").execute(check_error=True):
                        lp = _diag_serialize(getattr(pb, "logical_port", None)) or ""
                        if lp not in our_lsp_names:
                            continue
                        chassis_row = getattr(pb, "chassis", None)
                        chassis_name = row_name(chassis_row) if chassis_row else None
                        bindings.append({
                            "logical_port": lp,
                            "type": _diag_serialize(getattr(pb, "type", "")),
                            "mac": _diag_serialize(getattr(pb, "mac", [])),
                            "chassis": chassis_name,
                            "up": _diag_serialize(getattr(pb, "up", None)),
                            "external_ids": _diag_serialize(getattr(pb, "external_ids", {})),
                        })
                    if bindings:
                        sb["port_bindings"] = bindings
            except Exception as exc:
                sb["port_bindings_error"] = str(exc)

            if sb:
                result["southbound"] = sb

        return result


def build_context(argv: Sequence[str]) -> CommandContext:
    if len(argv) < 2:
        raise ExtensionError("missing command")
    command = argv[1]

    if command == "capabilities" and len(argv) == 2:
        config = ExtensionConfig.from_details({})
        return CommandContext(
            command=command,
            args={},
            physical_details={},
            network_details={},
            config=config,
        )

    # Supported invocation protocol: <command> <payload-file> [<timeout-seconds>]
    if len(argv) < 3 or not argv[2] or argv[2].startswith("--"):
        raise ExtensionError("payload-file argument is required; legacy CLI argument mode is not supported")

    payload_path = argv[2]
    try:
        with open(payload_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtensionError(f"cannot read payload file {payload_path!r}: {exc}") from exc

    physical: Dict[str, Any] = data.get("physical-network-extension-details", {}) or {}
    network: Dict[str, Any] = data.get("network-extension-details", {}) or {}
    if command == "custom-action":
        # custom-action uses a flat top-level structure (no nested "payload").
        # physical-network-extension-details and network-extension-details are
        # extracted above; everything else becomes the args mapping.
        args: Dict[str, Any] = {
            k.replace("-", "_"): v
            for k, v in data.items()
            if k not in ("physical-network-extension-details", "network-extension-details")
        }
    else:
        payload = data.get("payload", {}) or {}
        args = {k.replace("-", "_"): v for k, v in payload.items()}

    # For ensure-network-device: merge previously stored extension.details
    # (passed as current_details) into network_details so ConnectivityService
    # can access them.
    current = decode_json_payload(args.get("current_details"), None)
    if isinstance(current, dict):
        network.update(current)

    config = ExtensionConfig.from_details(physical)
    return CommandContext(command=command, args=args, physical_details=physical, network_details=network, config=config)


def main(argv: Sequence[str]) -> int:
    try:
        ctx = build_context(argv)
        if ctx.command == "serve-metadata":
            serve_metadata_http(ctx)
            return 0
        result = Dispatcher(ctx).run()
        if ctx.command in {"ensure-network-device", "implement", "implement-network"}:
            print(compact_json(result))
        elif ctx.command in {"custom-action", "sync", "capabilities"}:
            print(compact_json(result))
        else:
            LOG.debug("command result: %s", compact_json(result))
        return 0
    except ExtensionError as exc:
        LOG.error("%s", exc)
        return 1
    except Exception:
        LOG.exception("unhandled failure")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
