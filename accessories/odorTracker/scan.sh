#!/bin/bash

SRC=$1
PVGROOT="/home/gg/Dropbox/myCode/pySolo-Video/"

PVG_S=$PVGROOT"pvg_standalone.py -t2 --trackonly -i"
FILETYPE_S="*.avi"

PVG_OT=$PVGROOT"accessories/odorTracker/odorTracker.py --distribution --path -i"
FILETYPE_OT="*.txt"

for file in `find ${SRC} -name "$FILETYPE_S" -type f`
do
    echo ${file}
    python2 ${PVG_S} ${file}
done

for file in `find ${SRC} -name "$FILETYPE_OT" -type f`
do
    echo ${file}
    python2 ${PVG_OT} ${file}
done
