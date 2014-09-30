__author__ = 'quentin'

import numpy as np
import pandas as pd

class BaseTracker(object):
    # a list of complex number representing x(real) and y(imaginary) coordinatesT
    _positions = []
    _time_stamps = []
    _data=None

    def __init__(self, data=None):
        self._data = data

    def __call__(self, t, img, mask):
        point = self._find_position(img,mask)
        self._positions.append(point)
        self._time_stamps.append(t)
        return point


    def _find_position(self,img, mask):
        raise NotImplementedError



class DummyTracker(BaseTracker):

    def _find_position(self,img, mask):
        # random_walk
        x, y = np.random.uniform(size=2)
        point = np.complex64(x + y * 1j)
        return self._positions[-1] + point






