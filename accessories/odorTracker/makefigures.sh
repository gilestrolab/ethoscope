#!/bin/bash

SRC=$1
PVGROOT="/home/gg/Dropbox/myCode/pySolo-Video/"


PVG_OT=$PVGROOT"accessories/odorTracker/odorTracker.py --distribution --path -i"
FILETYPE_OT="*.txt"

for file in `find ${SRC} -name "$FILETYPE_OT" -type f`
do
    echo ${file}
    python2 ${PVG_OT} ${file}
done
