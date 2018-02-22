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

from sklearn.cluster import KMeans

try:
    from cv2.cv import CV_FOURCC as VideoWriter_fourcc
except ImportError:
    from cv2 import VideoWriter_fourcc


class ForegroundModel(object):

    def __init__(self):
        self._previous_contours = []
        super(ForegroundModel, self).__init__()

    def _is_intersection(self, img, contour_a, contour_b):
        is_intersection = False
        mask_a = np.zeros_like(img, np.uint8)
        cv2.drawContours(mask_a, [contour_a], 0, 255, -1)

        mask_b = np.zeros_like(img, np.uint8)
        cv2.drawContours(mask_b, [contour_b], 0, 255, -1)

        intersection = cv2.bitwise_and(mask_a, mask_b)
        n_px_intersection = np.count_nonzero(intersection)

        if n_px_intersection > 0:
            is_intersection = True

        print is_intersection
        return is_intersection

    def is_contour_valid(self,contour,img):
        for c in self._previous_contours:
            if self._is_intersection(img, c, contour):
                return True
        return False


class MultiFlyTrackerKMeans(AdaptiveBGModel):
    _description = {"overview": "An experimental tracker to monitor several animals per ROI.",
                    "arguments": []}



    def __init__(self, roi, data=None, n_flies=2):
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
        self._n_flies = n_flies
        self._all_flies_found = False
        self._kmeans = KMeans(n_clusters=self._n_flies, max_iter=1000, n_jobs=1, tol=1e-10)
        self._previous_kmeans_centers = []
        self._min_initial_iterations = 1000
        self._iteration_counts = 0
        self._once_done = False

        super(MultiFlyTrackerKMeans, self).__init__(roi, data)


    def _filter_contours(self, previous_centers, contours):
        Ms = [cv2.moments(c) for c in contours]

        #print Ms
        centers = [[int(M['m01']/M['m00']), int(M['m10']/M['m00'])] for M in Ms]

        # print 'Previous centers', previous_centers
        # print 'This', centers


    def _track(self, img,  grey, mask,t):

        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            self._old_pos = [0.0 +0.0j] * self._n_flies
            self._buff_object= np.empty_like(grey)
            self._buff_fg_backup = np.empty_like(grey)
            raise NoPositionError

        bg = self._bg_model.bg_img.astype(np.uint8)
        cv2.subtract(grey, bg, self._buff_fg)

        cv2.threshold(self._buff_fg,20,255,cv2.THRESH_TOZERO, dst=self._buff_fg)
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

        if len(contours) == 0 :
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        valid_contours = contours

        #if there are too many contours, remove the smallest
        if len(valid_contours) > self._n_flies:
            areas = []

            for c in valid_contours:
                areas.append(cv2.contourArea(c))

            print 'Before', areas
            # Sort array of areas by size
            sorted_areas = sorted(zip(areas, valid_contours), key=lambda x: x[0], reverse=True)

            # sorted_areas = sorted_areas[sorted_areas != 0.0]
            # print 'nonzero areas', sorted_areas

            a = []
            for i in range(0, self._n_flies):
                area, c = sorted_areas[i]
                a.append(c)
            valid_contours = a
            areas = []

            for c in valid_contours:
                areas.append(cv2.contourArea(c))

            print 'After', areas


            #self._filter_contours(self._previous_kmeans_centers, valid_contours)


        if len(valid_contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        else:
            vc_frame = np.zeros_like(grey)
            cv2.drawContours(vc_frame, valid_contours,  -1, 255, -1)
            cv2.imshow('valid contours', vc_frame)
            #cv2.waitKey(0)
            out = np.zeros_like(vc_frame)
            x, y = np.where(vc_frame == 255)
            self._iteration_counts = self._iteration_counts + 1
            if len(x) < self._n_flies:
                self._bg_model.increase_learning_rate()
                raise NoPositionError
            else:
                X = np.column_stack((x,y))
                self._kmeans.fit(X)
                if len(self._previous_kmeans_centers) > 0:
                    diff_centers = np.around(self._kmeans.cluster_centers_ - self._previous_kmeans_centers)
                    distances = [item[0]**2 + item[1]**2 for item in diff_centers]
                    print distances
                    if any(d > 2000 for d in distances) and self._iteration_counts > self._min_initial_iterations and not self._once_done:
                        self._once_done = True
                        print self._iteration_counts
                        self._bg_model.increase_learning_rate()
                        raise NoPositionError

                self._once_done = False
                self._kmeans.set_params(init=self._kmeans.cluster_centers_)
                self._previous_kmeans_centers = self._kmeans.cluster_centers_

                #print self._kmeans.cluster_centers_
                out[x, y] = self._kmeans.labels_.astype(np.uint8) + 1


            valid_contours = []
            for i in range(1, self._n_flies + 1):
                out_copy = out.copy()
                selected_pixels = out_copy != i
                out_copy[selected_pixels] = 0
                fly_pixels = out_copy == i
                out_copy[fly_pixels] = 255



                # if (self._iteration_counts > 1000):
                #     cv2.imshow('individual fly', out_copy)
                #     cv2.waitKey(0)

                if CV_VERSION == 3:
                    _, contours,hierarchy = cv2.findContours(out_copy, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                else:
                    contours,hierarchy = cv2.findContours(out_copy, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                if len(contours) > 0:
                    c = max(contours, key=cv2.contourArea)
                    valid_contours.append(c)


        out_pos = []
        previous_contours = contours
        for id, vc in enumerate(valid_contours):
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
            xy_dist = round(log10(1./float(w_im) + abs(pos - self._old_pos[id]))*1000)

            self._old_pos[id] = pos

            cv2.ellipse(self._buff_fg ,((x,y), (int(w*1.5),int(h*1.5)),angle),255,-1)

            id_var = IDVariable(id+1)
            x_var = XPosVariable(int(round(x)))
            y_var = YPosVariable(int(round(y)))
            distance = XYDistance(int(xy_dist))
            #xor_dist = XorDistance(int(xor_dist))
            w_var = WidthVariable(int(round(w)))
            h_var = HeightVariable(int(round(h)))
            phi_var = PhiVariable(int(round(angle)))
            # mlogl =   mLogLik(int(distance*1000))

            out = DataPoint([id_var, x_var, y_var, w_var, h_var,
                             phi_var,
                             #mlogl,
                             distance,
                             #xor_dist
                            #Label(0)
                             ])


            out_pos.append(out)


        if len(out_pos) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        cv2.bitwise_and(self._buff_fg_backup, self._buff_fg, self._buff_fg_backup)

        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)

        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)


        return out_pos