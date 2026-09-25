# KVM: VXLAN / BGP-EVPN for guest and public traffic

Trillian can build nested CloudStack environments whose KVM **guest** traffic and/or **public**
traffic uses VXLAN isolation with a BGP-EVPN control plane (FRR), instead of VLANs. Public
traffic reaches the lab's public VLAN through a small per-environment gateway VM that runs FRR
as a Containerlab node and bridges the public VNI onto the public VLAN.

Contents: modes, requirements, KVM OS support, using it (Jenkins and command line), variables,
architecture, what gets built, build order, traffic flow, isolation, verification,
troubleshooting, limitations, files.

---

## 1. Modes

Two independent flags select what runs over VXLAN. Both default to `no`; with both unset or
`no`, every template renders exactly as in a standard Trillian build.

| `kvm_vxlan_evpn` (guest) | `evpn_public_vxlan` (public) | Guest traffic | Public traffic | EVPN on KVM hosts | Gateway VM | State |
|---|---|---|---|---|---|---|
| `no` | `no` | VLAN | VLAN | no | no | standard Trillian |
| `yes` | `no` | VXLAN / EVPN | VLAN | yes | no | verified |
| `yes` | `yes` | VXLAN / EVPN | VXLAN -> gateway -> public VLAN | yes | yes | verified |
| `no` | `yes` | VLAN | VXLAN -> gateway -> public VLAN | yes | yes | verified |

"EVPN on KVM hosts" (FRR, VTEP, underlay MTU, peer-only firewall) is derived automatically:
`kvm_evpn_enabled` is written to the environment's group vars as the expression
`(kvm_vxlan_evpn | bool) or (evpn_public_vxlan | bool)` and evaluated at deploy time, so it can
never disagree with the two flags. Do not set it yourself.

---

## 2. Requirements

When either flag is `yes`:

* KVM build (`hvtype=k`) with a supported KVM host OS (section 3)
* advanced zone **without** security groups
* `kvm_network_mode=bridge` (Linux bridge, not Open vSwitch)
* nested KVM hosts (not `use_phys_hosts` / `use_external_hv_hosts`), not an additional pod
* CloudStack 4.19 or later
* `kvm_underlay_mtu` >= 1550, and the parent network carrying the hosts' management NIC must
  pass frames of that size (default 9000; the lab's `dvs_Data` is 9000)
* FRR installable on the KVM hosts: distribution package, or a repository via
  `evpn_frr_repo_baseurl` (dnf/zypper) or `evpn_frr_apt_repo` (Ubuntu)

Additionally, with `evpn_public_vxlan=yes`:

* an EL9 template for the gateway VM (picked automatically, see 7.3)
* Docker CE, Containerlab and the FRR container image reachable from the gateway VM
  (internet, or mirrors via the `evpn_gw_*` variables)
* the parent trunk network (`guest_public_network`) must allow the gateway VM to send frames
  with other MACs (the same setting the nested KVM hosts already rely on)

Unsupported combinations stop the build at the start with an explanation: in `deployvms.yml`
(zone type, security groups, backend, host type, additional pod, CloudStack version, MTU,
gateway template, gateway in the inventory, public VNI overlap) and per host in the KVM role
(OS allow-list).

---

## 3. KVM host OS support

| KVM OS | Id | State | FRR source | Underlay MTU set by | Firewall |
|---|---|---|---|---|---|
| EL8, EL9, EL10 (Rocky, Alma, Oracle Linux) | `el8`, `el9`, `el10` | verified | AppStream, or `evpn_frr_repo_baseurl` | nmcli bridge setup (`kvm_networking_bridge8.yml`) | firewalld or iptables |
| Ubuntu 24.04 | `ubuntu24.04` | verified | Ubuntu `frr`, or `evpn_frr_apt_repo` | `netplan.j2` | ufw if active, else iptables + netfilter-persistent |
| Ubuntu 22.04 | `ubuntu22.04` | implemented, not verified | Ubuntu `frr`, or `evpn_frr_apt_repo` | `netplan.j2` | as Ubuntu 24.04 |
| openSUSE Leap 15.x | `opensuse-leap15` | verified (15.6) | Leap OSS `frr`, or `evpn_frr_repo_baseurl` | nmcli bridge setup | firewalld or iptables |
| EL7, Ubuntu 20.04, Debian, others | - | not supported | - | - | - |

* The OS id comes from `os_facts` on EL (`el<major>`) and from `/etc/os-release` on other
  distributions (`os_facts` returns no version on SUSE).
* The lists live in `roles/kvm/tasks/main.yml`: `evpn_os_implemented` and `evpn_os_verified`.
  An implemented but unverified OS builds only with `evpn_allow_untested_os=yes`. An OS is
  moved to "verified" in its own commit after a passing lab build.
* The **gateway VM is always EL9**, whatever the KVM host OS.
* The management server OS is independent of all of this.

---

## 4. Using it

### 4.1 Jenkins (Reference_Trillian)

Standard KVM settings: `PRIMARY_HYPERVISOR=k`, a supported `KVM_OS`, `HYPERVISOR_COUNT` >= 2,
`ZONE_TYPE=Advanced`, `KVM_NETWORK_BACKEND=bridge`, CloudStack 4.19+, `TRILLIAN_BRANCH` set to
a branch containing this feature. Then either:

**a) `ANY_OTHER_OPTS`** (works without any job change), space-separated:

