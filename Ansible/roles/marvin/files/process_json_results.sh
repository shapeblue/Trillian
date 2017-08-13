#!/bin/bash

#ARG
CFG_FILE="./trl-830-v-cs410-pangus-advanced-cfg"
TEST_DATA_FILE="test_data.py"
EXTRA_ENV_DATA_FILE=$3


# ----  Create testrun uuid
TESTRUN_UUID=$(uuidgen -r)


# ----  Inject UUID into test results
for file in /marvin/MarvinLogs/test_*.py.json; do
  cat $file | jq 'del(.stats)' | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./$file.processed
done


# ----  Inject UUID into cfg data
cat $CFG_FILE | jq . | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./$CFG_FILE.processed


# ---- Redact sensitive data
sed 's/\"password\": \".*\"/\"password\": \"------"/g' $CFG_FILE > ./env_cfg_file.json
sed -i 's/\"passwd\": \".*\"/\"passwd\": \"------"/g' ./env_cfg_file.json
sed -i 's/\"username\": \".*\"/\"username\": \"------"/g' ./env_cfg_file.json
sed -i 's/\"mgtSvrIp\": \".*\"/\"mgtSvrIp\": \"------"/g' ./env_cfg_file.json


# ---- Clean comments out of test_data
sed 's/#.*//g' $TEST_DATA_FILE | sed '/^$/d'  > ./test_data_file.clean


# ----  Inject UUID into cfg data
cat ./test_data_file.clean | jq . | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./test_data_file.json


# ----  Inject UUID into cfg data
cat ./additional_test_data.json | jq . | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./additional_test_data.json
# ---- get additional data for cfg data

cloudmonkey set display json
HV=$(cloudmonkey list hosts | jq -r '.host[] | .hypervisor //empty' | head -1)
HV_JSON=`cat ./additional_test_data.json | jq -r '.marvin_hypervisor''`

if [[ "$HV" == "$HV_JSON" ]]; then
  HV_VER=$(cloudmonkey list hosts | jq -r '.host[] | .hypervisorversion //empty' | head -1)
  sed -i 's/\"hypervisor_version\": \".*\"/\"hypervisor_version\": \"$HV_VER"/g' ./additional_test_data.json

fi



#zip -ur existing.zip myFolder

done
