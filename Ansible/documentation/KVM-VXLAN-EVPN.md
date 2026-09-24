# KVM: VXLAN / BGP-EVPN for guest and public traffic

Trillian can build nested CloudStack environments whose KVM **guest** traffic, and optionally
**public** traffic, uses VXLAN isolation with a BGP-EVPN control plane (FRR) instead of VLANs.
Public traffic reaches the lab's public VLAN through a small per-environment gateway VM that
runs FRR as a Containerlab node and bridges the public VNI onto the public VLAN.

Everything is controlled by two flags, both `no` by default. With the flags unset or `no`, all
templates render exactly as before.

| `kvm_vxlan_evpn` | `evpn_public_vxlan` | Guest traffic | Public traffic | Gateway VM |
|---|---|---|---|---|
| `yes` | `yes` | VXLAN / EVPN | VXLAN -> gateway -> public VLAN | yes |
| `yes` | `no` | VXLAN / EVPN | VLAN | no |
| `no` | (ignored) | VLAN | VLAN | no |

A public-only mode (guest on VLAN, public on VXLAN) is not implemented.

## Requirements

* KVM build (`hvtype=k`) with a supported KVM host OS (see below), advanced zone without
  security groups, `kvm_network_mode=bridge`, nested KVM hosts (not physical/external),
  not an additional pod, CloudStack 4.19 or later
* the parent network carrying the hosts' management NIC must pass frames of
  `kvm_underlay_mtu` (default 9000, minimum 1550)
* FRR must be installable on the KVM hosts (distribution package, or a repository via
  `evpn_frr_repo_baseurl` / `evpn_frr_apt_repo`)
* public VXLAN: an EL9 template for the gateway, and Docker CE, Containerlab and the FRR
  image reachable from it (internet or mirrors)

Unsupported combinations stop the build at the start with an explanation
(`deployvms.yml`, and a per-host OS check in the KVM role).

## KVM host OS support

| KVM OS | Id | State | FRR source | Underlay MTU | Firewall |
|---|---|---|---|---|---|
| EL8, EL9, EL10 | `el8`, `el9`, `el10` | verified | AppStream, or `evpn_frr_repo_baseurl` | nmcli bridge setup | firewalld or iptables |
| Ubuntu 24.04 | `ubuntu24.04` | verified | Ubuntu `frr`, or `evpn_frr_apt_repo` | `netplan.j2` | ufw if active, else iptables + netfilter-persistent |
| Ubuntu 22.04 | `ubuntu22.04` | implemented, not verified | Ubuntu `frr`, or `evpn_frr_apt_repo` | `netplan.j2` | as Ubuntu 24.04 |
| openSUSE Leap 15.x | `opensuse-leap15` | verified (15.6) | Leap OSS `frr`, or `evpn_frr_repo_baseurl` | nmcli bridge setup | firewalld or iptables |
| EL7, Ubuntu 20.04, Debian, others | - | not supported | - | - | - |

Implemented but unverified OSes build only with `evpn_allow_untested_os=yes`. The lists are
`evpn_os_implemented` and `evpn_os_verified` in `roles/kvm/tasks/main.yml`; an OS moves to
"verified" in its own commit after a passing lab build.

The **gateway VM is always EL9**, whatever the KVM host OS.

## Using it

Jenkins (Reference_Trillian): the usual KVM settings (`PRIMARY_HYPERVISOR=k`, a supported
`KVM_OS`, `HYPERVISOR_COUNT` >= 2, `ZONE_TYPE=Advanced`, `KVM_NETWORK_BACKEND=bridge`) plus the
flags in `ANY_OTHER_OPTS`, space-separated, e.g.:

```
kvm_vxlan_evpn=yes evpn_public_vxlan=yes
```

