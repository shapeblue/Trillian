#!/bin/bash

#ARG (static for testing).
CFG_FILE="./trl-838-v-cs410-pangus-advanced-cfg"
TEST_DATA_FILE="./test_data.py"
EXTRA_ENV_DATA_FILE="./additional_test_data.json"
TMP_ENV_DATA_FILE="./additional_test_data.out"

# ----  Create testrun uuid
TESTRUN_UUID=$(uuidgen -r)


echo " -- Inject UUID into test results"
for file in ./test_*.py.json; do
  cat $file | jq 'del(.stats)' | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./$file.processed
  rm -f $file
  mv ./$file.processed $file
done


echo "  --  Inject UUID into cfg data"
cat $CFG_FILE | jq . | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./$CFG_FILE.uuid


echo " -- Redact sensitive data (TODO - 	convert to function)."
sed 's/\"password\": \".*\"/\"password\": \"------"/g' ./$CFG_FILE.uuid > ./env_cfg_file.json
sed -i 's/\"passwd\": \".*\"/\"passwd\": \"------"/g' ./env_cfg_file.json
sed -i 's/\"username\": \".*\"/\"username\": \"------"/g' ./env_cfg_file.json
sed -i 's/\"mgtSvrIp\": \".*\"/\"mgtSvrIp\": \"------"/g' ./env_cfg_file.json
sed -i 's/\"user\": \".*\"/\"user\": \"------"/g' ./env_cfg_file.json
rm -f ./$CFG_FILE.uuid
rm -f $CFG_FILE

echo " -- Clean comments out of test_data"
sed  's/#.*//g' $TEST_DATA_FILE | sed '/^$/d' | sed 's/test_data = {/{/g' > ./test_data_file.clean
rm -f $TEST_DATA_FILE

echo " -- Inject UUID into test cfg data"
cat ./test_data_file.clean | jq . | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > ./test_data_file.json
rm -f ./test_data_file.clean


echo " -- Inject UUID into env cfg data"
cat $EXTRA_ENV_DATA_FILE | jq . | jq --arg testrunuuid $TESTRUN_UUID '. + {testrun_uuid: $testrunuuid}' > $TMP_ENV_DATA_FILE


echo " -- get additional data for env cfg data"
## TODO - Make more intelligent to pick out correct HV type (in case of mulitple hypervisor types) not just pick from first one in the list
cloudmonkey set display json
export TERM=vt100
HV=$(cloudmonkey list hosts | jq -r '.host[] | .hypervisor //empty' | head -1)
HV_JSON=`cat $TMP_ENV_DATA_FILE | jq -r '.marvin_hypervisor'`

if [[ "${HV,,}" == "${HV_JSON,,}" ]]; then
  HV_VER=$(cloudmonkey list hosts | jq -r '.host[] | .hypervisorversion //empty' | head -1)
  sed -i "s/\"hypervisor_version\": \".*\"/\"hypervisor_version\": \"$HV_VER\"/g" $TMP_ENV_DATA_FILE
fi
rm -f $EXTRA_ENV_DATA_FILE
mv $TMP_ENV_DATA_FILE $EXTRA_ENV_DATA_FILE
#zip -ur existing.zip myFolder

