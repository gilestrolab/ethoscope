#!/usr/bin/env bash



GIT_REPO="/home/quentin/comput/ethoscope-git/"
SERVER_SCRIPT="../../../scripts/device_server.py"

#config_file=test_generic_config.json
#config_file="test_sleep_monit_arena.json"
config_file="test_fake_sleep_dep.json"

python $SERVER_SCRIPT -g $GIT_REPO -j $config_file -r

