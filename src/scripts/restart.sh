#!/bin/bash
sleep 2
kill -INT $1
sleep 1
python2 ./device_server.py -d