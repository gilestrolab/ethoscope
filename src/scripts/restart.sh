#!/bin/bash
PID=${args[0]}
kill -15 $PID
wait
python2 device_server.py -d