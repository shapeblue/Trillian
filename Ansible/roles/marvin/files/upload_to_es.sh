#!/bin/bash


ES_IP="10.4.0.15"
RESULTS_INDEX="test_results"
ENVDATA_INDEX="env_cfg_file.json"
ENV_TEST_DATA="env_test_data.json"
ENV_EXTRA_DATA="env_extra_data.json"

echo " -- Upload test results"
for file in ./test_*.json; do
  curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$file
done

echo " -- Upload test env cfg"
curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$ENVDATA_INDEX

echo " -- Upload test data used"
curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$ENV_TEST_DATA

echo " -- Upload Additional test env data"
curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$ENV_EXTRA_DATA