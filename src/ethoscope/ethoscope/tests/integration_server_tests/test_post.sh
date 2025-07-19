#!/usr/bin/env bash

ID=$(cat /etc/machine-id)


start="http://localhost:9000/controls/$ID/start"
stop="http://localhost:9000/controls/$ID/stop"
close="http://localhost:9000/controls/$ID/close"
JSON_FILE=./test_generic_config.json
SERVER_SCRIPT="../../../scripts/device_server.py"

tmp=$(mktemp)


failed(){
    echo "ERROR!"
    rm $tmp
    kill $daemon_pid
    exit 1

    }


echo "Starting daemon in background"
python $SERVER_SCRIPT -j $JSON_FILE  -D  > /dev/null&
daemon_pid=$!
echo "Wait 5s"
sleep 5
echo "tmp file is saved at $tmp"

for i in $(seq 1 2)
    do
    echo "Checking tracking is stopped"
    curl http://localhost:9000/data/$ID -s > $tmp
    if python check_field.py $tmp  status stopped; then
        echo "OK"
    else
        failed

    fi

    echo "Starting tracking with $JSON_FILE"

    curl -XPOST\
         -H 'Content-Type:application/json'\
         -H 'Accept: application/json'\
         --data-binary @$JSON_FILE\
         $start -s > $tmp


    echo "Checking tracking is initialising"
    curl http://localhost:9000/data/$ID -s > $tmp
    if python check_field.py $tmp  status initialising; then
        echo "OK"
    else
        failed
    fi

    echo "Sleeping 10s"
    sleep 10

    echo "Checking tracking is running"
    curl http://localhost:9000/data/$ID -s > $tmp
    if python check_field.py $tmp  status running; then
        echo "OK"
    else
        failed
    fi


    echo "Stopping tracking with $JSON_FILE"

    curl -XPOST\
         -H 'Content-Type:application/json'\
         -H 'Accept: application/json'\
         --data-binary @$JSON_FILE\
         $stop -s > $tmp

    echo "Checking tracking is stopped"
    curl http://localhost:9000/data/$ID -s > $tmp
    if python check_field.py $tmp  status stopped; then
        echo "OK"
    else
        failed
    fi
done

echo "Test weather program can be closed"
curl -XPOST\
     -H 'Content-Type:application/json'\
     -H 'Accept: application/json'\
     --data-binary @$JSON_FILE\
     $close -s > $tmp

echo "Waiting for daemon to finish"

wait
