__author__ = 'quentin'

import cv2
import numpy as np

class EthoscopeException(Exception):

    def __init__(self,value, img=None):
        """
        A custom exception. It can store an image

        :param value: A value passed to the exception, generally a text message
        :param img: an image
        :type img: :class:`~numpy.ndarray`
        :return:
        """
        self.value = value
        if isinstance(img, np.ndarray):
            self.img = np.copy(img)
        else:
            self.img = None
            
    def __str__(self):
        return repr(self.value)


def show(im,t=-1):
    """
    A function to simply display an image and wait. This is for debugging purposes only.
    :param im: the image to show
    :type im: :class:`~numpy.ndarray`
    :param t: the time to wait, in ms. Lower than 1 means until user enter a key.
    :type t: int
    :return:
    """
    cv2.imshow("debug",im)
    cv2.waitKey(t)
