#!/bin/sh
mplayer -vf screenshot -tv driver=v4l2:gain=1:width=960:height=720:device=/dev/video0:fps=10:outfmt=rgb16 tv://
