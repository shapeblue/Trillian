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
DEPLOYLOG="/tmp/generalise.log"

touch /tmp/state-firstboot-started
echo "First nested boot script started" | tee -i -a ${DEPLOYLOG}
xe host-management-disable

echo "Removing old NICs"
OLDHOSTUUID=""
while [[ -z $OLDHOSTUUID ]]; do
  OLDHOSTUUID=`xe host-list --minimal`
  echo "waiting for xe host-list to return a valid value" | tee -i -a ${DEPLOYLOG}
  sleep 5
done
echo $OLDHOSTUUID > /tmp/oldhostuuid
echo `xe pif-list device=eth0 --minimal` > /tmp/oldeth0pif
echo `xe pif-list device=eth1 --minimal` > /tmp/oldeth1pif
xe pif-forget uuid=`cat /tmp/oldeth0pif` uuid=`cat /tmp/oldeth1pif` uuid=`cat /tmp/oldeth2pif` force=true | tee -i -a ${DEPLOYLOG}

echo "Removing old SRs"  | tee -i -a ${DEPLOYLOG}

IFS=',' read -a array <<< "`xe sr-list --minimal`"
for (( i = 0; i < ${#array[@]}; i++ )); do
  echo "${array[$i]}"  | tee -i -a ${DEPLOYLOG}
  xe pbd-unplug uuid=`xe sr-list uuid="${array[$i]}" params=PBDs --minimal` | tee -i -a ${DEPLOYLOG}
  xe sr-forget uuid="${array[$i]}" | tee -i -a ${DEPLOYLOG}
done;

echo "Generating new UUIDs" | tee -i -a ${DEPLOYLOG}
NEWHOSTUUID=`uuidgen`
NEWCONTROLUUID=`uuidgen`

echo "Applying new UUIDs" | tee -i -a ${DEPLOYLOG}
sed  -i -e "/^INSTALLATION_UUID=/ c\INSTALLATION_UUID='$NEWHOSTUUID'" -i -e "/^CONTROL_DOMAIN_UUID=/ c\CONTROL_DOMAIN_UUID='$NEWCONTROLUUID'"  /etc/xensource-inventory

echo "Clearing xapi" | tee -i -a ${DEPLOYLOG}
service xapi stop
rm -rf /var/xapi/

echo "Preparing for next boot" | tee -i -a ${DEPLOYLOG}

sed  -i "/firstnestedboot/ c\ExecStart=\/etc\/rc.d\/init.d\/secondnestedboot.sh"  /etc/systemd/system/nestedxengeneralise.service

rm -f /tmp/state-firstboot-started
touch /tmp/state-firstboot-complete

echo "reseting network and rebooting to finalise nested fixup"
echo yes | /opt/xensource/bin/xe-reset-networking --device=eth0 --mode=dhcp
# End of first reboot script

EOF

echo "Writing bash script for second boot (second boot after templating)"

cat << "EOF"  > /etc/rc.d/init.d/secondnestedboot.sh
#!/bin/bash
DEPLOYLOG="/tmp/generalise.log"
rm -f /tmp/state-firstboot-complete
touch /tmp/state-secondboot-started

echo "Second nested boot script started"

echo "Applying clean management cfg"
HOSTUUID=""
while [[ -z $HOSTUUID ]]; do
  HOSTUUID=`xe host-list --minimal`
  echo "waiting for xe host-list to return a valid value" | tee -i -a ${DEPLOYLOG}
  sleep 5
done

xe pif-scan host-uuid=$HOSTUUID | tee -i -a ${DEPLOYLOG}
PIFUUID=`xe pif-list device=eth0 --minimal`
ETH0NET=`xe network-list bridge=xenbr0 --minimal` 
xe network-param-set uuid=$ETH0NET MTU=4500 | tee -i -a ${DEPLOYLOG}

xe pif-reconfigure-ip uuid=$PIFUUID mode=DHCP | tee -i -a ${DEPLOYLOG}
xe host-management-reconfigure pif-uuid=$PIFUUID | tee -i -a ${DEPLOYLOG}
xe host-param-set uuid=$HOSTUUID name-label=`xe host-list params=hostname --minimal` | tee -i -a ${DEPLOYLOG}

echo ""
xe-toolstack-restart
echo "waiting for dhcp address" | tee -i -a ${DEPLOYLOG}
HAVADDR=0
while [[ $HAVADDR -eq 0 ]]
do
  echo ""
  echo "requesting dhcp address" | tee -i -a ${DEPLOYLOG}
  ADDR=`ifconfig xenbr0 | grep 'inet'`
  if [[ -n "$ADDR" ]]; then HAVADDR=1;else sleep 5s; fi
done


echo "Creating SRs and templates"
stringZ=`pvdisplay | grep "VG Name"`
localsruuid=${stringZ: 38}
xe sr-create uuid=$localsruuid type=lvm name-label="Local Storage" content-type=user device-config:device=/dev/sda3  | tee -i -a ${DEPLOYLOG}
sleep 10s
/usr/bin/create-guest-templates | tee -i -a ${DEPLOYLOG}

systemctl disable nestedxengeneralise
rm -f /tmp/state-secondboot-started
echo "Nested fixup complete" | tee -i -a ${DEPLOYLOG}
touch /tmp/state-built

# End of second boot script

EOF

# write systemd startup file 
cat << "EOF"  > /etc/systemd/system/nestedxengeneralise.service
[Unit]
After=xapi.service

[Service]
ExecStart=/etc/rc.d/init.d/firstnestedboot.sh

[Install]
WantedBy=default.target

EOF
chmod +x /etc/systemd/system/nestedxengeneralise.service
systemctl enable nestedxengeneralise
chmod +x /etc/rc.d/init.d/firstnestedboot.sh
chmod +x /etc/rc.d/init.d/secondnestedboot.sh


echo "XenServer prepared for templating - shutdown and then template volume."
