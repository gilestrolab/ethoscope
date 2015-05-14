import numpy as np
import picamera
import picamera.array

class DetectMotion(picamera.array.PiRGBAnalysis):
    def analyse(self, a):

        # If there're more than 10 vectors with a magnitude greater
        # than 60, then say we've detected motion
        print np.sum(a)

with picamera.PiCamera() as camera:
    with DetectMotion(camera) as output:
        camera.resolution = (640, 480)
        camera.start_recording(
              '/dev/null', format='bgr')
        camera.wait_recording(30)
        camera.stop_recording()