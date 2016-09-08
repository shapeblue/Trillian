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


echo "Writing bash script for next boot (first boot after templating)"

cat << "EOF"  > /etc/rc.d/init.d/firstnestedboot.sh
#!/bin/bash

touch /tmp/state-firstboot-started
echo "First nested boot script started"
xe host-management-disable

echo "Removing old NICs"
OLDHOSTUUID=`xe host-list --minimal`
echo $OLDHOSTUUID > /tmp/oldhostuuid
echo `xe pif-list device=eth0 --minimal` > /tmp/oldeth0pif
echo `xe pif-list device=eth1 --minimal` > /tmp/oldeth1pif
xe pif-forget uuid=`cat /tmp/oldeth0pif` uuid=`cat /tmp/oldeth1pif` uuid=`cat /tmp/oldeth2pif` force=true

echo "Removing old SRs"

IFS=',' read -a array <<< "`xe sr-list --minimal`"
for (( i = 0; i < ${#array[@]}; i++ )); do
  echo "${array[$i]}"
  xe pbd-unplug uuid=`xe sr-list uuid="${array[$i]}" params=PBDs --minimal`
  xe sr-forget uuid="${array[$i]}"
done;

echo "Generating new UUIDs"
NEWHOSTUUID=`uuidgen`
NEWCONTROLUUID=`uuidgen`

echo "Applying new UUIDs"
sed  -i -e "/^INSTALLATION_UUID=/ c\INSTALLATION_UUID='$NEWHOSTUUID'" -i -e "/^CONTROL_DOMAIN_UUID=/ c\CONTROL_DOMAIN_UUID='$NEWCONTROLUUID'"  /etc/xensource-inventory

echo "Clearing xapi"
service xapi stop
rm -rf /var/xapi/

echo "Preparing for next boot"
rm -f /etc/rc3.d/S99nestedfixup
ln -s /etc/rc.d/init.d/secondnestedboot.sh /etc/rc3.d/S99nestedfixup

rm -f /tmp/state-firstboot-started
touch /tmp/state-firstboot-complete

echo "reseting network and rebooting to finalise nested fixup"
echo yes | /opt/xensource/bin/xe-reset-networking --device=eth0 --mode=dhcp
# End of first reboot script

EOF

echo "Writing bash script for second boot (second boot after templating)"

cat << "EOF"  > /etc/rc.d/init.d/secondnestedboot.sh
#!/bin/bash

rm -f /tmp/state-firstboot-complete
touch /tmp/state-secondboot-started

echo "Second nested boot script started"

echo "Applying clean management cfg"
HOSTUUID=`xe host-list --minimal`
xe pif-scan host-uuid=$HOSTUUID
PIFUUID=`xe pif-list device=eth0 --minimal`

xe pif-reconfigure-ip uuid=$PIFUUID mode=DHCP
xe host-management-reconfigure pif-uuid=$PIFUUID
xe host-param-set uuid=$HOSTUUID name-label=`xe host-list params=hostname --minimal`

echo ""
echo "request dhcp address (until one is returned)"
HAVADDR=0
while [[ $HAVADDR -eq 0 ]]
do
  echo ""
  echo "requesting dhcp address"
  dhclient -r && dhclient xenbr0
  ADDR=`ifconfig xenbr0 | grep 'inet addr'`
  if [[ -n "$ADDR" ]]; then HAVADDR=1; fi
done


echo "Creating SRs and templates"
stringZ=`pvdisplay | grep "VG Name"`
localsruuid=${stringZ: 38}
xe sr-create uuid=$localsruuid type=lvm name-label="Local Storage" content-type=user device-config:device=/dev/sda3
/opt/xensource/libexec/create_templates

rm -f /etc/rc3.d/S99nestedfixup
rm -f /tmp/state-secondboot-started
echo "Nested fixup complete"
touch /tmp/state-built

# End of second boot script

EOF


chmod 755 /etc/rc.d/init.d/firstnestedboot.sh
chmod 755 /etc/rc.d/init.d/secondnestedboot.sh

rm -f /etc/rc3.d/S99nestedfixup
ln -s /etc/rc.d/init.d/firstnestedboot.sh /etc/rc3.d/S99nestedfixup

echo "XenServer prepared for templating - shutdown and then template volume."
