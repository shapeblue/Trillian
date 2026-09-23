# KVM VXLAN guest isolation with BGP-EVPN (phase 1)

This option builds a nested CloudStack environment whose **guest** networks use VXLAN
isolation with a BGP-EVPN control plane (FRR) on the nested KVM hosts. **Public**,
management and storage traffic are unchanged (public stays on the leased VLAN).

Everything is behind `kvm_vxlan_evpn` (default `no`). With the flag unset or `no`, all
templates render exactly as before.

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
4. tcp/179 and udp/4789 are opened (firewalld or iptables, following `use_firewalld`).
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

## Known limitations

* EL9+ KVM hosts only (Ubuntu/netplan and OVS paths are not implemented).
* Marvin `test_data.py.j2` contains fixed VLAN IDs (e.g. 10, 301, 4000) and `specifyVlan`
  offerings. On a VXLAN guest network these are used as VNIs; select tests accordingly.
* Public over VXLAN and the Containerlab gateway are phase 2 and not part of this change.