```
kvm_vxlan_evpn=yes evpn_public_vxlan=yes      # guest + public
kvm_vxlan_evpn=yes evpn_public_vxlan=no       # guest only
kvm_vxlan_evpn=no  evpn_public_vxlan=yes      # public only
```

**b) Dedicated job parameters (recommended).** Add two Choice parameters to the job
(Configure -> "This project is parameterized" -> Add Parameter), first value = default:

* `GUEST_ISOLATION`: `VLAN`, `VXLAN`
* `PUBLIC_ISOLATION`: `VLAN`, `VXLAN`

In the "Execute shell" build step, before the `generate-cloudconfig.yml` call, add:

```bash
EVPN_OPTS="kvm_vxlan_evpn=no evpn_public_vxlan=no"
[ "$GUEST_ISOLATION" = "VXLAN" ]  && EVPN_OPTS="kvm_vxlan_evpn=yes evpn_public_vxlan=no"
[ "$PUBLIC_ISOLATION" = "VXLAN" ] && EVPN_OPTS="${EVPN_OPTS% evpn_public_vxlan=no} evpn_public_vxlan=yes"
```

and insert `${EVPN_OPTS}` into the `--extra-vars '...'` string (next to `ANY_OTHER_OPTS`).
With the defaults (`VLAN`/`VLAN`) the job passes both flags as `no`; branches without this
feature ignore the variables entirely, so the change is safe for every other build. Boolean
(checkbox) parameters work the same way if preferred.

### 4.2 Command line

Pass the flags (and any variables from section 5) in the `generate-cloudconfig.yml` extra vars.
`deployvms.yml` needs nothing extra; everything is stored in `group_vars/<env_name>`.

---

## 5. Variables

All optional; pass them like the flags.

