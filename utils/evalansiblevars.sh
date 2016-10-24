#!/bin/bash
# Evaluates Ansible template files againsts variable files
# $1 is the template file
# $2 is the ansible hostfile
# $3 is the ansible hostname
IFS=$'\n';
for i in `grep -ho '{{[^}]*}}' $1 | sort | uniq`;
do
  cleanvarname=`echo ${i} | sed 's/{*//' | sed 's/}}//' | sed 's/^\ *//' | sed 's/\ *$//' | sed 's/|\ lower//'`;
  ansible -m debug -a "var=${cleanvarname}" -i $2 $3
done