Command line: pass the same values in the `generate-cloudconfig.yml` extra vars. `deployvms.yml`
needs nothing extra; the values are stored in `group_vars/<env_name>`.

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `kvm_vxlan_evpn` | `no` | guest traffic over VXLAN/EVPN (FRR on the KVM hosts) |
| `evpn_public_vxlan` | `no` | public traffic over VXLAN too; builds the gateway VM (requires `kvm_vxlan_evpn`) |
| `kvm_underlay_mtu` | `9000` | MTU of the underlay (KVM `eth0`/`cloudbr0`, gateway `eth0`); minimum 1550 |
| `kvm_vxlan_guest_label` | `kvm_mgmt_network_label` | KVM traffic label of the VXLAN physical networks (the underlay bridge) |
| `vxlan_vni_base` | `100000` | guest VNIs = base + leased guest VLAN range (e.g. 501-520 -> 100501-100520) |
| `evpn_public_vni` | derived | public VNI; default `vxlan_vni_base + env_pubvlan`; must not overlap the guest range |
| `evpn_bgp_asn` | `65000` | private ASN of the per-environment iBGP mesh |
| `evpn_frr_repo_baseurl` | empty | dnf/zypper repository for FRR (directory containing `repodata/`; literal path) |
| `evpn_frr_apt_repo` | empty | Ubuntu: complete apt sources line for an FRR repository |
| `evpn_force_vendored_script` | `no` | always use Trillian's copy of the EVPN script |
| `evpn_allow_untested_os` | `no` | allow an implemented but not yet verified KVM OS (currently Ubuntu 22.04) |
| `evpn_gw_template` | auto | gateway template (see "Gateway VM") |
| `evpn_gw_os` | empty | `linux_os` key of the EL9 OS to take the gateway template from (e.g. `r9`) |
| `evpn_gw_service_offering` | KVM offering | gateway service offering |
| `evpn_gw_trunk_if` | `eth1` | gateway NIC on the trunk network (public VLAN side) |
| `evpn_gw_frr_image` | `quay.io/frrouting/frr:10.2.1` | FRR container image |
| `evpn_gw_docker_repo_baseurl` | Docker CE CentOS 9 stable | Docker CE repository for the gateway |
| `evpn_gw_containerlab_repo_baseurl` | `https://yum.fury.io/netdevops/` | Containerlab repository for the gateway |

VNIs are derived from the environment's existing leases, so no Trillian database change is needed.

## What gets built

### Zone (`roles/cloudstack-config/templates/deployzone.sh.j2`)

| Physical network | Isolation | Traffic | KVM label | Range |
|---|---|---|---|---|
| Physical Network Mgmt | VLAN | Management | `cloudbr0` | - |
| Physical Network Public | VLAN, or VXLAN with `evpn_public_vxlan` | Public | `cloudbr1`, or `kvm_vxlan_guest_label` | public IP range with `vlan=<env_pubvlan>`, or `vlan=vxlan://<public VNI>` |
| Physical Network Guest VXLAN | VXLAN | Guest | `kvm_vxlan_guest_label` | derived guest VNI range |

Public IPs, gateway and netmask always come from the normal Trillian public lease. CloudStack
passes a range tag containing `://` unchanged into the NIC broadcast URI, so VR, SSVM and CPVM
public NICs get `vxlan://<public VNI>`. The Marvin configs describe the same layout.

### KVM hosts (`roles/kvm/tasks/kvm_vxlan_evpn.yml` + per-OS files)

1. `eth0` and `cloudbr0` get `kvm_underlay_mtu` (nmcli on EL/SUSE, `netplan.j2` on Ubuntu).
2. The management IP is added as a `/32` on `lo` (`trillian-evpn-vtep.service`, before `frr`
   and `cloudstack-agent`): the EVPN script takes the VTEP from `lo`, so the VTEP is the
   management IP and traffic still leaves via the bridge.
3. FRR (`kvm_vxlan_evpn_install_<family>.yml`) with `bgpd`: iBGP full mesh (`l2vpn evpn`,
   `advertise-all-vni`) to the other KVM hosts and the gateway, generated from the inventory.
4. tcp/179 and udp/4789 accepted **only from the environment's own peers**
   (`kvm_vxlan_evpn_firewall_<family>.yml`): firewalld rich rules, ufw rules, or the iptables
   chain `TRILLIAN-EVPN`. The kernel VXLAN device decapsulates packets for a known VNI from
   any source, so this stops leftovers of other environments or other VMs on the management
   network from injecting frames.
5. `/usr/share/modifyvxlan.sh` points to the EVPN script (found by the agent before the packaged
   multicast script): a symlink to the packaged `modifyvxlan-evpn.sh` on 4.21+, otherwise the
   vendored copy. The path is not owned by any package, so agent upgrades keep it.
6. The play waits until all BGP sessions are Established.

