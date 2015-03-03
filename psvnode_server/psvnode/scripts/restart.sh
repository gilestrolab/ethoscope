#!/bin/bash
kill -INT $1
wait
python2 ./server.py -d -p 8000