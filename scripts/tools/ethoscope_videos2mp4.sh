#!/bin/bash
set -e
cd $1
echo "moving to $(pwd)"

TMP_FILE=chunks.tmp
echo "Merging $(ls *.h264 | wc -l) h264 chunks in tmp file"
cat  *.h264  > $TMP_FILE
fps=$(ls *.h264 | head -n 1 | cut -d _ -f 5 | cut -d @ -f 2)
prefix="whole_$(ls *.h264 | head -n 1 | cut -d . -f 1)"
echo "Using ffmpeg to create $(pwd)/$prefix.mp4"
ffmpeg -r $fps -i $TMP_FILE  -vcodec copy -y  $prefix.mp4  -loglevel panic
rm $TMP_FILE

