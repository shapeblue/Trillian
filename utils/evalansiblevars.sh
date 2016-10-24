#!/bin/bash
# Evaluates Ansible template files againsts variable files
# First arg is the template file

IFS=$'\n';
for i in `grep -ho '{{[^}]*}}' $1 | sort | uniq`;
do
  #foundvar="";
  #tmplvarname=`echo ${i} | sed 's/{*//' | sed 's/}*//' | sed 's/^\ *//' | sed 's/\ *$//'`;
  #foundvar=`grep -hi ^${tmplvarname} $2`;
  #if [ -z ${foundvar} ];
  #then
  #    foundvar="NOTFOUND";
  #fi
  #echo "${tmplvarname} matches: ${foundvar}";
  cleanvarname=`echo ${i} | sed 's/{*//' | sed 's/}*//' | sed 's/^\ *//' | sed 's/\ *$//'`;
  ansible -m debug -a "var=${cleanvarname}" -i $2 $3;
done
