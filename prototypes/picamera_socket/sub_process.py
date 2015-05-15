__author__ = 'quentin'

import numpy as np
import logging
try:
    from picamera.array import PiRGBArray
    from picamera import PiCamera
except:
    logging.warning("Could not load picamera module")

import multiprocessing
from pysolovideo.tracking.cameras import BaseCamera
from pysolovideo.utils.debug import PSVException
import time
import cv2



class PiFrameGrabber(multiprocessing.Process):

    def __init__(self, target_fps, target_resolution, queue):
        self._queue = queue
        self._target_fps = target_fps
        self._target_resolution = target_resolution


        super(PiFrameGrabber, self).__init__()


    def run(self):
        try:
            w,h = self._target_resolution
            capture = PiCamera()
            capture.resolution = self._target_resolution

            capture.framerate = self._target_fps
            raw_capture = PiRGBArray(capture, size=self._target_resolution)

            for frame in capture.capture_continuous(raw_capture, format="bgr", use_video_port=True):
                # print "getting frame"

                to_break = False

                # while self._queue.qsize() > 2:
                #     msg = self._queue.get()
                #     if msg is None:
                #         to_break =True
                # if to_break:
                #     logging.info("Camera frame grabber was instructed to stop by parent process")
                #     break

                raw_capture.truncate(0)
                out = cv2.cvtColor(frame.array,cv2.COLOR_BGR2GRAY)
                #out = np.copy(out[0:100, 0:100])
                self._queue.put(out)
                print "frame PUT"


        finally:
            capture.close()




class OurPiCameraAsync(BaseCamera):

    def __init__(self, target_fps=10, target_resolution=(960,720), *args, **kwargs):

        logging.info("Initialising camera")
        w,h = target_resolution

        if not isinstance(target_fps, int):
            raise PSVException("FPS must be an integer number")



        self._queue = multiprocessing.Queue()
        self._p = PiFrameGrabber(target_fps,target_resolution,self._queue)
        self._p.daemon = True
        self._p.start()



        im = self._queue.get(timeout=5)
        self._frame = im


        if len(im.shape) < 2:
            raise PSVException("The camera image is corrupted (less that 2 dimensions)")

        self._resolution = (im.shape[1], im.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))


        super(OurPiCameraAsync, self).__init__(*args, **kwargs)

        self._start_time = time.time()
        logging.info("Camera initialised")



    def restart(self):
        self._frame_idx = 0
        self._start_time = time.time()

    def is_opened(self):
        return True
        # return self.capture.isOpened()


    def is_last_frame(self):
        return False

    def _time_stamp(self):
        now = time.time()
        # relative time stamp
        return now - self._start_time

    @property
    def start_time(self):
        return self._start_time

    def _close(self):

        self._queue.put(None)
        self._p.join(timeout=5)

    def _next_image(self):

        try:
            t0= time.time()
            g = self._queue.get(timeout=30)

            print "time to get", time.time() - t0
            return g
        except Exception as e:
            raise PSVException("Could not get frame from camera\n%s", str(e))


#
# class CameraStub(object):
#     def __init__(self):
#         self._stop = False
#         self._queue = multiprocessing.Queue()
#         self._p = PiFrameGrabber(self._queue)
#         self._p.daemon = True
#         self._p.start()
#
#
#     def frame_iter(self):
#         try:
#             while not self._stop:
#                 print "qs = ", self._queue.qsize()
#                 o = self._queue.get(timeout=1)
#                 yield o
#         except:
#             raise Exception("Could not get frame from camera")
#     def close(self):
#         self._stop = True
#         self._queue.put(None)
#         self._p.join(timeout=5)
#
#
# c = CameraStub()
# t0 = time.time()
# for i in c.frame_iter():
#     print i
#     time.sleep(.5)
#     if time.time() - t0 > 5:
#         break
# c.close()
#
c = OurPiCameraAsync(target_fps=20,target_resolution=(1280,960))
t0 = 0

for t,f in c:
    print t - t0
    t0 = t
    # cv2.imshow("t",f)
    # cv2.waitKey(int(1000.0/2))


