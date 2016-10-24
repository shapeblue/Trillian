#!/bin/bash
# Evaluates Ansible jinja template files againsts variable files.
# Extracts all Ansible variables from the jinja template and
# does an ansible ad-hoc debug against each var individually rather
# than processing all in one go.
# Input:
# $1 is the template file
# $2 is the ansible hostfile
# $3 is the ansible hostname
#
IFS=$'\n';
echo -e "\nTemplate file: $1\nHost file:     $2\nHost:          $3\n";
for i in `grep -ho '{{[^}]*}}' $1 | sort | uniq`;
do
  cleanvarname=`echo ${i} | sed 's/{*//' | sed 's/}}//' | sed 's/^\ *//' | sed 's/\ *$//' | sed 's/|\ lower//'`;
  ansible -m debug -a "var=${cleanvarname}" -i $2 $3 | awk 'NR==2';
done
