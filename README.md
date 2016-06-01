# Trillian - Build Nested CloudStack Environments

More detailed information can be found in the [Wiki](https://github.com/shapeblue/Trillian/wiki)

#### Trillian makes use a 'parent' CloudStack' environment which is used to build virtualised nested environments.

Trillian leverages ESXi's ability to virtualise the VT-x features allowing the creation of VT-x enabled virtualised hosts

#### Trillian uses Ansible 2 to create environment configuration files and deploy those environments. The user can run 2 commandline statements and go from 0 to a running cloudstack environment with multiple hosts. 



```bash
ansible-playbook generate-cloudconfig.yml --extra-vars "env_name=vsphere55-test mgmt=1 db=0 hvtype=v hv=2 esxi_template='ESXi 5.5 U3' vc_template='vCenter 5.5 U3' env_accounts=all pri=1 sec=1" -i localhost
ansible-playbook deployvms.yml -i ./hosts_vsphere55-test

ansible-playbook generate-cloudconfig.yml --extra-vars "env_name=xs65pga mgmt=1 db=0 hvtype=x hv=2 xenserver_template='XenServer 6.5 SP1' env_accounts=all pri=1 sec=1" -i localhost
ansible-playbook deployvms.yml -i ./hosts_xs65pga

ansible-playbook generate-cloudconfig.yml --extra-vars "env_name=kvmtest mgmt=1 db=0 hvtype=k hv=2 kvm_template='KVM CentOS 6.7' env_accounts=all pri=1 sec=1" -i localhost
ansible-playbook deployvms.yml -i ./hosts_kvmtest

````

Ultimately a wrapper will run these steps & then run specified Marvin tests against these environments
Initially Jenkins post build tasks will run the individual

The full list of variables are as follows:
* env_name [mandatory]: Environment name, single string, characters, numbers, underscore _ or dash - only. Required for all playbook * runs and distinguishes the nested clouds from each other.
* mgmt [optional]: Number of management servers to configure
* db [optional]: Number of database servers to configure
* hvtype [mandatory]: XenServer (x), KVM (k) or VMware (v)
* hv [optional]: number of hypervisors. Please note if hypervisor type is VMware the assumption is made that a single VC host is also required. This does not have to be specified anywhere.
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
* env_db_name: environments database name
* env_db_ip: environments database IP address
* env_db_user: environments database username
* env_db_password: environments database password
* env_id: override value to re-use a specific environment in the env database
* env_zonetype: basic or advanced (default)