| Variable | Default | Meaning |
|---|---|---|
| `kvm_vxlan_evpn` | `no` | guest traffic over VXLAN/EVPN |
| `evpn_public_vxlan` | `no` | public traffic over VXLAN; builds the gateway VM |
| `kvm_evpn_enabled` | derived | EVPN on the KVM hosts; computed from the two flags, do not set |
| `kvm_underlay_mtu` | `9000` | MTU of the underlay (KVM `eth0`/`cloudbr0`, gateway `eth0`); minimum 1550 |
| `kvm_vxlan_guest_label` | `kvm_mgmt_network_label` (`cloudbr0`) | KVM traffic label of the VXLAN physical networks (the underlay bridge) |
| `vxlan_vni_base` | `100000` | guest VNIs = base + leased guest VLAN range (e.g. 501-520 -> 100501-100520); default public VNI = base + public VLAN |
| `evpn_public_vni` | derived | explicit public VNI; with guest VXLAN it must not fall inside the guest VNI range |
| `evpn_bgp_asn` | `65000` | private ASN of the per-environment iBGP mesh |
| `evpn_frr_repo_baseurl` | empty | dnf/zypper repository for FRR (directory containing `repodata/`; literal path, no `$releasever`) |
| `evpn_frr_apt_repo` | empty | Ubuntu: complete apt sources line, e.g. `deb [trusted=yes] http://<mirror>/frr noble frr-stable` |
| `evpn_force_vendored_script` | `no` | always use Trillian's copy of the EVPN script |
| `evpn_allow_untested_os` | `no` | allow an implemented but not yet verified KVM OS (currently Ubuntu 22.04) |
| `evpn_gw_template` | auto | gateway template (see 7.3) |
| `evpn_gw_os` | empty | `linux_os` key of the EL9 OS to take the gateway template from (e.g. `r9`) |
| `evpn_gw_service_offering` | KVM offering | gateway service offering |
| `evpn_gw_trunk_if` | `eth1` | gateway NIC on the trunk network (public VLAN side) |
| `evpn_gw_frr_image` | `quay.io/frrouting/frr:10.2.1` | FRR container image |
| `evpn_gw_docker_repo_baseurl` | Docker CE CentOS 9 stable | Docker CE repository for the gateway |
| `evpn_gw_containerlab_repo_baseurl` | `https://yum.fury.io/netdevops/` | Containerlab repository for the gateway |

VNIs are derived from the environment's existing Trillian leases, so no Trillian database
change is needed and VNIs are unique per active environment.

---

## 6. Architecture

* **Underlay:** the environment's existing management network in the parent cloud (one L2
  segment). No extra networks.
* **VTEP address:** each VM's management IP, also added as a `/32` on `lo`. CloudStack's EVPN
  VXLAN script takes its VTEP from `lo`; since the address is the same as on the management
  bridge, traffic still leaves via that bridge and no underlay routing is needed.
* **Control plane:** per environment, an iBGP full mesh (`l2vpn evpn` only, `advertise-all-vni`)
  between all KVM hosts and, with public VXLAN, the gateway. Peers are generated from the
  inventory. Hosts advertise type-3 routes (flood list per VNI) and type-2 routes (MAC per VNI).
* **Data plane:** Linux VXLAN devices created with `nolearning` (forwarding entries only from
  EVPN), UDP port 4789, broadcasts by head-end replication. Guests and VRs keep MTU 1500.
* **Routing and NAT:** by the CloudStack virtual routers, as usual. EVPN carries only L2 VNIs.
* **Public handoff:** the gateway VM bridges the public VNI onto the public VLAN; the lab router
  (e.g. SL-Router-01) keeps the public gateway address.

---

## 7. What gets built

### 7.1 Zone (`roles/cloudstack-config/templates/deployzone.sh.j2`)

| Mode | Physical networks |
|---|---|
| standard | Mgmt (VLAN, management); Guest Public (VLAN, guest + public) |
| guest only | Mgmt (VLAN); Public (VLAN, label `cloudbr1`, public VLAN); Guest VXLAN (VXLAN, label `cloudbr0`, guest VNI range) |
| guest + public | Mgmt (VLAN); Public (VXLAN, label `cloudbr0`); Guest VXLAN (VXLAN, label `cloudbr0`, guest VNI range) |
| public only | Mgmt (VLAN); Public (VXLAN, label `cloudbr0`); Guest (VLAN, label `cloudbr1`, leased guest VLAN range) |

* The public IP range always uses the normal Trillian public lease (gateway, netmask, IPs). Its
  VLAN field is `<env_pubvlan>`, or `vxlan://<public VNI>` with public VXLAN. CloudStack passes a
  range tag containing `://` unchanged into the NIC broadcast URI, so VR, SSVM and CPVM public
  NICs get `vxlan://<public VNI>` and the agent attaches them to a VXLAN bridge. This works
  through the normal API on 4.19+.
* Guest networks on a VXLAN guest physical network get `vxlan://<VNI>` broadcast URIs.
* The Marvin configs (`templates/advanced-cfg.j2`, `roles/marvin/templates/advanced-cfg.j2`)
  describe the same layout.

### 7.2 KVM hosts (`roles/kvm/tasks/kvm_vxlan_evpn.yml` + per-OS files)

