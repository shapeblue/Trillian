#!/bin/bash

counter=1
for file in $1/template/tmpl/1/5/*.vhd; do
 if [[ $((counter)) -gt 1 ]; then
    rm -f $file
 fi
 counter=$((counter+1))
done
