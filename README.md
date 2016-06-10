# Trillian - Build Nested CloudStack Environments

More detailed information can be found in the [Wiki](https://github.com/shapeblue/Trillian/wiki)

#### Trillian makes use a 'parent' CloudStack' environment which is used to build virtualised nested environments.

Trillian leverages ESXi's ability to virtualise the VT-x features allowing the creation of VT-x enabled virtualised hosts

#### Trillian uses Ansible 2 to create environment configuration files and deploy those environments. The user can run 2 commandline statements and go from 0 to a running cloudstack environment with multiple hosts. 



```bash
ansible-playbook generate-cloudconfig.yml --extra-vars "env_name=xs62test mgmt_os=6 env_version=cs45 env_accounts=all hvtype=x hv=2 pri=2 xs_template='XenServer 6.2 SP1'" -i localhost
ansible-playbook deployvms.yml -i ./hosts_xs62test
ansible-playbook destroyvms.yml -i ./hosts_xs62test -e "expunge=true removeproject=true removeconfig=true"

generate-config "env_name=kvmtest-pga mgmt_os=6 env_version=cs45 env_accounts=all hvtype=k hv=2 pri=2"

generate-config "env_name=esxi55test mgmt_os=7 env_version=cs45 env_accounts=all hvtype=v hv=2 pri=2 vc_template='vCenter55u3' esxi_template='ESXi 5.5 U3'"
````

Ultimately a wrapper will run these steps & then run specified Marvin tests against these environments
Initially Jenkins post build tasks will run the individual steps.

The full list of variables are as follows:
* env_name [mandatory]: Environment name, single string, characters, numbers, underscore _ or dash - only. Required for all playbook * runs and distinguishes the nested clouds from each other.
* env_version [mandatory]: Environment CloudStack version (cs45, cs46, custom, etc)- see group_vars/all for options
* hvtype [mandatory]: XenServer (x), KVM (k) or VMware (v)
* mgmt_os [mandatory]: Management server OS (centos, centos7, ubuntu, custom)
* pri [mandatory]: number of primary storage pools.

Optional:
* mgmt: Number of management servers to configure (default = 1)
* db: Number of independent MySQL servers configure (default = 0 ie MySQL on mgmt server)
* hv: number of hypervisors. Please note if hypervisor type is VMware the assumption is made that a single VC host is also required. This does not have to be specified anywhere.
* management_network: name of the management network
* guest_public_network: name of the guest+public network
* management_vm_hypervisor: parent CloudStack cloud hypervisor (default VMware)
* build_project: project name to use for the nested cloudstack build (default <accountname>-NestedClouds)
* build_zone: parent cloud zone name
* build_keyboard: keyboard used for nested VMs (default UK)
* mgmtsrv_service_offering: parent cloud service offering used for the management server build
* mgmtsrv_template: parent cloud template used for the management server build
* dbsrv_service_offering: parent cloud service offering used for database server build
* dbsrv_template: parent cloud template used for database server build
* kvm_service_offering: parent cloud nested KVM instances service offering
* kvm_template: parent cloud nested KVM HV template
* xs_service_offering: parent cloud nested XenServer instances service offering
* xs_template: parent cloud nested XenServer HV template
* esxi_service_offering: parent cloud nested ESXi instances service offering
* esxi_template: parent cloud nested ESXi HV template
* vc_service_offering: parent cloud nested VC instances service offering
* vc_template: parent cloud nested VirtualCentre template
* baseurl_cloudstack: URL for CloudStack build repository
* env_id: override value to re-use a specific environment in the env database
* env_zonetype: basic or advanced (default)
* env_zone_systemplate: URL to system template, overrides version variable
* build_marvin: whether or not to build a marvin vm for testing purposes (default is false)
