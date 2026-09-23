# KVM VXLAN guest isolation with BGP-EVPN (phase 1)

This option builds a nested CloudStack environment whose **guest** networks use VXLAN
isolation with a BGP-EVPN control plane (FRR) on the nested KVM hosts. **Public**,
management and storage traffic are unchanged (public stays on the leased VLAN).

Everything is behind `kvm_vxlan_evpn` (default `no`). With the flag unset or `no`, all
templates render exactly as before.

> **Branch default:** on the `kvm-vxlan-evpn-phase1` branch the default is `yes`, so every
> build from this branch is a VXLAN/EVPN build. Pass `kvm_vxlan_evpn=no` (Jenkins:
> `ANY_OTHER_OPTS`) for a normal build. Drop this commit before merging to master.
> `evpn_public_vxlan` also defaults to `yes` on this branch; pass `evpn_public_vxlan=no` for phase 1 only.

## Requirements

* `hvtype=k` with an EL9 (or later EL) `kvm_os`, `kvm_network_mode=bridge` (default)
* `env_zonetype=advanced`, `env_zone_secgroups=no`
* nested KVM hosts (not `use_phys_hosts` / `use_external_hv_hosts`)
* CloudStack 4.19 or later
* the parent network carrying the KVM hosts' management NIC must pass frames of
  `kvm_underlay_mtu` (default 9000; minimum 1550) and allow tcp/179 and udp/4789
  between the environment's VMs
* the `frr` package must be installable on the KVM hosts (distro repo or `evpn_frr_repo_baseurl`)

The build fails early (in `deployvms.yml`) if these are not met.

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `kvm_vxlan_evpn` | `no` | enable the feature |
| `kvm_underlay_mtu` | `9000` | MTU on `eth0` and the management bridge (VXLAN underlay) |
| `kvm_vxlan_guest_label` | `kvm_mgmt_network_label` | KVM traffic label of the VXLAN guest physical network |
| `vxlan_vni_base` | `100000` | guest VNI range = base + leased guest VLAN range (e.g. 501-520 -> 100501-100520) |
| `evpn_bgp_asn` | `65000` | private ASN of the per-environment iBGP full mesh |
| `evpn_frr_repo_baseurl` | empty | optional FRR repo mirror (FRR >= 10 recommended by the CloudStack docs) |
| `evpn_force_vendored_script` | `no` | always use Trillian's copy of the EVPN script |

VNIs are derived from the environment's existing guest VLAN lease, so they are unique per
active environment without any Trillian database change.

## Jenkins / command line

Add to the usual `generate-cloudconfig.yml` extra vars, for example:

```
hvtype=k kvm_os=<el9 value> env_zonetype=advanced env_zone_secgroups=no kvm_vxlan_evpn=yes
```

and optionally `kvm_underlay_mtu=9000 vxlan_vni_base=100000 evpn_bgp_asn=65000`.
`deployvms.yml` needs no extra arguments; the values are stored in `group_vars/<env_name>`.

## What gets built

On every KVM host (`roles/kvm/tasks/kvm_vxlan_evpn.yml`):

1. `eth0` and the management bridge are created with `kvm_underlay_mtu` (EL8/EL9 nmcli path).
2. The host's management IP is added as a `/32` on `lo` by `trillian-evpn-vtep.service`
   (ordered before `frr` and `cloudstack-agent`). The CloudStack EVPN script takes the VTEP
   address from `lo`, so the VTEP is the management IP and traffic still leaves via the bridge.
3. FRR is installed with `bgpd` enabled and an iBGP full mesh (`l2vpn evpn`, `advertise-all-vni`)
   to all other KVM hosts of the environment.
4. tcp/179 and udp/4789 are accepted **only from the environment's own peers** (other KVM hosts
   and the EVPN gateway): firewalld rich rules, or an iptables chain `TRILLIAN-EVPN` that drops
   everyone else. The kernel's VXLAN device decapsulates any packet for a known VNI regardless of
   its source, so this prevents leftovers of other environments (or other VMs on the management
   network) from injecting frames.
5. `/usr/share/modifyvxlan.sh` is created. The agent's script lookup finds this path before the
   packaged multicast `modifyvxlan.sh` (CloudStack 4.19+):
   * packaged `modifyvxlan-evpn.sh` exists (4.21+): symlink to it
   * otherwise (4.19, 4.20): Trillian's vendored copy `roles/kvm/files/modifyvxlan-evpn.sh`
   The path is not owned by any package, so agent upgrades do not overwrite it.
6. The play waits until BGP sessions to all peers are Established and fails otherwise.

In the zone (`deployzone.sh.j2`), three physical networks are created instead of two:

