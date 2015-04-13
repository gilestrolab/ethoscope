__author__ = 'quentin'


import cv2
import time
import logging
import os
from pysolovideo.utils.debug import PSVException
try:
    from picamera.array import PiRGBArray
    from picamera import PiCamera
except:
    logging.warning("Could not load picamera module")

class BaseCamera(object):
    #TODO catch exception eg, if initialise with a wrong file

    capture = None
    _resolution = None
    _frame_idx = 0

    def __init__(self, *args, **kwargs):
        pass

    def __del__(self):
        logging.info("Closing camera")
        self._close()

    def __iter__(self):

        # We ensure timestamps and frame index are set to 0

        self.restart()
        at_leat_one_frame = False
        while True:
            if self.is_last_frame() or not self.is_opened():
                if not at_leat_one_frame:
                    raise PSVException("Camera could not read the first frame")
                break
            t,out = self.next_time_image()

            if out is None:
                break
            t_ms = int(1000*t)

            yield t_ms,out

            at_leat_one_frame = True


    @property
    def resolution(self):
        return self._resolution

    @property
    def width(self):
        return self._resolution[0]

    @property
    def height(self):
        return self._resolution[1]

    def next_time_image(self):
        im = self._next_image()
        time = self._time_stamp()
        self._frame_idx += 1
        return time, im



    def is_last_frame(self):
        raise NotImplementedError
    def _next_image(self):
        raise NotImplementedError
    def _time_stamp(self):
        raise NotImplementedError
    def is_opened(self):
        raise NotImplementedError
    def restart(self):
        raise NotImplementedError



class MovieVirtualCamera(BaseCamera):


    def __init__(self, path, use_wall_clock = False,  *args, **kwargs ):
        self._frame_idx = 0
        self._path = path
        self._use_wall_clock = use_wall_clock

        if not isinstance(path, str):
            raise PSVException("path to video must be a string")
        if not os.path.exists(path):
            raise PSVException("'%s' does not exist. No such file" % path)

        self.capture = cv2.VideoCapture(path)
        w = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        h = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)
        self._total_n_frames =self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT)
        if self._total_n_frames == 0.:
            self._has_end_of_file = False
        else:
            self._has_end_of_file = True

        self._resolution = (int(w),int(h))

        super(MovieVirtualCamera, self).__init__(path, *args, **kwargs)

        # emulates v4l2 (real time camera) from video file
        if self._use_wall_clock:
            self._start_time = time.time()
        else:
            self._start_time = 0

    @property
    def start_time(self):
        return self._start_time

    @property
    def path(self):
        return self._path

    def is_opened(self):
        return True

    def restart(self):
        self.__init__(self._path, self._use_wall_clock)


    def _next_image(self):
        _, frame = self.capture.read()
        return frame

    def _time_stamp(self):
        if self._use_wall_clock:
            now = time.time()
            return now - self._start_time

        time_s = self.capture.get(cv2.cv.CV_CAP_PROP_POS_MSEC) / 1e3
        return time_s

    def is_last_frame(self):
        if self._has_end_of_file and self._frame_idx >= self._total_n_frames:
            return True
        return False

    def _close(self):
        self.capture.release()


class V4L2Camera(BaseCamera):
    def __init__(self,device, target_fps=5, target_resolution=(960,720), *args, **kwargs):
        self.capture = cv2.VideoCapture(device)
        self._warm_up()

        w, h = target_resolution
        if w <0 or h <0:
            self.capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 99999)
            self.capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 99999)
        else:
            self.capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, w)
            self.capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, h)

        if not isinstance(target_fps, int):
            raise PSVException("FPS must be an integer number")

        if target_fps < 2:
            raise PSVException("FPS must be at least 2")

        self.capture.set(cv2.cv.CV_CAP_PROP_FPS, target_fps)

        self._target_fps = float(target_fps)
        _, im = self.capture.read()

        # preallocate image buffer => faster
        if im is None:
            raise PSVException("Error whist retrieving video frame. Got None instead. Camera not plugged?")

        self._frame = im


        #TODO better exception handling is needed here / what do we do if initial capture fails...
        assert(len(im.shape) >1)

        self._resolution = (im.shape[1], im.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))


        super(V4L2Camera, self).__init__(*args, **kwargs)
        self._start_time = time.time()

    def _warm_up(self):
        logging.info("%s is warming up" % (str(self)))
        time.sleep(2)

    def restart(self):
        self._frame_idx = 0
        self._start_time = time.time()

    def is_opened(self):
        return self.capture.isOpened()


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
        self.capture.release()


    def _next_image(self):

        if self._frame_idx >0 :
            expected_time =  self._start_time + self._frame_idx / self._target_fps
            now = time.time()

            to_sleep = expected_time - now

            # Warnings if the fps is so high that we cannot grab fast enough
            if to_sleep < 0:
                if self._frame_idx % 5000 == 0:
                    logging.warning("The target FPS (%f) could not be reached. Effective FPS is about %f" % (self._target_fps, self._frame_idx/(now - self._start_time)))
                self.capture.grab()

            # we simply drop frames until we go above expected time
            while now < expected_time:
                self.capture.grab()
                now = time.time()
        else:
            self.capture.grab()

        self.capture.retrieve(self._frame)



        return self._frame




class OurPiCamera(BaseCamera):

    def __init__(self, target_fps=10, target_resolution=(960,720), *args, **kwargs):


        w,h = target_resolution
        self.capture = PiCamera()

        self.capture.resolution = target_resolution
        if not isinstance(target_fps, int):
            raise PSVException("FPS must be an integer number")
        self.capture.framerate = target_fps

        self._raw_capture = PiRGBArray(self.capture, size=target_resolution)

        self._target_fps = float(target_fps)
        self._warm_up()

        self._cap_it = self._frame_iter()

        im = next(self._cap_it)

        if im is None:
            raise PSVException("Error whist retrieving video frame. Got None instead. Camera not plugged?")

        self._frame = im


        assert(len(im.shape) >1)

        self._resolution = (im.shape[1], im.shape[0])
        if self._resolution != target_resolution:
            if w > 0 and h > 0:
                logging.warning('Target resolution "%s" could NOT be achieved. Effective resolution is "%s"' % (target_resolution, self._resolution ))
            else:
                logging.info('Maximal effective resolution is "%s"' % str(self._resolution))


        super(OurPiCamera, self).__init__(*args, **kwargs)
        self._start_time = time.time()

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




    def _next_image(self):

        if self._frame_idx >0 :
            expected_time =  self._start_time + self._frame_idx / self._target_fps
            now = time.time()

            to_sleep = expected_time - now

            # Warnings if the fps is so high that we cannot grab fast enough
            if to_sleep < 0:
                if self._frame_idx % 5000 == 0:
                    logging.warning("The target FPS (%f) could not be reached. Effective FPS is about %f" % (self._target_fps, self._frame_idx/(now - self._start_time)))
                next(self._cap_it)

            # we simply drop frames until we go above expected time
            while now < expected_time:
                next(self._cap_it)
                now = time.time()


        self._frame = next(self._cap_it)

        return self._frame
