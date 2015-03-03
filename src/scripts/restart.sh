#!/bin/bash
PID = ${args[0]}
kill -SIGINT $PID
wait
python2 device_server.py -d