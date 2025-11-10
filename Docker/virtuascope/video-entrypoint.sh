#!/bin/bash

# Default video URL (can be overridden with environment variable)
VIDEO_URL=${VIDEO_URL:-"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
DEVICE=${VIRTUAL_DEVICE:-"/dev/video10"}
LOOP=${LOOP:-"true"}

echo "Setting up virtual video device: $DEVICE"
echo "Streaming from: $VIDEO_URL"

# Check if virtual device exists (should be created by host)
if [ ! -e "$DEVICE" ]; then
    echo "ERROR: Virtual device $DEVICE not found!"
    echo "Please create it on the host system first:"
    echo "  sudo modprobe v4l2loopback video_nr=10 card_label=\"Virtual Ethoscope Camera\""
    echo "Or if v4l2loopback needs rebuilding:"
    echo "  sudo dkms install v4l2loopback/0.13.2 -k \$(uname -r)"
    exit 1
fi

echo "Virtual device $DEVICE found, proceeding with stream..."
sleep 2

# Determine loop parameters
if [[ "${LOOP,,}" == "true" ]]; then
    LOOP_PARAM="-stream_loop -1"
    echo "Starting looping video stream..."
else
    LOOP_PARAM=""
    echo "Starting single-play video stream..."
fi

# Stream video to virtual device
ffmpeg $LOOP_PARAM -re -i "$VIDEO_URL" \
    -vf "scale=640:480" \
    -f v4l2 \
    -pix_fmt yuv420p \
    "$DEVICE" \
    -loglevel warning

echo "Video streaming ended"
