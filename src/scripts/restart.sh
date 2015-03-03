#!/bin/bash
echo $1
kill -INT $1
wait
python2 device_server.py -d