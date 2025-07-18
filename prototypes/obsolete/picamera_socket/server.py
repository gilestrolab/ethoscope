import numpy as np
import logging
try:
    from picamera.array import PiRGBArray
    from picamera import PiCamera
except:
    logging.warning("Could not load picamera module")

import multiprocessing
from ethoscope.tracking.cameras import BaseCamera
from ethoscope.utils.debug import EthoscopeException
import time




# class PiFrameGrabber(Thread):
class PiFrameGrabber(multiprocessing.Process):

    def __init__(self, queue):

        #self.camera...
        res = (640,480)
        self.img = np.zeros((res[0],res[1],3),np.uint8)
        self._queue = queue

        self._force_stop = False

        super(PiFrameGrabber, self).__init__()

    # def get_last_frame(self):
    #     i = 0
    #     msg = self._queue.get()
    #     while self._queue.qsize()>1:
    #         msg = self._queue.get()
    #         print "FLUSHING", i
    #     # print "no flushing", self._queue.qsize()
    #     return msg




    def stop(self):
        self._queue.cancel_join_thread()
        self._queue.close()


    def run(self):
        try:
            self._frame_cb = FrameCallBack(None,self._queue)
            ttt0 = time.time()
            while not self._force_stop:

                    time.sleep(.1)

                    if self._frame_cb.is_done:
                        TODO
                    self._frame_cb.analyse(None)

                    print("running222")
                    # with picamera.PiCamera() as camera:
                    #     with DetectMotion(camera) as output:
                    #             self._img = output.get_array()
                    #         camera.resolution = (640, 480)
                    #         camera.start_recording(output, format='bgr')
                    #         camera.wait_recording(3600*24*365)
                    #         camera.stop_recording()
                    # if time.time() - ttt0 > 3:
                    #     raise Exception("bouya")

        finally:
            self._queue.cancel_join_thread()
            pass


class OurPiCamera(BaseCamera):

    def __init__(self, target_fps=10, target_resolution=(960,720), *args, **kwargs):

        logging.info("Initialising camera")
        w,h = target_resolution
        self.capture = PiCamera()

        self.capture.resolution = target_resolution
        if not isinstance(target_fps, int):
            raise EthoscopeException("FPS must be an integer number")

        self.capture.framerate = target_fps

        self._raw_capture = PiRGBArray(self.capture, size=target_resolution)

        self._target_fps = float(target_fps)
        self._warm_up()

        self._cap_it = self._frame_iter()

        im = next(self._cap_it)

        if im is None:
            raise EthoscopeException("Error whist retrieving video frame. Got None instead. Camera not plugged?")

        self._frame = im



        if len(im.shape) < 2:
            raise EthoscopeException("The camera image is corrupted (less that 2 dimensions)")

        self._resolution = (im.shape[1], im.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))


        super(OurPiCamera, self).__init__(*args, **kwargs)

        self._start_time = time.time()
        logging.info("Camera initialised")

    def _warm_up(self):
        logging.info("%s is warming up" % (str(self)))
        time.sleep(1)

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
        self._raw_capture.truncate(0)
        self.capture.close()

        # self.capture.release()

    def _frame_iter(self):

        # capture frames from the camera

        for frame in self.capture.capture_continuous(self._raw_capture, format="bgr", use_video_port=True):
            # grab the raw NumPy array representing the image, then initialize the timestamp
            # and occupied/unoccupied text

        # clear the stream in preparation for the next frame
            self._raw_capture.truncate(0)
            yield frame.array


class FrameCallBack(object):
    def __init__(self,camera,queue):
        # res = camera.resolution
        self._queue = queue
        self.is_done=False
        # super(FrameCallBack, self).__init__(camera)
        super(FrameCallBack, self).__init__()

    def analyse(self, a):
        out = np.random.random((640,480,3))
        out *=100
        out = out.astype(np.uint8)
        while self._queue.qsize()>1:
            msg = self._queue.get()
            if msg=="DONE":
                self.is_done=True
        self._queue.put(out)





_queue = multiprocessing.JoinableQueue()
p = PiFrameGrabber(_queue)
p.daemon = False
p.start()

# if time.time() - ttt0 > 3:
#     raise Exception("bouya")

loop=True
try:
    ttt0 = time.time()
    while loop:

            # p.get_last_frame()[1,1]
            time.sleep(.5)

            if time.time() - ttt0 > 3:
                loop=False
                print("OUTOFLOOP")
except:
    pass
finally:
    p.stop()
    print("join")
    p.join()
