#!/bin/bash


ES_IP="10.4.0.15"
RESULTS_INDEX="test_results"
ENV_TEST_DATA="./test_run.json"
JSON_OUTPUT_DIR="/marvin/json_results"

cd /marvin

echo " -- Upload test results"
for file in $JSON_OUTPUT_DIR/test_*.json; do
curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$file
done