* `Physical Network Mgmt` - VLAN, Management traffic (unchanged)
* `Physical Network Public` - VLAN, Public traffic on `kvm_public_network_label`, leased public VLAN
* `Physical Network Guest VXLAN` - VXLAN, Guest traffic on `kvm_vxlan_guest_label`, derived VNI range

The Marvin configs describe the same layout.

## Vendored script

`roles/kvm/files/modifyvxlan-evpn.sh` is an unmodified copy of
`scripts/vm/network/vnet/modifyvxlan-evpn.sh` from apache/cloudstack `main`, fetched
2026-09-23, sha256 `f9da25ca049f49050cca34c46d3ab523b0527f0c633cc405f3dbe5be6cbf446f`
(Apache License 2.0). Refresh it when upstream changes.

## Verifying a build

On a KVM host after an instance on an isolated network has started:

```
ip -4 addr show dev lo                 # management IP as /32, scope global
ip -d link show | grep -A2 vxlan       # vxlan<VNI> ... local <mgmt-ip> dstport 4789 nolearning
vtysh -c 'show bgp l2vpn evpn summary' # all peers up
vtysh -c 'show evpn vni'               # VNIs with remote VTEPs
```

In CloudStack, the guest physical network shows isolation method VXLAN and new guest
networks get a `vxlan://<VNI>` broadcast URI.

## Phase 2: public traffic over VXLAN (`evpn_public_vxlan`)

With `evpn_public_vxlan=yes` (requires `kvm_vxlan_evpn`), Public traffic also uses VXLAN:

* `Physical Network Public` is created with isolation method **VXLAN** and KVM label
  `kvm_vxlan_guest_label`; it has no VNI range of its own.
* The public IP range is created with `vlan=vxlan://<public VNI>` (gateway, netmask and IPs are the
  normal Trillian public lease). CloudStack passes a range tag containing `://` through unchanged as
  the NIC broadcast URI, so VR/SSVM/CPVM public NICs land on `brvx-<public VNI>` on the KVM hosts.
* Public VNI = `evpn_public_vni`, or `vxlan_vni_base + env_pubvlan` (build fails if that falls inside
  the guest VNI range).

A gateway VM `<env>-evpngw` is built in the same parent project (KVM template/offering unless
overridden) with NICs on `management_network` and `guest_public_network`, and is configured
**before** the KVM hosts and the zone (`roles/evpn-gateway`):

| Piece | What it does |
|---|---|
| `trillian-evpn-gw-net.service` | management IP as /32 on `lo` (VTEP); `br-pub` = `vxlan<VNI>` (local VTEP, port 4789, nolearning) + `eth1.<env_pubvlan>`; bridged frames bypass iptables |
| Containerlab node `clab-evpngw-frr` | FRR in host network mode, iBGP `l2vpn evpn` to every KVM host, `advertise-all-vni` |
| `trillian-evpn-gw-clab.service` | (re)deploys the Containerlab topology at boot |

The KVM hosts peer with the gateway too, and their BGP check waits for it. NetworkManager is told to
leave the gateway's trunk NIC, VLAN, bridge and VXLAN devices alone. The gateway is destroyed with
the environment.

Frame path: VR public NIC -> `brvx-<VNI>` (KVM host) -> VXLAN/EVPN -> gateway `vxlan<VNI>` ->
`br-pub` -> `eth1.<vlan>` (tagged) -> parent trunk -> the public gateway router.

Gateway prerequisites: Docker CE and Containerlab packages (`evpn_gw_docker_repo_baseurl`,
`evpn_gw_containerlab_repo_baseurl`) and the FRR image (`evpn_gw_frr_image`) must be reachable from
the gateway VM; set these to lab mirrors if there is no internet access. The gateway's trunk NIC
must be allowed to send frames from other MACs (the same parent port-group settings the nested
KVM hosts already rely on).

Verify on the gateway:

```
bridge link show master br-pub                       # vxlan<VNI> and eth1.<vlan>
docker exec clab-evpngw-frr vtysh -c 'show bgp l2vpn evpn summary'
docker exec clab-evpngw-frr vtysh -c 'show evpn mac vni <VNI>'   # VR MACs (remote) + router MAC (local)
```

## Known limitations

* EL9+ KVM hosts only (Ubuntu/netplan and OVS paths are not implemented).
* The EVPN peer lists (FRR neighbours and the tcp/179 + udp/4789 firewall rules) are fixed at
  build time from the inventory. **Additional pods are rejected** at the start of the build, and
  hosts added by hand need FRR and firewall peers updated on every host and the gateway.
  An additional zone is a separate build and gets its own EVPN domain (own mesh and gateway).
* Marvin `test_data.py.j2` contains fixed VLAN IDs (e.g. 10, 301, 4000) and `specifyVlan`
  offerings. On a VXLAN guest network these are used as VNIs; select tests accordingly.
* Phase 2 builds one gateway per environment (no redundancy); `use_custom_allocator` is not supported.
