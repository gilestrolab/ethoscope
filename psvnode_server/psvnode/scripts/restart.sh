#!/bin/bash
sleep 2
kill -INT $1
sleep 2
python2 ./server.py -d -p 8000