#!/bin/bash

timeout=20
active="true"
while [[ "$active" == "true" ]]; do
active="false"
echo "Still seeing writes"
if inotifywait -e modify $1/template/tmpl/1/5/ -t $timeout; then active="true" ; fi
done
echo "nothing was written in the directory for $timeout seconds.
removing any extra VHDs"
counter=1
for file in $1/template/tmpl/1/5/*.vhd; do
 if [[ $((counter)) > 1 ]]; then
    rm -f $file
    echo "$file removed"
 fi
 counter=$((counter+1))
done
