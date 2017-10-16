#!/bin/bash


ES_IP="10.4.0.15"
RESULTS_INDEX="test_results"
ENV_TEST_DATA="./test_run.json"


cd /marvin

echo " -- Upload test results"
curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$ENV_TEST_DATA
