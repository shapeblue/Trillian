#!/bin/bash


ES_IP="10.4.0.15"
RESULTS_INDEX="test_results"
ENV_TEST_DATA="./test_run.json"
JSON_OUTPUT_DIR="/marvin/json_results"
TESTRUN_INDEX="test_runs"
metafile="$JSON_OUTPUT_DIR/additional_test_data.json"

cd /marvin

echo " -- Upload test results -- "
for file in $JSON_OUTPUT_DIR/*.json; do
  if [[ "$(basename $file)" != "additional_test_data.json" ]] && [[ "$(basename $file)" != "env_cfg_file.json" ]]; then
    echo " Uploading $(basename $file)"
    curl -XPOST "$ES_IP:9200/$RESULTS_INDEX/external?pretty" -d @$file
  fi
done


echo " -- Upload test metadata"
curl -XPOST "$ES_IP:9200/$TESTRUN_INDEX/external?pretty" -d @$metafile