Run whenever guest and/or public uses VXLAN:

1. `eth0` and `cloudbr0` get `kvm_underlay_mtu` (nmcli on EL/SUSE, `netplan.j2` on Ubuntu); the
   play checks that it was applied.
2. `trillian-evpn-vtep.service` adds the management IP as `/32` on `lo`, ordered before `frr`
   and `cloudstack-agent`. `/run/cloud` is created for the EVPN script's lock file.
3. FRR (`kvm_vxlan_evpn_install_{el,ubuntu,suse}.yml`), `bgpd` enabled, `/etc/frr/frr.conf`
   from `frr-evpn.conf.j2`: iBGP mesh to the other KVM hosts and the gateway.
4. Peer-only firewall (`kvm_vxlan_evpn_firewall_{el,ubuntu}.yml`; SUSE uses the EL file):
   tcp/179 and udp/4789 accepted only from the environment's peers - firewalld rich rules, ufw
   rules, or the iptables chain `TRILLIAN-EVPN` (peers ACCEPT, everything else DROP).
5. `/usr/share/modifyvxlan.sh` points to the EVPN script. The agent's script lookup finds this
   path before the packaged multicast `modifyvxlan.sh`: a symlink to the packaged
   `modifyvxlan-evpn.sh` on 4.21+, otherwise the vendored copy (4.19/4.20). The path is not owned
   by any package, so agent upgrades keep it. A running agent is restarted when it changes.
6. The play waits until BGP sessions to all peers are Established and fails otherwise.

### 7.3 Gateway VM (`roles/evpn-gateway`, public VXLAN only)

* Name `<env>-evpngw`, same parent project as the other VMs, built by `buildvms.yml` or
  `buildvms_custom_allocator.yml` (started in the cluster/host the allocator chose for the KVM
  hosts). NICs: `management_network` (`eth0`) and `guest_public_network` (`eth1`, trunk).
  Destroyed with the environment (`removeproject.yml`).
* Template, resolved at generate time: `evpn_gw_template`, else `linux_os[evpn_gw_os].template`,
  else the KVM template if the KVM OS has `os_type: el9`, else the first `linux_os` entry with
  `os_type: el9`. The build stops if none is found and prints the chosen template.
* Configured before the KVM hosts and the zone. The environment lease (`env_pubvlan`) is taken
  from `localhost`'s facts; the play checks VLAN/VNI are valid numbers and that no gateway file
  contains unrendered placeholders.

| Piece | Location | What it does |
|---|---|---|
| NetworkManager exclusion | `/etc/NetworkManager/conf.d/99-trillian-evpn-gw.conf` | NM leaves `eth1`, `eth1.*`, `br-pub`, `vxlan*` alone |
| Bridge script + unit | `/usr/local/sbin/trillian-evpn-gw-net.sh`, `trillian-evpn-gw-net.service` | VTEP `/32` on `lo`; `br-pub` = `vxlan<VNI>` (local VTEP, 4789, nolearning) + `eth1.<env_pubvlan>`; bridged frames bypass iptables; peer-only firewall (iptables path) |
| Docker CE, Containerlab | packages | runtime for the FRR node |
| FRR config | `/etc/trillian-evpn/frr/{daemons,frr.conf,vtysh.conf}` | iBGP `l2vpn evpn` to every KVM host |
| Containerlab topology + unit | `/etc/trillian-evpn/clab/evpn-gw.clab.yml`, `trillian-evpn-gw-clab.service` | node `clab-evpngw-frr` in host network mode, (re)deployed at boot |

The gateway has no public IP and does no routing or NAT.

---

## 8. Build order (`deployvms.yml`)

1. Validations (section 2), public VNI overlap check, gateway template and inventory checks.
2. Leases (public, pod, guest VLANs) and VM creation, including the gateway VM.
3. Management server(s) and database.
4. **Gateway VM** (`timezone` + `evpn-gateway` roles).
5. **KVM hosts** (`kvm` role, including the EVPN tasks and the BGP wait for all peers).
6. Zone creation (`cloudstack-config`), system VMs, optional Marvin.

The gateway must be up before the zone: SSVM, CPVM and VR public NICs use the public VNI.

