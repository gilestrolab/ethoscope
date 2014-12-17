__author__ = 'quentin'


import cv2
import time
import logging


class BaseCamera(object):
    #TODO catch exception eg, if initialise with a wrong file

    capture = None
    _resolution = None
    _frame_idx = 0

    def __init__(self, *args, **kwargs):
        pass

    def __del__(self):
        self._close()

    def __iter__(self):

        # We ensure timestamps and frame index are set to 0

        self.restart()
        at_leat_one_frame = False
        while True:
            if self.is_last_frame() or not self.is_opened():
                if not at_leat_one_frame:
                    raise Exception("Camera could not read the first frame")
                break
            t,out = self.next_time_image()

            if out is None:
                break
            yield t,out
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



class BaseVirtualCamera(BaseCamera):
    _path=None

    def __init__(self, path, *args, **kwargs):
        self._frame_idx = 0

    @property
    def path(self):
        return self._path
    def is_opened(self):
        return True

    def restart(self):
        self.__init__(self._path)


class MovieVirtualCamera(BaseVirtualCamera):

    def __init__(self, path, *args, **kwargs ):
        self._path = path
        self.capture = cv2.VideoCapture(path)
        w = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        h = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)
        self._total_n_frames =self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT)
        if self._total_n_frames == 0.:
            self._has_end_of_file = False
        else:
            self._has_end_of_file = True

        self._resolution = (int(w),int(h))

        super(MovieVirtualCamera, self).__init__(path,*args, **kwargs)

    def _next_image(self):
        _, frame = self.capture.read()

        return frame

    def _time_stamp(self):
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
        self.capture.set(cv2.cv.CV_CAP_PROP_FPS, target_fps)

        self._target_fps = float(target_fps)
        _, im = self.capture.read()

        # preallocate image buffer => faster
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

    def _close(self):
        self.capture.release()


    def _next_image(self):

        if self._frame_idx >0 :
            expected_time =  self._start_time + self._frame_idx / self._target_fps
            now = time.time()

            to_sleep = expected_time - now

            # Warnings if the fps is so high that we cannot grab fast enough
            if to_sleep < 0:
                logging.warning("The target FPS could not be reached. Actual FPS is about %f" % ( self._frame_idx/self._start_time))
                self.capture.grab()

            # we simply drop frames until we go above expected time
            while now < expected_time:
                self.capture.grab()
                now = time.time()
        else:
            self.capture.grab()

        self.capture.retrieve(self._frame)
        return self._frame
