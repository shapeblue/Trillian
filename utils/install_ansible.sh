#!/bin/bash

#Copyright 2016 ShapeBlue
#
#Licensed under the Apache License, Version 2.0 (the "License");
#you may not use this file except in compliance with the License.
#You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#Unless required by applicable law or agreed to in writing, software
#distributed under the License is distributed on an "AS IS" BASIS,
#WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#See the License for the specific language governing permissions and
#limitations under the License.


yum install -y epel-release wget git libselinux-python
yum install -y python-setuptools jq
yum install -y mysql
yum install -y python-crypto sshpass ansible
easy_install pip
pip install pyvmomi
pip install cs

INVDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/../Ansible && pwd )"
echo "ansible-playbook $INVDIR/generate-cloudconfig.yml -i $INVDIR/localhost --extra-vars \"\$1\"" > /usr/bin/generate-config  && chmod 0755 /usr/bin/generate-config
echo "ansible-playbook $INVDIR/erase-env.yml -i $INVDIR/localhost --extra-vars \"env_name=\$1\"" > /usr/bin/erase-env && chmod 0755 /usr/bin/erase-env
sed -i "/^library  /c\library        = /usr/share/ansible:$INVDIR/library" $INVDIR/ansible.cfg

echo '!/bin/bash

EXTRAVARS=$1
ansible-playbook ./generate-cloudconfig.yml -i ./localhost --extra-vars "$EXTRAVARS"
ENVNAME=`echo ${EXTRAVARS%$env_name=*} | head -n1 | cut -d " " -f1|cut -d "=" -f 2`
ansible-playbook ./deployvms.yml -i ./hosts_"$ENVNAME"
' > /usr/bin/build-env
chmod 0755 /usr/bin/build-env
