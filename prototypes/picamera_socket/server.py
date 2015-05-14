
from picamera.array import PiRGBArray
from picamera import PiCamera
import cv2
import numpy as np



target_resolution=(1280, 960)
capture.framerate = 5
capture = PiCamera()
capture.resolution = target_resolution


raw_capture = PiRGBArray(capture, target_resolution)



def _frame_iter(capture, _raw_capture):

    # capture frames from the camera

    for frame in capture.capture_continuous(_raw_capture, format="bgr", use_video_port=True):
        # grab the raw NumPy array representing the image, then initialize the timestamp
        # and occupied/unoccupied text

    # clear the stream in preparation for the next frame
        _raw_capture.truncate(0)
        yield frame.array


for f in _frame_iter(capture, raw_capture):
    print f.shape