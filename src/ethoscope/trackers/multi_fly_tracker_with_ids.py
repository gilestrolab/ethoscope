__author__ = 'diana'
from adaptive_bg_tracker import AdaptiveBGModel, BackgroundModel, ObjectModel
from collections import deque
from math import log10
import cv2
CV_VERSION = int(cv2.__version__.split(".")[0])

import numpy as np
from scipy import ndimage
from ethoscope.core.variables import XPosVariable, YPosVariable, XYDistance, WidthVariable, HeightVariable, PhiVariable, \
    IDVariable
from ethoscope.core.data_point import DataPoint
from ethoscope.trackers.trackers import BaseTracker, NoPositionError
from ethoscope.utils.debug import EthoscopeException
import logging


class ForegroundModel(object):
    def is_contour_valid(self,contour,img):

        return True


class MultiFlyTrackerWithIds(BaseTracker):
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

        self._n_flies = 7
        self._all_flies_found = False
        self.flies_detected_meter = 0
        self._colors = [(255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (0, 0, 0)]
        self._ids = range(1, 8)
        self._labeled_flies = {}
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


        super(MultiFlyTrackerWithIds, self).__init__(roi, data)

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

    def _intersection(self, grey, contour_a, contour_b):
        is_intersection = False
        mask_a = np.zeros_like(grey, np.uint8)
        cv2.drawContours(mask_a, [contour_a], 0, 255, -1)
        #n_px_a = np.count_nonzero(mask_a)

        mask_b = np.zeros_like(grey, np.uint8)
        cv2.drawContours(mask_b, [contour_b], 0, 255, -1)
        #n_px_b = np.count_nonzero(mask_b)

        intersection = cv2.bitwise_and(mask_a, mask_b)
        n_px_intersection = np.count_nonzero(intersection)

        if n_px_intersection > 0:
            is_intersection = True
        #
        # cv2.imshow('intersection', intersection)
        # cv2.waitKey(30)

        if CV_VERSION == 3:
            _, intersection_contour, hierarchy = cv2.findContours(intersection, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        else:
            intersection_contour ,hierarchy = cv2.findContours(intersection, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        return is_intersection, intersection_contour


    def _min_distance(self, x, y, centers):
        distances_to_centers = []
        for center in centers:
            center_x, center_y = center
            d = np.sqrt((center_x - x)**2 + (center_y - y)**2)
            distances_to_centers.append(d)
        return distances_to_centers

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

        # cv2.imshow('dbg', self._buff_fg)
        # cv2.waitKey(30)

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
        elif len(valid_contours) > self._n_flies:
            self._bg_model.increase_learning_rate()


        if self._all_flies_found is False and len(valid_contours) != self._n_flies:
            self.flies_detected_meter = 0

        if (len(self._labeled_flies) > 0):
            mapped_flies_arr = [False] * len(self._labeled_flies)
            mapped_flies = dict(zip(self._ids, mapped_flies_arr))
            new_contours_intersections = []
            for new_contour in valid_contours:
                mask_new_contour = np.zeros_like(grey, np.uint8)
                old_contours_intersections = {}
                for old_contour_id in self._labeled_flies:
                    old_contour = self._labeled_flies[old_contour_id]
                    is_intersection, intersection_contour = self._intersection(grey, new_contour, old_contour)
                    if is_intersection:
                        old_contours_intersections[old_contour_id] = intersection_contour

                el = [new_contour, old_contours_intersections]
                new_contours_intersections.append(el)
                #cv2.drawContours(mask_new_contour, np.array(old_contours_intersections.values()), 0, 200, -1)


            for el in new_contours_intersections:
                new_contour, old_contours_intersections = el
                if len(old_contours_intersections) == 1:
                    key = next(iter(old_contours_intersections))
                    self._labeled_flies[key] = new_contour
                    mapped_flies[key] = True

            for el in new_contours_intersections:
                new_contour, old_contours_intersections = el
                if len(old_contours_intersections) > 1:
                    mask_new_contour = np.zeros_like(grey, np.uint8)
                    cv2.drawContours(mask_new_contour, [new_contour], 0, 255, -1)
                    # cv2.imshow('new contour', mask_new_contour)
                    # cv2.waitKey(30)
                    center_of_mass_old_contours = []
                    mask_all_old_contours = np.zeros_like(grey, np.uint8)

                    for old_contour_id in old_contours_intersections:
                        old_contour = old_contours_intersections[old_contour_id]
                        mask_old_contours = np.zeros_like(grey, np.uint8)
                        cv2.drawContours(mask_old_contours, old_contour, 0, 255, -1)
                        # cv2.imshow('old contour', mask_old_contours)
                        # cv2.waitKey(30)
                        cv2.drawContours(mask_all_old_contours, old_contour, 0, 255, -1)
                        y,x = ndimage.measurements.center_of_mass(mask_old_contours)
                        center_of_mass_old_contours.append((x, y))
                        cv2.circle(mask_all_old_contours, (int(x), int(y)), 10, (0, 0, 0), 2)


                    # cv2.imshow('all old contour', mask_all_old_contours)
                    # cv2.waitKey(30)


                    y_ind, x_ind = mask_new_contour.nonzero()

                    distances = np.transpose(self._min_distance(x_ind, y_ind, center_of_mass_old_contours))


                    copy_mask_new_cnt = mask_new_contour.copy()

                    fly_index = [np.argmin(row) + 10 for row in distances]

                    copy_mask_new_cnt[y_ind, x_ind] = fly_index


                    for old_contour_id in old_contours_intersections:
                        old_contour = old_contours_intersections[old_contour_id]
                        another_copy_mask_new_cnt = copy_mask_new_cnt.copy()

                        fly_2_pixels = another_copy_mask_new_cnt != (old_contour_id + 10)
                        another_copy_mask_new_cnt[fly_2_pixels] = 0
                        fly_1_pixels = another_copy_mask_new_cnt == old_contour_id + 10
                        another_copy_mask_new_cnt[fly_1_pixels] = 255
                        if (CV_VERSION == 3):
                            _, contours, hierarchy = cv2.findContours(another_copy_mask_new_cnt, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                        else:
                            contours, hierarchy = cv2.findContours(another_copy_mask_new_cnt, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

                        if len(contours) > 1:
                            self._labeled_flies[old_contour_id] = contours[0]
                            mapped_flies[old_contour_id] = True




            for el in new_contours_intersections:
                new_contour, old_contours_intersections = el
                if len(old_contours_intersections) == 0:
                    if (mapped_flies.values().count(False) == 0):
                        break
                    mask_new_contour = np.zeros_like(grey, np.uint8)
                    cv2.drawContours(mask_new_contour, [new_contour], 0, 255, -1)
                    new_y, new_x = ndimage.measurements.center_of_mass(mask_new_contour)
                    center_of_mass_old_contours ={}
                    distances_to_old_contours = {}
                    for old_contour_id in self._labeled_flies:
                        if mapped_flies[old_contour_id] is False:
                            old_contour = self._labeled_flies[old_contour_id]
                            mask_old_contours = np.zeros_like(grey, np.uint8)
                            cv2.drawContours(mask_old_contours, old_contour, 0, 255, -1)
                            center_y, center_x = ndimage.measurements.center_of_mass(mask_old_contours)
                            distances_to_old_contours[old_contour_id] = np.sqrt((center_x - new_x)**2 + (center_y - new_y)**2)
                    id = min(distances_to_old_contours, key=distances_to_old_contours.get)
                    self._labeled_flies[id] = new_contour





        else:
            self.flies_detected_meter = self.flies_detected_meter + 1
            if (self.flies_detected_meter > 5):
                self._labeled_flies = dict(zip(self._ids, valid_contours))
                self._all_flies_found = True



        valid_contours =np.array(self._labeled_flies.values())
        out_pos = []
        for id in self._labeled_flies:
            vc = self._labeled_flies[id]
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

            id_var = IDVariable(id)
            x_var = XPosVariable(int(round(x)))
            y_var = YPosVariable(int(round(y)))
            # distance = XYDistance(int(xy_dist))
            #xor_dist = XorDistance(int(xor_dist))
            w_var = WidthVariable(int(round(w)))
            h_var = HeightVariable(int(round(h)))
            phi_var = PhiVariable(int(round(angle)))
            # mlogl =   mLogLik(int(distance*1000))

            out = DataPoint([id_var, x_var, y_var, w_var, h_var,
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