---

## 9. Traffic flow

**Guest (guest VXLAN):** VM -> `brvx-<VNI>` -> `vxlan<VNI>` -> bridge FDB entry from an EVPN
type-2 route -> encapsulated (UDP 4789, +50 bytes) to the destination host's VTEP over the
management network -> peer-only firewall -> decapsulated -> `brvx-<VNI>` -> destination VM or
VR. Broadcasts (ARP, DHCP) are copied to every VTEP in the VNI's type-3 list.

**Guest (guest VLAN, public-only mode):** unchanged standard path over `cloudbr1` and the
leased guest VLANs.

**Public (public VXLAN):** the VR source-NATs to its public IP and sends to the public gateway
address. The first ARP is replicated to all VTEPs of the public VNI, including the gateway. The
gateway decapsulates it, `br-pub` forwards it out of `eth1.<env_pubvlan>` (tagged) across the
parent trunk to the lab router. The router's reply returns tagged; the gateway learns the
router MAC on the VLAN side (advertised into EVPN) and already knows from EVPN which host the
VR MAC is behind. Afterwards traffic is unicast: VR host -> VXLAN -> gateway -> VLAN -> router.
Port forwarding and static NAT use the same path in reverse.

**Public (public VLAN):** unchanged standard path over `cloudbr1` / `eth1.<env_pubvlan>`.

---

## 10. Isolation and security

* Each environment has its own BGP mesh and its own gateway; environments never learn each
  other's VTEPs or MACs, even though the public VNI number is the same everywhere.
* VXLAN devices never learn from received traffic (`nolearning`).
* Peer-only firewall: the kernel VXLAN device decapsulates packets for a known VNI from any
  source, so udp/4789 and tcp/179 are restricted to the environment's peers. This blocks
  leftovers of partly destroyed environments whose IPs were reused, and other VMs on the shared
  management network.
* Each EVPN domain touches the public VLAN at exactly one point (its gateway), so there is no L2
  loop. The public VLAN itself stays shared between environments, as with VLAN builds.

---

## 11. Verification

KVM host:

```
ip link show cloudbr0 | grep -o 'mtu [0-9]*'     # kvm_underlay_mtu
ip -4 addr show dev lo                           # management IP as /32, scope global (not visible in ifconfig)
systemctl is-active trillian-evpn-vtep frr       # active active
vtysh -c 'show bgp l2vpn evpn summary'           # all peers (hosts + gateway) up
vtysh -c 'show evpn vni'                         # guest VNIs and/or the public VNI
ip -d link show vxlan<VNI>                       # local <mgmt IP> dstport 4789 nolearning
bridge fdb show dev vxlan<VNI> | grep dst        # entries to remote VTEPs
ls -l /usr/share/modifyvxlan.sh                  # symlink (4.21+) or vendored file
iptables -S TRILLIAN-EVPN                        # or: firewall-cmd --list-rich-rules / ufw status
```

Gateway VM:

```
systemctl status trillian-evpn-gw-net trillian-evpn-gw-clab --no-pager
bridge link show master br-pub                   # vxlan<public VNI> + eth1.<env_pubvlan>
docker exec clab-evpngw-frr vtysh -c 'show bgp l2vpn evpn summary'
docker exec clab-evpngw-frr vtysh -c 'show evpn mac vni <public VNI>'   # router MAC local, VR/SSVM/CPVM MACs remote
tcpdump -eni eth1.<env_pubvlan> arp              # ARP to and from the public VLAN
```

CloudStack: the physical networks match 7.1; new guest networks get `vxlan://<VNI>` when guest
VXLAN is on; system VMs run; a VM behind a VR reaches the internet; port forwarding works.

