from pip.utils import logging

__author__ = 'quentin'


import cv2
import time
import logging
import os
from ethoscope.utils.debug import EthoscopeException
from ethoscope.tracking.cameras import BaseCamera
import multiprocessing
try:
    from picamera.array import PiRGBArray
    from picamera import PiCamera
except:
    logging.warning("Could not load picamera module")


class PiFrameGrabber(multiprocessing.Process):

    def __init__(self, target_fps, target_resolution, queue,stop_queue):
        self._queue = queue
        self._stop_queue = stop_queue
        self._target_fps = target_fps
        self._target_resolution = target_resolution


        super(PiFrameGrabber, self).__init__()


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
                    out = cv2.cvtColor(frame.array,cv2.COLOR_BGR2GRAY)

                    self._queue.put(out)
        finally:
            self._stop_queue.close()
            self._queue.close()
            logging.info("Camera Frame grabber stopped acquisition cleanly")


        #
        # try:
        #     capture = cv2.VideoCapture("/lud/validation_2fps.mp4")
        #     while True:
        #         if not self._stop_queue.empty():
        #             logging.info("The stop queue is not empty. Stop acquiring frames")
        #             self._stop_queue.get()
        #             self._stop_queue.task_done()
        #             logging.info("Stop Task Done")
        #             break
        #
        #         _, frame = capture.read()
        #         out = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        #         self._queue.put(out)
        # finally:
        #     capture.release()
        #
        #
        #     self._stop_queue.close()
        #     self._queue.close()
        #     logging.info("Camera Frame grabber stopped acquisition cleanly")



class OurPiCameraAsync(BaseCamera):

    def __init__(self, target_fps=10, target_resolution=(960,720), *args, **kwargs):

        logging.info("Initialising camera")
        w,h = target_resolution

        if not isinstance(target_fps, int):
            raise EthoscopeException("FPS must be an integer number")



        self._queue = multiprocessing.Queue(maxsize=2)
        self._stop_queue = multiprocessing.JoinableQueue(maxsize=1)
        self._p = PiFrameGrabber(target_fps,target_resolution,self._queue,self._stop_queue )
        self._p.daemon = True
        self._p.start()



        im = self._queue.get(timeout=5)

        self._frame = cv2.cvtColor(im,cv2.COLOR_GRAY2BGR)


        if len(im.shape) < 2:
            raise EthoscopeException("The camera image is corrupted (less that 2 dimensions)")

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
        logging.info("Requesting grabbing process to stop!")

        self._stop_queue.put(None)

        while not self._queue.empty():
             self._queue.get()

        logging.info("Joining stop queue")

        self._stop_queue.cancel_join_thread()
        self._queue.cancel_join_thread()

        logging.info("Stopping stop queue")
        self._stop_queue.close()

        logging.info("Stopping queue")
        self._queue.close()
        logging.info("Joining process")

        self._p.join()

        logging.info("All joined ok")

    def _next_image(self):

        try:
            g = self._queue.get(timeout=30)
            cv2.cvtColor(g,cv2.COLOR_GRAY2BGR,self._frame)
            return self._frame
        except Exception as e:
            raise EthoscopeException("Could not get frame from camera\n%s", str(e))

#
while True:
    cap = OurPiCameraAsync()
    for t,f in cap:
        # time.sleep(1)
        print(t)
        if t>3000:
            break

    cap._close()
    print("closed")
