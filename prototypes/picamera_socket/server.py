
from picamera.array import PiRGBArray
import picamera
import cv2
import numpy as np
import time

class DetectMotion(picamera.array.PiRGBAnalysis):
    img = None
    t0 = time.time()
    def analyse(self, a):
        print time.time() - self.t0 
        self.t0 = time.time()
        self.img = a


with picamera.PiCamera() as camera:
    with DetectMotion(camera) as output:
        camera.resolution = (640, 480)
        camera.start_recording(
              '/dev/null', format='bgr', motion_output=output)
        camera.wait_recording(30)
        camera.stop_recording()