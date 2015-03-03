PID = $1
kill -SIGINT $PID
wait $PID
python2 device_server.py -d