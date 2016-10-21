#!/bin/bash
# Evaluates Ansible template files againsts variable files
# First arg is the template file

IFS=$'\n';
for i in `grep -ho '{{[a-zA-Z \-\_]*}}' $1 | sort | uniq`;
do
  tmplvarname=`echo ${i} | sed 's/{{//' | sed 's/}}//' | sed 's/^\ *//' | sed 's/\ *$//'`;
  foundvar=`grep -hi ${tmplvarname} $2 | grep -v 'def_'`;
  echo "${tmplvarname} matches: ${foundvar}";
done
