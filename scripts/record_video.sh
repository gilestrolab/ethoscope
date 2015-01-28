#!/bin/sh
#$1 is eg `test.avi`
fps=5
/opt/vc/bin/raspivid  -o $1  -w 720 -h 540 -fps $fps  -e
ffmpeg -r 5 -i $1 -vcodec copy  tmp_$1 && mv tmp_$1 $1



