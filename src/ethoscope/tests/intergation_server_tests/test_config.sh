#!/usr/bin/env bash

set -e # stop if any error happens


GIT_REPO="/home/quentin/comput/ethoscope-git/"
SERVER_SCRIPT="../../../scripts/device_server.py"

#config_file=test_generic_config.json
#config_file="test_sleep_monit_arena.json"

for config_file in $(ls test_*.json)
do
echo "TESTING $config_file"
time python $SERVER_SCRIPT -j $config_file -r -D -s
done

echo "all test successful (by some miracle)!"



