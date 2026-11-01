# Trillian - Build Nested CloudStack Environments

More detailed information can be found in the [Wiki](https://github.com/shapeblue/Trillian/wiki)

## Trillian makes use a 'parent' CloudStack' environment which is used to build virtualised nested environments.

Trillian leverages ESXi's ability to virtualise the VT-x features allowing the creation of VT-x enabled virtualised hosts

## Trillian uses Ansible 2 to create environment configuration files and deploy those environments. The user can run 2 commandline statements and go from 0 to a running cloudstack environment with multiple hosts. 

as an example:
```
ansible-playbook generate-cloudconfig.yml --extra-vars 'env_name=trillian-test-env env_comment='\''example nested cloudstack test environment'\''  use_shared_storage=true env_version=cs410 mgmt=1 db=0 hvtype=k  kvm_os=7 hv=2 env_accounts=all pri=2 sec=1 esxi_use_dvswitch=no build_marvin=yes wait_till_setup=yes wait_for_template=yes mgmt_os=7' -i localhost
```
at the end of this the sugestion, `You can now run: ansible-playbook deployvms.yml -i ./hosts_trillian-test-env`, is put on the output, which would trigger you to run something like
```
ansible-playbook deployvms.yml -i ./hosts_trillian-test-env --extra-vars 'env_name=trillian-test-env env_version=cs410'
```

for more examples see the [Wiki](https://github.com/shapeblue/Trillian/wiki)

### Basic variables:
+ `env_name` [mandatory]: Environment name, single string, characters, numbers, underscore \_ or dash - only.
+ `env_version` [mandatory]: Environment CloudStack version (cs45, cs46, cs49, custom, etc).
+ `mgmt_os` [mandatory]: Management server OS (6, 7, u, custom)
+ `hvtype` [mandatory]: XenServer (x), KVM (k) or VMware (v)
+ `pri` [mandatory]: number of primary storage pools.
+ `hv`: number of hypervisors. Please note if hypervisor type is VMware the assumption is made that a single VC host is also required.                            This does not have to be specified anywhere.

  One of the following three is required depending on the choosen Hypervisor (`hvtype`):
  + `kvm_os`:
    -	`6` = centos6.8
    -	`7` = centos7.1
    -	`u` = ubuntu14.04
  + `xs_ver`:
    -	`xs62sp1`
    -	`xs65sp1`
  + `vmware_ver`:
    -	`55u3`
    -	`60u1`

  In order to avoid template issues, `kvm_os`, `xs_ver`and `vmware_ver` will
  default to 'custom' when they are not specified.

  If you specify KVM as hypervisor (`hvtype=k`) you must specify the `kvm_os`
  **or** set it to 'custom' and set the template to use (`kvm_template`) in the
  extra vars (`kvm_template="Ubuntu Server 14.04"`)

  The same applies to the other hypervisor types. For custom VMware you would
  need to specify both the vCenter and ESXi templates



### Advanced variables [all optional]:
+ `mgmt`: Number of management servers to configure (default is 1)
+ `sec`: number of secondary storage pools. (default is 1)
+ `db`: Number of database servers to configure (default is 0 - db is on mgmt host)
+ `management_network`: name of the management network
+ `guest_public_network`: name of the guest+public network
+ `management_vm_hypervisor`: parent CloudStack cloud hypervisor (default VMware)
+ `build_project`: project name to use for the nested cloudstack build (default <accountname>-NestedClouds)
+ `build_zone`: parent cloud zone name
+ `build_keyboard`: keyboard used for nested VMs (default UK)
+ `mgmtsrv_service_offering`: parent cloud service offering used for the management server build
+ `mgmtsrv_template`: parent cloud template used for the management server build
+ `dbsrv_service_offering`: parent cloud service offering used for database server build
+ `dbsrv_template`: parent cloud template used for database server build
+ `kvm_service_offering`: parent cloud nested KVM instances service offering
+ `kvm_template`: parent cloud nested KVM HV template
+ `xs_service_offering`: parent cloud nested XenServer instances service offering
+ `xs_template`: parent cloud nested XenServer HV template
+ `esxi_service_offering`: parent cloud nested ESXi instances service offering
+ `esxi_template`: parent cloud nested ESXi HV template
+ `vc_service_offering`: parent cloud nested VC instances service offering
+ `vc_template`: parent cloud nested VirtualCentre template
+ `baseurl_cloudstack`: URL for CloudStack build repository
+ `env_db_name`: environments database name
+ `env_db_ip`: environments database IP address
+ `env_db_user`: environments database username
+ `env_db_password`: environments database password
+ `env_zonetype`: basic or advanced (default)
+ `env_prihost`: primary storage host fqdn or IP address
+ `env_sechost`: secondary storage host fqdn or IP address
+ `env_zone_systemplate`: URL to system template, overrides version variable
+ `build_marvin`: whether or not to build a marvin vm for testing purposes (default is false)
+ `wait_till_setup`: only return once system VMs are running. (default is no)


### Multiple KVM clusters with different distros (`kvm_clusters`)

CloudStack only accepts hosts of one OS family per KVM cluster, so testing
several KVM distros needs one cluster per distro. `kvm_clusters` builds them
in a single environment, in one pod:

+ `kvm_clusters`: comma separated `<kvm_os>:<hosts>[:<cluster name>]`, e.g.
  `ol9:2,u24:1,d12:1,s15:1`. Each `<kvm_os>` is a `linux_os` key from the
  `all` file. The default cluster name is `p1-c<N>-<kvm_os>`. Hosts are named
  `<env>-kvm1..N` in the order given (above: kvm1-2 OL9, kvm3 Ubuntu, kvm4
  Debian, kvm5 SUSE). Each host is built from its own distro's template and
  gets its own distro's package repo and Java.
+ `hv` must equal the total number of hosts (5 above). `hvtype=k`. `kvm_os`
  defaults to the first entry's distro.
+ `kvm_clusters_pool_scope`: `first` (default) attaches the primary pools to
  the first cluster only, so system VMs and shared-storage guests run there;
  `zone` makes them zone-wide so every cluster mounts them.
+ When the distros differ, the KVM repo must come from `rooturl_kvm` or
  `rooturl_cloudstack` (or the default root); a single `baseurl_kvm` or
  `baseurl_cloudstack` URL cannot serve every distro and is refused.
+ Not supported with `additional_pod`, `additional_zone`,
  `use_external_hv_hosts`, or by `upgrade_env.yaml`.

```
env_name=remediate env_dotted_version=4.22.1.0 mgmt_os=<ol9 code> hvtype=k hv=5 kvm_clusters=<ol9 code>:2,<u24 code>:1,<debian12 code>:1,<suse15 code>:1 pri=1 sec=1 env_accounts=all
```

### Running a script on the Marvin VM after the build (`post_deploy_script`)

With `build_marvin=yes`, `deployvms.yml` can finish by running a script of
your own on the Marvin VM, the way it queues the Marvin tests:

+ `post_deploy_script`: a file name in `Ansible/post_deploy_scripts/`, or an
  `http(s)://` URL to download it from.
+ `post_deploy_script_args`: arguments passed to it, as shell words.
+ `post_deploy_wait`: `no` (default) queues the script with `at` and the build
  finishes; `yes` runs it within the build and fails the build when it exits
  non-zero, printing the end of its log.
+ `post_deploy_timeout`: seconds before the script is killed (default 21600).

The script runs as root in `/marvin/post-deploy/`, with
`trillian-env.sh` sourced first: `TRILLIAN_API_URL`, `TRILLIAN_API_KEY` and
`TRILLIAN_SECRET_KEY` (the admin keys), `TRILLIAN_MGMT_IPS`,
`TRILLIAN_KVM_IPS` and their root passwords, `TRILLIAN_DB_HOST` with the
MySQL root and cloud passwords, `TRILLIAN_STAGING_SERVER`, the environment
name, UUID and CloudStack version. Its output goes to `<script>.log` and its
exit code to `<script>.exit`; `/marvin/post-deploy/run.sh` runs it again.
Marvin tests queued in the same build run against the lab at the same time.

#### Remediate apply smoke

`post_deploy_scripts/remediate-smoke-setup.sh` prepares the environment for the
remediate apply smoke and runs it. It downloads a remediate bundle from the
staging server (`http://<stagingserverip>/remediate/remediate-smoke-latest.tar.gz`,
or `--version <v>` for `remediate-smoke-<v>.tar.gz`), so no git checkout or
credentials are needed. It installs its own SSH key on the management servers
and KVM hosts, waits for the zone, works out the `lab` section from the KVM
clusters, writes `env.yaml`, runs `lab -prepare`, then `smoke`. Results are in
`/marvin/remediate/results/latest/` on the Marvin VM. Options and the bundle
build commands are in the script's header. With `kvm_clusters`:

```
env_name=remediate env_dotted_version=4.22.1.0 mgmt_os=<ol9 code> hvtype=k hv=5 kvm_clusters=<ol9 code>:2:p1-el,<u24 code>:1:p1-ubuntu,<debian12 code>:1:p1-debian,<suse15 code>:1:p1-suse pri=1 sec=1 env_accounts=all build_marvin=yes post_deploy_script=remediate-smoke-setup.sh post_deploy_wait=yes
```

### Product profiles (`products/<product>.yml`)

A profile fixes everything a product's test lab needs, so the job takes one
choice instead of a dozen settings. Jenkins passes it last, after the job's own
extra vars, so its values win over the job's parameters; the environment name
and CloudStack version still come from the job:

```
PRODUCT_OPTS=""
[ -n "$PRODUCT" ] && [ "$PRODUCT" != "none" ] && PRODUCT_OPTS="--extra-vars @products/${PRODUCT}.yml"
ansible-playbook generate-cloudconfig.yml -i localhost --extra-vars '<job vars>' $PRODUCT_OPTS
ansible-playbook deployvms.yml -i ./hosts_<env> --extra-vars '<job vars>' $PRODUCT_OPTS
```

`generate-cloudconfig.yml` refuses a profile that still has `CHANGEME` values,
and a build where `product` is set but the profile was not passed last (a job
value overriding one of the profile's).

+ `products/remediate.yml`: the remediate apply-smoke lab (`kvm_clusters` with
  OL9 x2, Ubuntu 24.04, Debian 12 and openSUSE Leap 15.6, the Marvin VM, and
  `remediate-smoke-setup.sh` run at the end of the build).

#### Some example --extra-args:

* `env_name=ccs-xs-13-patest env_version=cs45 mgmt=1 hvtype=x hv=2 xs_ver=xs65sp1 env_accounts=all pri=1 build_marvin=true mgmt_os=6`
* `env_name=cs49-vmw55-pga env_version=cs49 mgmt_os=6 hvtype=v vmware_ver=55u3 hv=2 pri=2 env_accounts=all build_marvin=true wait_till_setup=yes baseurl_cloudstack=http://10.2.0.4/shapeblue/cloudstack/testing/`
* `env_name=cs49-kvm6-pga env_version=cs49 mgmt_os=6 env_accounts=all hvtype=k kvm_os=6 hv=2 pri=2 env_accounts=all build_marvin=true wait_till_setup=yes baseurl_cloudstack=http://10.2.0.4/shapeblue/cloudstack/testing/`
