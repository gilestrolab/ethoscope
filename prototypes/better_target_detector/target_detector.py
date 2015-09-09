__author__ = 'quentin'

import cv2
import numpy as np
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI
import itertools


class TargetGridROIBuilder(TargetGridROIBuilderBase):
    def __init__(self, n_rows, n_cols, top_margin, bottom_margin,
                 left_margin, right_margin, horizontal_fill, vertical_fill):
        self._n_rows = n_rows
        self._n_cols = n_cols
        self._top_margin =  top_margin
        self._bottom_margin = bottom_margin
        self._left_margin = left_margin
        self._right_margin = right_margin
        self._horizontal_fill = horizontal_fill
        self._vertical_fill = vertical_fill

        super(TargetGridROIBuilder,self).__init__()

class SleepMonitorROIBuilder(TargetGridROIBuilderBase):

    _n_rows = 10
    _n_cols = 2
    _top_margin =  6.99 / 111.00
    _horizontal_fill = .9
    _vertical_fill = .7


test_rb = SleepMonitorROIBuilder()
im = cv2.imread("sample.png")
test_rb(im)


