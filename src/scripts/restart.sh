#!/bin/bash
PID=${args[0]}
$echo->$PID
kill -INT $PID
wait
python2 device_server.py -d