The gateway normally learns every MAC on the shared public VLAN (other environments, the parent
cloud's VRs, the router) and advertises them into the environment's EVPN; that is expected.

---

## 12. Troubleshooting

| Symptom | Cause | What to do |
|---|---|---|
| Build stops at "Validate KVM VXLAN/EVPN settings" | unsupported combination (section 2) | adjust the Jenkins settings |
| "VXLAN/EVPN is enabled but ... runs ..." | KVM OS not in the verified list | use a supported OS, or `evpn_allow_untested_os=yes` for implemented ones |
| "needs an EL9 template for the gateway VM" | no `os_type: el9` entry in `linux_os` | set `evpn_gw_os` or `evpn_gw_template` |
| "EVPN - install FRR" fails | FRR not in the host's repositories | `evpn_frr_repo_baseurl` / `evpn_frr_apt_repo` |
| "EVPN GW - install/pull" fails | gateway can't reach Docker, Containerlab or quay.io | mirror URLs via the `evpn_gw_*` variables |
| "EVPN - check the underlay MTU was applied" fails | MTU not applied by nmcli/netplan | check the host's network config; the parent network must allow the MTU |
| BGP wait times out | a peer failed earlier, firewall, or MTU | check the failed host first, then `vtysh -c 'show bgp summary'` |
| System VMs run but have no public connectivity | public VNI not connected to the VLAN | on the gateway: `bridge link show master br-pub`; on a host: `show evpn vni <public VNI>` must list the gateway VTEP |
| Strange failures on a freshly built VM (wrong OS, old repos) | duplicate IP on the management network (stale VM) | check hostname/MAC of the VM Ansible reaches; remove the stale VM |

---

## 13. Known limitations

* One gateway per environment, no redundancy (a second gateway in the same environment would
  create an L2 loop).
* Peer lists (FRR neighbours and firewall rules) are fixed at build time: additional pods are
  rejected; hosts added by hand need FRR and firewall peers updated on every host and the
  gateway. An additional zone is a separate build with its own EVPN domain.
* No broadcast rate limit on the gateway's VLAN side.
* Marvin `test_data.py.j2` contains fixed VLAN IDs and `specifyVlan` offerings; on a VXLAN guest
  network these become VNIs. Select tests accordingly.
* Open vSwitch, IPv6 underlay and the OSes listed as not supported are not implemented.

---

## 14. Files

| File | Role |
|---|---|
| `templates/nestedgroupvars.j2` | flags, derived `kvm_evpn_enabled`, variables, gateway template selection |
| `templates/nestedinventory.j2` | `evpn_gateway_hosts` group (public VXLAN) |
| `generate-cloudconfig.yml` | parameter notes |
| `deployvms.yml` | validations, gateway play before the KVM play |
| `tasks/buildvms.yml`, `tasks/buildvms_custom_allocator.yml` | gateway VM creation |
| `tasks/removeproject.yml` | gateway VM removal |
| `roles/kvm/tasks/main.yml` | OS id and allow-list check |
| `roles/kvm/tasks/{el9,centos8,ubuntu,suse}.yml` | include the EVPN tasks |
| `roles/kvm/tasks/kvm_vxlan_evpn.yml` | shared EVPN tasks |
| `roles/kvm/tasks/kvm_vxlan_evpn_install_{el,ubuntu,suse}.yml` | FRR installation |
| `roles/kvm/tasks/kvm_vxlan_evpn_firewall_{el,ubuntu}.yml` | peer-only firewall |
| `roles/kvm/tasks/kvm_networking_bridge8.yml`, `roles/kvm/templates/netplan.j2` | underlay MTU |
| `roles/kvm/templates/{frr-evpn.conf.j2,trillian-evpn-vtep.service.j2}` | FRR config, VTEP unit |
| `roles/kvm/files/modifyvxlan-evpn.sh` | vendored EVPN script |
| `roles/evpn-gateway/` | gateway role (tasks, templates, files) |
| `roles/cloudstack-config/templates/deployzone.sh.j2` | zone layout per mode |
| `templates/advanced-cfg.j2`, `roles/marvin/templates/advanced-cfg.j2` | Marvin zone description |

### Vendored script

`roles/kvm/files/modifyvxlan-evpn.sh` is an unmodified copy of
`scripts/vm/network/vnet/modifyvxlan-evpn.sh` from apache/cloudstack `main`, fetched
2026-09-23, sha256 `f9da25ca049f49050cca34c46d3ab523b0527f0c633cc405f3dbe5be6cbf446f`
(Apache License 2.0). Refresh it when upstream changes.
