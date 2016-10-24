#!/bin/bash
# Evaluates Ansible template files againsts variable files
# $1 is the template file
# $2 is the ansible hostfile
# $3 is the ansible hostname
IFS=$'\n';
echo -e "\nVariable file: $1";
echo -e "Host file:     $2";
echo -e "Host:          $3\n\n";

for i in `grep -ho '{{[^}]*}}' $1 | sort | uniq`;
do
  cleanvarname=`echo ${i} | sed 's/{*//' | sed 's/}}//' | sed 's/^\ *//' | sed 's/\ *$//' | sed 's/|\ lower//'`;
  ansible -m debug -a "var=${cleanvarname}" -i $2 $3 | awk 'NR==2';
done
