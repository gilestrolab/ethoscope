__author__ = 'quentin'

from collections import deque
import cv2

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2


import numpy as np
from ethoscope.core.variables import XPosVariable, YPosVariable, WidthVariable, HeightVariable, PhiVariable
from ethoscope.core.data_point import DataPoint
from ethoscope.trackers.adaptive_bg_tracker import BackgroundModel
from ethoscope.trackers.trackers import BaseTracker, NoPositionError
from ethoscope.utils.img_proc import merge_blobs


class AdaptiveBGModelOneObject(BaseTracker):

    def __init__(self, roi, data=None):

        self._object_expected_size = 0.005 # proportion of the roi main axis
        self._max_area = (5 * self._object_expected_size) ** 2
        # self._max_length = 5 * self._object_expected_size
        self._smooth_mode = deque()
        self._smooth_mode_tstamp = deque()
        self._smooth_mode_window_dt = 30 * 1000 #miliseconds


        self._bg_model = BackgroundModel()

        self._buff_grey = None
        self._buff_grey_blurred = None
        self._buff_fg = None
        self._buff_convolved_mask = None
        self._erode_kern = np.ones((7,7),np.uint8)
        super(AdaptiveBGModelOneObject, self).__init__(roi, data)

    def _pre_process_input_minimal(self, img, mask, t, darker_fg=True):
        if self._buff_grey is None:
            self._buff_grey = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            if mask is None:
                mask = np.ones_like(self._buff_grey) * 255

        cv2.cvtColor(img,cv2.COLOR_BGR2GRAY, self._buff_grey)

        cv2.erode(self._buff_grey, self._erode_kern, dst=self._buff_grey)

        if darker_fg:
            cv2.subtract(255, self._buff_grey, self._buff_grey)


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
    def _exclude_incorrect_hull(self,hulls):

        out = []
        for contour in hulls:
            (_,_) ,(width,height), angle  = cv2.minAreaRect(contour)
            width, height= max(width,height), min(width,height)
            ar = ((height+1) / (width+1))
            area = cv2.contourArea(contour)
            if 50 < area < 2000 and ar > .3:
                out.append(contour)

        return out


    def _track(self, img,  grey, mask,t):

        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            raise NoPositionError

        bg = self._bg_model.bg_img.astype(np.uint8)
        cv2.subtract(grey, bg, self._buff_fg)

        #fixme magic number
        cv2.threshold(self._buff_fg,15,255,cv2.THRESH_BINARY, dst=self._buff_fg)


        n_fg_pix = np.count_nonzero(self._buff_fg)
        prop_fg_pix  = n_fg_pix / (1.0 * grey.shape[0] * grey.shape[1])
        is_ambiguous = False

        if  prop_fg_pix > self._max_area:
            self._bg_model.increase_learning_rate()
            print("too big")
            raise NoPositionError

        if  prop_fg_pix == 0:
            self._bg_model.increase_learning_rate()
            print("no pixs")
            raise NoPositionError
        # show(self._buff_fg,100)
        if CV_VERSION == 3:
            _, contours,hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        else:
            contours,hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            print("No contours")
            raise NoPositionError


        elif len(contours) > 1:


            hulls = [cv2.convexHull( c) for c in contours]
            hulls = merge_blobs(hulls)

            hulls = [h for h in hulls if h.shape[0] >= 3]
            print("before exclusion", len(hulls))

            hulls = self._exclude_incorrect_hull(hulls)

            print("after exclusion", len(hulls))

            if len(hulls) == 0:
                raise NoPositionError

            elif len(hulls) > 1:
                raise NoPositionError






            else:
                is_ambiguous = False

                hull = hulls[0]



        else:
            hull = cv2.convexHull(contours[0])
            if hull.shape[0] < 3:
                self._bg_model.increase_learning_rate()
                raise NoPositionError

        (_,_) ,(w,h), angle  = cv2.minAreaRect(hull)


        M = cv2.moments(hull)

        x = int(M['m10']/M['m00'])
        y = int(M['m01']/M['m00'])



        if w < h:
            angle -= 90
            w,h = h,w

        angle = angle % 180


        h_im = min(grey.shape)
        max_h = 2*h_im
        if w>max_h or h>max_h:
            raise NoPositionError




        x_var = XPosVariable(int(round(x)))
        y_var = YPosVariable(int(round(y)))
        w_var = WidthVariable(int(round(w)))
        h_var = HeightVariable(int(round(h)))
        phi_var = PhiVariable(int(round(angle)))



        self._buff_fg.fill(0)

        cv2.drawContours(self._buff_fg ,[hull],0, 1,-1)

        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)
        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)


        out = DataPoint([x_var, y_var, w_var, h_var, phi_var])


        return out