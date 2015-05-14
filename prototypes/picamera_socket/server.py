
from picamera.array import PiRGBArray
from picamera import PiCamera
import cv2
import numpy as np
import time
capture = PiCamera()

target_resolution=(1280, 960)
capture.resolution = target_resolution
capture.framerate = 5

raw_capture = PiRGBArray(capture, target_resolution)



def _frame_iter(capture, _raw_capture):

    # capture frames from the camera

    for frame in capture.capture_continuous(_raw_capture, format="bgr", use_video_port=True):
        # grab the raw NumPy array representing the image, then initialize the timestamp
        # and occupied/unoccupied text

    # clear the stream in preparation for the next frame
        _raw_capture.flush()
        yield frame.array

t0 = time.time()
for f in _frame_iter(capture, raw_capture):
    print time.time() - t0
    t0 = time.time()
    print f.shape