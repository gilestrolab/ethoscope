#!/bin/bash
kill -INT $1
wait
python2 ./device_server.py -d