OS-specific parts: `kvm_vxlan_evpn_install_{el,ubuntu,suse}.yml`,
`kvm_vxlan_evpn_firewall_{el,ubuntu}.yml` (SUSE uses the EL firewall tasks).

### Gateway VM (`roles/evpn-gateway`, public VXLAN only)

`<env>-evpngw` is built in the same parent project (standard and custom-allocator builds), with
NICs on `management_network` and `guest_public_network`, and is configured **before** the KVM
hosts and the zone. It is destroyed with the environment.

Template: `evpn_gw_template`, else `linux_os[evpn_gw_os]`, else the KVM template if the KVM OS
is EL9, else the first `linux_os` entry with `os_type: el9`. The build stops if none is found,
and prints the chosen template.

| Piece | What it does |
|---|---|
| `trillian-evpn-gw-net.service` | VTEP `/32` on `lo`; `br-pub` = `vxlan<VNI>` (local VTEP, port 4789, nolearning) + `eth1.<env_pubvlan>`; bridged frames bypass iptables; peer-only firewall (iptables path) |
| Containerlab node `clab-evpngw-frr` | FRR in host network mode: iBGP `l2vpn evpn` to every KVM host, `advertise-all-vni` |
| `trillian-evpn-gw-clab.service` | (re)deploys the Containerlab topology at boot |

The gateway has no public IP and does no routing or NAT; it only bridges the public VNI and the
public VLAN. The environment lease is read from `localhost`, and the build checks that no gateway
file contains unrendered placeholders.

## Traffic flow

Guest: VM -> `brvx-<VNI>` -> `vxlan<VNI>` (FDB entry from EVPN type-2) -> encapsulated to the
destination host's VTEP over the management network -> decapsulated -> destination VM or VR.
Broadcasts are copied to every VTEP in the VNI (EVPN type-3, head-end replication).

Public: VR public NIC -> `brvx-<public VNI>` -> VXLAN to the gateway -> `br-pub` ->
`eth1.<env_pubvlan>` (tagged) -> parent trunk -> the public gateway router. Replies and inbound
traffic (port forwarding, static NAT) take the same path back.

Isolation: each environment has its own BGP mesh and gateway, VXLAN devices never learn from
traffic, and the peer-only firewall rejects other sources. The public VLAN stays shared between
environments, as with plain VLAN builds.

## Verifying a build

KVM host:

```
ip -4 addr show dev lo                    # management IP as /32, scope global
vtysh -c 'show bgp l2vpn evpn summary'    # all peers (hosts + gateway) up
vtysh -c 'show evpn vni'                  # guest VNIs (+ public VNI)
ip -d link show vxlan<VNI>                # local <mgmt IP> dstport 4789 nolearning
```

Gateway:

```
bridge link show master br-pub            # vxlan<public VNI> + eth1.<env_pubvlan>
docker exec clab-evpngw-frr vtysh -c 'show bgp l2vpn evpn summary'
docker exec clab-evpngw-frr vtysh -c 'show evpn mac vni <public VNI>'
```

CloudStack: the guest (and public) physical network shows isolation VXLAN, new guest networks
get a `vxlan://<VNI>` broadcast URI, system VMs run, and VMs behind a VR reach the internet.

## Vendored script

`roles/kvm/files/modifyvxlan-evpn.sh` is an unmodified copy of
`scripts/vm/network/vnet/modifyvxlan-evpn.sh` from apache/cloudstack `main`, fetched
2026-09-23, sha256 `f9da25ca049f49050cca34c46d3ab523b0527f0c633cc405f3dbe5be6cbf446f`
(Apache License 2.0). Refresh it when upstream changes.

## Known limitations

* One gateway per environment, no redundancy.
* Peer lists (FRR neighbours and firewall rules) are fixed at build time: additional pods are
  rejected, and hosts added by hand need FRR and firewall peers updated on every host and the
  gateway. An additional zone is a separate build with its own EVPN domain.
* The gateway advertises every MAC it learns on the shared public VLAN into the environment's
  EVPN (harmless at lab scale).
* Marvin `test_data.py.j2` contains fixed VLAN IDs and `specifyVlan` offerings; on a VXLAN guest
  network these become VNIs. Select tests accordingly.
* Open vSwitch, public-only mode and IPv6 underlay are not implemented.
