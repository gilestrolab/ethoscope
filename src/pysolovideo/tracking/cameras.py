__author__ = 'quentin'


import cv2
import cv


class BaseCamera(object):

    capture = None
    _resolution = None
    _frame_idx = 0

    def __init__(self, *args, **kwargs):
        pass

    def __del__(self):
        NotImplementedError

    def __iter__(self):

        while True:
            if self.is_last_frame() or not self.is_opened():
                break
            self._frame_idx += 1

            yield self._time_stamp(), self._next_image()


    def is_opened(self):
        raise NotImplementedError

    @property
    def resolution(self):
        return self._resolution

    @property
    def width(self):
        return self._resolution[0]

    @property
    def height(self):
        return self._resolution[1]

    def is_last_frame(self):
        raise NotImplementedError
    def _next_image(self):
        raise NotImplementedError
    def _time_stamp(self):
        raise NotImplementedError

class BasePhysicalCamera(BaseCamera):
    def is_last_frame(self):
        return False


class BaseVirtualCamera(BaseCamera):
    _path=None

    @property
    def path(self):
        return self._path
    def is_opened(self):
        return True


class MovieVirtualCamera(BaseVirtualCamera):

    def __init__(self, path, *args, **kwargs ):
        self._path = path
        self.capture = cv2.VideoCapture(path)
        w = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_WIDTH)
        h = self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT)
        self._total_n_frames =self.capture.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT)
        self._resolution = (int(w),int(h))
        super(MovieVirtualCamera, self).__init__(*args, **kwargs)

    def _next_image(self):
        _, frame = self.capture.read()
        return frame

    def _time_stamp(self):
        time_s = self.capture.get(cv2.cv.CV_CAP_PROP_POS_MSEC) / 1e3

        return time_s

    def is_last_frame(self):
        if self._frame_idx >= self._total_n_frames:
            return True

        return False
    def __del__(self):
        self.capture.release()




class USBCamera(BasePhysicalCamera):
    pass


