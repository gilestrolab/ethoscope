__author__ = 'quentin'

import cv2
import numpy as np

class PSVException(Exception):
    def __init__(self,value, img=None):
        self.value = value
        if isinstance(img, np.ndarray):
            self.img = np.copy(img)
        else:
            self.img = None
            
    def __str__(self):
        return repr(self.value)


def show(im,t=-1):
    cv2.imshow("debug",im)
    cv2.waitKey(t)
