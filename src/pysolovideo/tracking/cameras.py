__author__ = 'quentin'


import cv2



class BaseCamera(object):

    capture = None
    resolution = None

    def __init__(self):

        raise NotImplementedError

    def __del__(self):
        self.capture.close()

    def __iter__(self):
        while True:
            if self.is_last_frame() or not self.is_opened():
                break

            yield self._next_image()


    def is_opened(self):
        raise NotImplementedError

    @property
    def resolution(self):
        return self.resolution

    @property
    def width(self):
        return self.resolution[0]

    @property
    def height(self):
        return self.resolution[1]

    def is_last_frame(self):
        raise NotImplementedError
    def _next_image(self):
        raise NotImplementedError

class BasePhysicalCamera(BaseCamera):
    def is_last_frame(self):
        return False


class BaseVirtualCamera(BaseCamera):
    pass

class USBCamera(PhysicalCamera):
    pass


