#!/bin/bash
PID = $1
kill -SIGINT $PID
wait
python2 device_server.py -d