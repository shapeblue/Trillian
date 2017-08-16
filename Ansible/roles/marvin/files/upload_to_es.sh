#!/bin/bash


ES_IP="10.4.0.15"
RESULTS_INDEX="test_results"
ENV_EXTRA_DATA="env_extra_data.json"
ENVDATA_INDEX="env_data"
ENV_TEST_DATA="env_test_data.json"

#echo " -- Upload test results"
#for file in ./test_*.json; do
#  curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$file
#done

echo " -- Upload Additional test env data"
curl -XPOST "$ES_IP:9200/$ENVDATA_INDEX/external?pretty" -d @$ENV_EXTRA_DATA

echo " -- Upload Additional test env data"
curl -XPOST "$ES_IP:9200/$ENVDATA_INDEX/external?pretty" -d @$ENV_TEST_DATA
