# Trillian - Build Nested CloudStack Environments

More detailed information can be found in the [Wiki](https://github.com/shapeblue/Trillian/wiki)


#### Trillian makes use a 'parent' CloudStack' environment which is used to build virtualised nested environments.

Trillian leverages ESXi's ability to virtualise the VT-x features allowing the creation of VT-x enabled virtualised hosts

#### Trillian uses Ansible 2 to create environment configuration files and deploy those environments. The user can run 2 commandline statements and go from 0 to a running cloudstack environment with multiple hosts. 

#### Installation using pyenv

Trillian uses [pyenv](https://github.com/yyuu/pyenv) and [pyenv-virutalenv](https://github.com/yyuu/pyenv-virtualenv) to install and manage the Python and dependency versions (e.g. Ansible, pysphere, etc) in an isolated Python environment.  This approach not only ensures that Trillian functions as expected, it also ensures that it does not conflict with any other Python applications on the system.  These instructions require pyenv and pyenv-virtualenv are already installed on your system.  If you do not already have pyenv installed, please see the [pyenv installation instructions](https://github.com/yyuu/pyenv-virtualenv) and [pyenv-virtualenv](https://github.com/yyuu/pyenv-virtualenv#installation) for more information about the installation process.  Following pyenv and pyenv-virtualenv installation and configuration, execute the ``configure.sh`` script in the root of the project.  This script will ensure that the expected version of Python is installed, create a ``trillian`` virtualenv, and install the required dependencies using pip.

#### Installation without pyenv

If you are unable to use pyenv and pyenv-virtualenv, you will need to install Python version 2.7.11 and pip per the instructions for your operating system.  Executing ``pip install -r requirements.txt`` in the root of this project will trigger pip to install the dependencies required by Trillian.

#### Environment Configuration

 Basic variables:
   env_name [mandatory]: Environment name, single string, characters, numbers, underscore _ or dash - only.
   env_version [mandatory]: Environment CloudStack version (cs45, cs46, cs49, custom, etc).
   mgmt_os [mandatory]: Management server OS (6, 7, u, custom)
   hvtype [mandatory]: XenServer (x), KVM (k) or VMware (v)
   hv: number of hypervisors. Please note if hypervisor type is VMware the assumption is made that a single VC host is also required.                            This does not have to be specified anywhere.
   pri [mandatory]: number of primary storage pools.
   
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



 Advanced variables [all optional]:
   mgmt: Number of management servers to configure (default is 1)
   sec: number of secondary storage pools. (default is 1)
   db: Number of database servers to configure (default is 0 - db is on mgmt host)
   management_network: name of the management network
   guest_public_network: name of the guest+public network
   management_vm_hypervisor: parent CloudStack cloud hypervisor (default VMware)
   build_project: project name to use for the nested cloudstack build (default <accountname>-NestedClouds)
   build_zone: parent cloud zone name
   build_keyboard: keyboard used for nested VMs (default UK)
   mgmtsrv_service_offering: parent cloud service offering used for the management server build
   mgmtsrv_template: parent cloud template used for the management server build
   dbsrv_service_offering: parent cloud service offering used for database server build
   dbsrv_template: parent cloud template used for database server build
   kvm_service_offering: parent cloud nested KVM instances service offering
   kvm_template: parent cloud nested KVM HV template
   xs_service_offering: parent cloud nested XenServer instances service offering
   xs_template: parent cloud nested XenServer HV template
   esxi_service_offering: parent cloud nested ESXi instances service offering
   esxi_template: parent cloud nested ESXi HV template
   vc_service_offering: parent cloud nested VC instances service offering
   vc_template: parent cloud nested VirtualCentre template
   baseurl_cloudstack: URL for CloudStack build repository
   env_db_name: environments database name
   env_db_ip: environments database IP address
   env_db_user: environments database username
   env_db_password: environments database password
   env_zonetype: basic or advanced (default)
   env_prihost: primary storage host fqdn or IP address
   env_sechost: secondary storage host fqdn or IP address
   env_zone_systemplate: URL to system template, overrides version variable
   build_marvin: whether or not to build a marvin vm for testing purposes (default is false)
   wait_till_setup: only return once system VMs are running. (default is no)


 Some example --extra-args:

 "env_name=ccs-xs-13-patest env_version=cs45 mgmt=1 hvtype=x hv=2 xs_ver=xs65sp1 env_accounts=all pri=1 build_marvin=true mgmt_os=6"
 "env_name=cs49-vmw55-pga env_version=cs49 mgmt_os=6 hvtype=v vmware_ver=55u3 hv=2 pri=2 env_accounts=all build_marvin=true wait_till_setup=yes baseurl_cloudstack=http://10.2.0.4/shapeblue/cloudstack/testing/"
 "env_name=cs49-kvm6-pga env_version=cs49 mgmt_os=6 env_accounts=all hvtype=k kvm_os=6 hv=2 pri=2 env_accounts=all build_marvin=true wait_till_setup=yes baseurl_cloudstack=http://10.2.0.4/shapeblue/cloudstack/testing/"
