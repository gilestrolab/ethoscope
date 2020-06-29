
import cv2
import time
import logging
import os
import numpy as np
from ethoscope.utils.debug import EthoscopeException
import multiprocessing
from scipy.misc import toimage, imread, imsave
from io import BytesIO
import io
from ethoscope.hardware.input.cameras import PiFrameGrabber, OurPiCameraAsync

class PiFrameGrabberJPEG(PiFrameGrabber):
    def run(self):
        try:
            with  PiCamera() as capture:
                capture.resolution = self._target_resolution

                capture.framerate = self._target_fps
                raw_capture = PiRGBArray(capture, size=self._target_resolution)

                for frame in capture.capture_continuous(raw_capture, format="bgr", use_video_port=True):
                    if not self._stop_queue.empty():
                        logging.info("The stop queue is not empty. Stop acquiring frames")

                        self._stop_queue.get()
                        self._stop_queue.task_done()
                        logging.info("Stop Task Done")
                        break
                    raw_capture.truncate(0)
                    # out = np.copy(frame.array)
                    out = BytesIO()
                    toimage(frame.array, cmin=0.0, cmax=255).save(out,"JPEG")

                    #fixme here we could actually pass a JPG compressed file object (http://docs.scipy.org/doc/scipy-0.16.0/reference/generated/scipy.misc.imsave.html)
                    # This way, we would manage to get faster FPS
                    self._queue.put(out)
        finally:
            self._stop_queue.close()
            self._queue.close()
            logging.info("Camera Frame grabber stopped acquisition cleanly")



class OurPiCameraAsyncJPEG(OurPiCameraAsync):

    def _next_image(self):

        try:
            g = self._queue.get(timeout=30)
            self._frame =  imread(g)
            return self._frame
        except Exception as e:
            raise EthoscopeException("Could not get frame from camera\n%s", str(e))

cam = OurPiCameraAsyncJPEG()
t0 = 0

for t,f in cam:
    print("dt = ", t - t0)
    print(np.sum(cam))
    time.sleep(.3)
    t0 = t