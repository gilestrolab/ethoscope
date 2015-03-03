#!/bin/bash
echo $1
kill -INT $1
sleep 5
python2 ./device_server.py -d