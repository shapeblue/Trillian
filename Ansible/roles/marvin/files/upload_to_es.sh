#!/bin/bash


ES_IP="10.4.0.15"
RESULTS_INDEX="test_results"
ENV_TEST_DATA="./test_run.json"
JSON_OUTPUT_DIR="/marvin/json_results"
TESTRUN_INDEX="test_runs"
metafile="$JSON_OUTPUT_DIR/additional_test_data.json"

cd /marvin

echo " -- Upload test results"
for file in $JSON_OUTPUT_DIR/test_*.json; do
curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$file
done


echo " -- Upload test metadata"
curl -XPOST "$ES_IP:9200/$TESTRUN_INDEX/external?pretty" -d @$metafile

