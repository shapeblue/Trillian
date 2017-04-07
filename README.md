# Trillian - Build Nested CloudStack Environments

More detailed information can be found in the [Wiki](https://github.com/shapeblue/Trillian/wiki)

#### Trillian makes use a 'parent' CloudStack' environment which is used to build virtualised nested environments.

Trillian leverages ESXi's ability to virtualise the VT-x features allowing the creation of VT-x enabled virtualised hosts

#### Trillian uses Ansible 2 to create environment configuration files and deploy those environments. The user can run 2 commandline statements and go from 0 to a running cloudstack environment with multiple hosts. 

```
ansible-playbook generate-cloudconfig.yml --extra-vars 'env_name=trillian-test-env env_comment='\''example nested cloudstack test environment'\''  use_shared_storage=true env_version=cs410 mgmt=1 db=0 hvtype=k  kvm_os=7 hv=2 env_accounts=all pri=2 sec=1 esxi_use_dvswitch=no build_marvin=yes wait_till_setup=yes wait_for_template=yes mgmt_os=7' -i localhost
```
at the end of this the sugestion, `You can now run: ansible-playbook deployvms.yml -i ./hosts_trillian-test-env`, is put on the output, which would trigger you to run something like
```
ansible-playbook deployvms.yml -i ./hosts_trillian-test-env --extra-vars 'env_name=trillian-test-env env_version=cs410'
```

for more examples see the [Wiki](https://github.com/shapeblue/Trillian/wiki)

 Basic variables:
 +   `env_name` [mandatory]: Environment name, single string, characters, numbers, underscore _ or dash - only.
 +   `env_version` [mandatory]: Environment CloudStack version (cs45, cs46, cs49, custom, etc).
 +   `mgmt_os` [mandatory]: Management server OS (6, 7, u, custom)
 +   `hvtype` [mandatory]: XenServer (x), KVM (k) or VMware (v)
 +   `hv`: number of hypervisors. Please note if hypervisor type is VMware the assumption is made that a single VC host is also required.                            This does not have to be specified anywhere.
 +   `pri` [mandatory]: number of primary storage pools.
   
 Required depending on Hypervisor
 kvm_os:
 -	6 = centos6.8
 -	7 = centos7.1
 -	u = ubuntu14.04
 xs_ver:
 -	xs62sp1
 -	xs65sp1
 vmware_ver:
 -	55u3
 -	60u1

 When not used they will default to 'custom' to avoid template issues

 If you specify KVM as hypervisor  (hvtype=k) you must specify the kvm_os OR set it to custom and set the template to use (kvm_template) in the extra vars (kvm_template="Ubuntu Server 14.04")
 The same applies to the other hypervisor types. For custom VMware you would need to specify both the vCenter and ESXi templates#



 Advanced variables [all optional]`:
 +   `mgmt`: Number of management servers to configure (default is 1)
 +   `sec`: number of secondary storage pools. (default is 1)
 +   `db`: Number of database servers to configure (default is 0 - db is on mgmt host)
 +   `management_network`: name of the management network
 +   `guest_public_network`: name of the guest+public network
 +   `management_vm_hypervisor`: parent CloudStack cloud hypervisor (default VMware)
 +   `build_project`: project name to use for the nested cloudstack build (default <accountname>-NestedClouds)
 +   `build_zone`: parent cloud zone name
 +   `build_keyboard`: keyboard used for nested VMs (default UK)
 +   `mgmtsrv_service_offering`: parent cloud service offering used for the management server build
 +   `mgmtsrv_template`: parent cloud template used for the management server build
 +   `dbsrv_service_offering`: parent cloud service offering used for database server build
 +   `dbsrv_template`: parent cloud template used for database server build
 +   `kvm_service_offering`: parent cloud nested KVM instances service offering
 +   `kvm_template`: parent cloud nested KVM HV template
 +   `xs_service_offering`: parent cloud nested XenServer instances service offering
 +   `xs_template`: parent cloud nested XenServer HV template
 +   `esxi_service_offering`: parent cloud nested ESXi instances service offering
 +   `esxi_template`: parent cloud nested ESXi HV template
 +   `vc_service_offering`: parent cloud nested VC instances service offering
 +   `vc_template`: parent cloud nested VirtualCentre template
 +   `baseurl_cloudstack`: URL for CloudStack build repository
 +   `env_db_name`: environments database name
 +   `env_db_ip`: environments database IP address
 +   `env_db_user`: environments database username
 +   `env_db_password`: environments database password
 +   `env_zonetype`: basic or advanced (default)
 +   `env_prihost`: primary storage host fqdn or IP address
 +   `env_sechost`: secondary storage host fqdn or IP address
 +   `env_zone_systemplate`: URL to system template, overrides version variable
 +   `build_marvin`: whether or not to build a marvin vm for testing purposes (default is false)
 +   `wait_till_setup`: only return once system VMs are running. (default is no)


 Some example --extra-args`:

  * `env_name=ccs-xs-13-patest env_version=cs45 mgmt=1 hvtype=x hv=2 xs_ver=xs65sp1 env_accounts=all pri=1 build_marvin=true mgmt_os=6`
  * `env_name=cs49-vmw55-pga env_version=cs49 mgmt_os=6 hvtype=v vmware_ver=55u3 hv=2 pri=2 env_accounts=all build_marvin=true wait_till_setup=yes baseurl_cloudstack=http`://10.2.0.4/shapeblue/cloudstack/testing/`
  * `env_name=cs49-kvm6-pga env_version=cs49 mgmt_os=6 env_accounts=all hvtype=k kvm_os=6 hv=2 pri=2 env_accounts=all build_marvin=true wait_till_setup=yes baseurl_cloudstack=http://10.2.0.4/shapeblue/cloudstack/testing/`
