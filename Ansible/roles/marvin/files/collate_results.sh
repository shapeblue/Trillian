#!/bin/bash

RESULTSFILE="/marvin/collated_results.txt"
LOGDIR="/marvin/MarvinLogs"

echo "Collated results from $HOSTNAME

" > $RESULTSFILE
for dir in $LOGDIR/*/; do

rm -f /tmp/tmpres1

sed -e '/=================================/,$d' $dir/results.txt > /tmp/tmpres1
sed -e '/begin captured logging/,$d' /tmp/tmpres1 >> $RESULTSFILE

done
