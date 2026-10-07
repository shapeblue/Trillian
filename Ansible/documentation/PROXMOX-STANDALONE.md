# Standalone Proxmox VE cluster

`deployproxmox.yml` builds a Proxmox VE cluster (default 3 nodes) as VMs in the parent cloud,
**without** a CloudStack environment. The nodes are not added to CloudStack; they are prepared
so that they can be added manually later (CloudStack's Proxmox extension, hypervisor type
External).

## What gets built

| Item | Value |
|---|---|
| VMs | `<env>-pve1` .. `<env>-pveN` in project `<env>-NestedClouds` (tagged like Trillian builds, plus `role=proxmox`) |
| Base image | Trillian's Debian template: `d12` -> Proxmox VE 8, `d13` -> Proxmox VE 9 (`pve_os`) |
| NIC 1 (`eth0`) | `management_network` -> bridge **`vmbr0`** with the management IP (static, = the address the parent DHCP assigned), cluster traffic, web UI |
| NIC 2 (`eth1`) | `guest_public_network` (trunk) -> bridge **`vmbr1`**, VLAN-aware (VLANs 2-4094), no IP |
| Data disk | extra volume per node -> VG `pve`, thin pool `data`, storage **`local-lvm`** (as on a Proxmox ISO install) |
| Storage | `local` (directory, ISOs/templates) and `local-lvm` (VM disks); no shared storage |
| Cluster | `pvecm create` on node 1, the others join one at a time (corosync over the management network) |
| Repositories | `pve-no-subscription`; enterprise repositories removed |
| Access | `https://<node-ip>:8006`, user `root`, realm Linux PAM, password = `pve_password` |

The NIC layout is identical to Trillian's KVM hosts (`eth0`/`cloudbr0`, `eth1`/`cloudbr1`), so
the nodes sit on the same management network and VLAN trunk as the KVM hosts of any Trillian
environment. That is what CloudStack's Proxmox extension needs later: Proxmox VMs reach the
CloudStack virtual routers (which run on KVM hosts) over the trunk.

## Running it

From the Trillian `Ansible/` directory (the same host and `group_vars/all` used by Trillian builds):

```
ansible-playbook deployproxmox.yml -i localhost --extra-vars "env_name=pve-lab-1"
```

| Option | Default | Meaning |
|---|---|---|
| `env_name` | required | name of the build (VM names, project, inventory file) |
| `pve_nodes` | `3` | number of nodes (1-16) |
| `pve_os` | `d12` | `linux_os` key of a Debian 12 (PVE 8) or Debian 13 (PVE 9) template |
| `pve_password` | `def_kvm_password` | root / web UI password |
| `pve_service_offering` | `def_kvm_service_offering` | parent-cloud offering (nested virtualization, like KVM hosts) |
| `pve_data_disk_offering` | `def_local_storage_disk_offering` | offering of the data disk |
| `pve_data_disk_size` | `100` | data disk size in GB (`local-lvm`) |
| `pve_cluster_name` | first 15 characters of the env name | Proxmox cluster name (max 15) |
| `pve_domain` | `pve.lab` | domain for the nodes' FQDNs |
| `build_project` | `<env>-NestedClouds` | parent-cloud project |

Role defaults (`roles/proxmox/defaults/main.yml`): Proxmox repository and key URLs (override
with mirrors if needed), interface names, and `pve_data_disk` (empty = detect the unused disk).

The run writes `hosts_<env>`; remove everything with:

```
ansible-playbook destroyproxmox.yml -i hosts_<env>
```

This is not registered in the Trillian environments database (no VLAN or IP leases are needed),
so environment listing/cleanup jobs do not know about it - destroy it with the playbook above.

### Jenkins

The `Reference_Trillian` job builds CloudStack environments only. For Jenkins, create a separate
job (copy the source-code and group-vars steps of `Reference_Trillian`) with parameters such as
`ENV_NAME`, `PVE_NODES`, `PVE_OS`, running:

```
cd Ansible
ansible-playbook deployproxmox.yml -i localhost --extra-vars "env_name=${ENV_NAME} pve_nodes=${PVE_NODES} pve_os=${PVE_OS}"
```

and a matching destroy job running `destroyproxmox.yml -i hosts_${ENV_NAME}`.

## Build steps

1. Create the project, build the nodes stopped, attach the data disks, start them.
2. Per node (`roles/proxmox`): hostname and `/etc/hosts` (node name -> management IP, as Proxmox
   requires), chrony (timezone role), Proxmox repository, full upgrade, Proxmox kernel + reboot,
   `proxmox-ve`, Debian kernel and os-prober removed, enterprise repositories removed,
   `/etc/network/interfaces` with `vmbr0`/`vmbr1` (netplan/networkd and cloud-init networking
   disabled), reboot, checks, VG `pve` / thin pool `data` on the data disk.
3. Cluster (one node at a time): node 1 runs `pvecm create`; the others get an SSH key authorized
   on node 1 and run `pvecm add <node1> --use_ssh 1`; each waits until it is quorate.
4. Storage `local-lvm` added once (cluster-wide); the run waits until all nodes are online and
   the cluster is quorate.

Every step is idempotent, so a failed run can be repeated with the same command.

## Adding it to CloudStack later (manual)

CloudStack 4.21+, Proxmox extension (see the CloudStack docs, "In-built Orchestrator
Extensions"): create a Proxmox API token, create a cluster with hypervisor `External` and
extension `Proxmox`, and add each node as a host with `url=https://<node-ip>:8006`, `user`,
`token`, `secret`, `node=<node name>`, `network_bridge=vmbr1` and `verify_tls_certificate=false`.
The zone also needs KVM hosts (virtual routers) on the same trunk, and guest networks used by
Proxmox VMs must be VLAN-isolated. Without shared storage, templates/ISOs must exist at the same
path on every node.

## Limitations

* Debian 12/13 templates only (Proxmox is installed on Debian, no Proxmox ISO template).
* No shared storage, no Ceph.
* VMs inside Proxmox have no DHCP on the management network (the parent cloud only serves its
  own VMs): use `vmbr1` with lab VLANs, static IPs, or a Proxmox SDN zone with DHCP/SNAT.
* Not tracked in the Trillian environments database.
