__author__ = 'quentin'
from .adaptive_bg_tracker import AdaptiveBGModel, BackgroundModel, ObjectModel
from collections import deque
from math import log10
import cv2
CV_VERSION = int(cv2.__version__.split(".")[0])

import numpy as np
from scipy import ndimage
from ethoscope.core.variables import XPosVariable, YPosVariable, XYDistance, WidthVariable, HeightVariable, PhiVariable, Label
from ethoscope.core.data_point import DataPoint
from ethoscope.trackers.trackers import BaseTracker, NoPositionError
from ethoscope.utils.debug import EthoscopeException
import logging


class ForegroundModel(object):
    def is_contour_valid(self,contour,img):

        return True


class MultiFlyTracker(BaseTracker):
    _description = {"overview": "An experimental tracker to monitor several animals per ROI.",
                    "arguments": []}



    def __init__(self, roi, data=None):
        """
        An adaptive background subtraction model to find position of one animal in one roi.

        TODO more description here
        :param roi:
        :param data:
        :return:
        """
        self._previous_shape=None
        self._object_expected_size = 0.05 # proportion of the roi main axis
        self._max_area = (5 * self._object_expected_size) ** 2

        self._smooth_mode = deque()
        self._smooth_mode_tstamp = deque()
        self._smooth_mode_window_dt = 30 * 1000 #miliseconds
        self._fg_model = ForegroundModel()

        self._bg_model = BackgroundModel()
        self._max_m_log_lik = 6.
        self._buff_grey = None
        self._buff_object = None
        self._buff_object_old = None
        self._buff_grey_blurred = None
        self._buff_fg = None
        self._buff_convolved_mask = None
        self._buff_fg_backup = None
        self._buff_fg_diff = None
        self._old_sum_fg = 0

        super(MultiFlyTracker, self).__init__(roi, data)

    def _pre_process_input_minimal(self, img, mask, t, darker_fg=True):
        blur_rad = int(self._object_expected_size * np.max(img.shape) / 2.0)

        if blur_rad % 2 == 0:
            blur_rad += 1

        if self._buff_grey is None:
            self._buff_grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            if mask is None:
                mask = np.ones_like(self._buff_grey) * 255

        cv2.cvtColor(img,cv2.COLOR_BGR2GRAY, self._buff_grey)
        # cv2.imshow("dbg",self._buff_grey)
        cv2.GaussianBlur(self._buff_grey,(blur_rad,blur_rad),1.2, self._buff_grey)
        if darker_fg:
            cv2.subtract(255, self._buff_grey, self._buff_grey)

        #
        mean = cv2.mean(self._buff_grey, mask)

        scale = 128. / mean[0]

        cv2.multiply(self._buff_grey, scale, dst = self._buff_grey)


        if mask is not None:
            cv2.bitwise_and(self._buff_grey, mask, self._buff_grey)
            return self._buff_grey


    def _find_position(self, img, mask,t):

        grey = self._pre_process_input_minimal(img, mask, t)
        # grey = self._pre_process_input(img, mask, t)
        try:
            return self._track(img, grey, mask, t)
        except NoPositionError:
            self._bg_model.update(grey, t)
            raise NoPositionError


    def _track(self, img,  grey, mask,t):

        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            self._buff_object= np.empty_like(grey)
            self._buff_fg_backup = np.empty_like(grey)
  #          self._buff_fg_diff = np.empty_like(grey)
  #           self._old_pos = 0.0 +0.0j
   #         self._old_sum_fg = 0
            raise NoPositionError

        bg = self._bg_model.bg_img.astype(np.uint8)
        cv2.subtract(grey, bg, self._buff_fg)

        cv2.threshold(self._buff_fg,20,255,cv2.THRESH_TOZERO, dst=self._buff_fg)

        # cv2.bitwise_and(self._buff_fg_backup,self._buff_fg,dst=self._buff_fg_diff)
        # sum_fg = cv2.countNonZero(self._buff_fg)

        self._buff_fg_backup = np.copy(self._buff_fg)

        n_fg_pix = np.count_nonzero(self._buff_fg)
        prop_fg_pix  = n_fg_pix / (1.0 * grey.shape[0] * grey.shape[1])
        is_ambiguous = False

        if  prop_fg_pix > self._max_area:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        if  prop_fg_pix == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        if CV_VERSION == 3:
            _, contours,hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        else:
            contours,hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        contours = [cv2.approxPolyDP(c,1.2,True) for c in contours]

        valid_contours = []
        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError



        else :
            for c in contours:
                if self._fg_model.is_contour_valid(c,img):
                    valid_contours.append(c)

        if len(valid_contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        out_pos = []
        for vc in valid_contours:
            (x,y) ,(w,h), angle  = cv2.minAreaRect(vc)

            if w < h:
                angle -= 90
                w,h = h,w
            angle = angle % 180

            h_im = min(grey.shape)
            w_im = max(grey.shape)
            max_h = 2*h_im
            if w>max_h or h>max_h:
                continue
            pos = x +1.0j*y
            pos /= w_im

            # fixme some matching needed here
            #xy_dist = round(log10(1./float(w_im) + abs(pos - self._old_pos))*1000)

            cv2.ellipse(self._buff_fg ,((x,y), (int(w*1.5),int(h*1.5)),angle),255,-1)


            x_var = XPosVariable(int(round(x)))
            y_var = YPosVariable(int(round(y)))
            # distance = XYDistance(int(xy_dist))
            #xor_dist = XorDistance(int(xor_dist))
            w_var = WidthVariable(int(round(w)))
            h_var = HeightVariable(int(round(h)))
            phi_var = PhiVariable(int(round(angle)))
            # mlogl =   mLogLik(int(distance*1000))

            out = DataPoint([x_var, y_var, w_var, h_var,
                             phi_var,
                             #mlogl,
                             # distance,
                             #xor_dist
                            #Label(0)
                             ])


            out_pos.append(out)


        if len(out_pos) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        # accurate measurment for multi animal tracking:
        #cv2.ellipse(self._buff_fg ,((x,y), (int(w*1.5),int(h*1.5)),angle),255,-1)
        #


        cv2.bitwise_and(self._buff_fg_backup, self._buff_fg,self._buff_fg_backup)

        # self._old_pos = out_points


        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)

        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)


        return out_pos