__author__ = 'quentin'
from .adaptive_bg_tracker import AdaptiveBGModel, BackgroundModel, ObjectModel
from collections import deque
from math import log10
import cv2
CV_VERSION = int(cv2.__version__.split(".")[0])

import numpy as np
from scipy import ndimage
from scipy.spatial import distance

from ethoscope.core.variables import XPosVariable, YPosVariable, XYDistance, WidthVariable, HeightVariable, PhiVariable, Label
from ethoscope.core.data_point import DataPoint
from ethoscope.trackers.trackers import BaseTracker, NoPositionError
from ethoscope.utils.debug import EthoscopeException
import logging

import matplotlib
import matplotlib.pyplot as plt


class ForegroundModel(object):
    
    def __init__( self, sample_size=400, normal_limits=(50, 200), visualise=False, tolerance = 0.8 ):
        '''
        set the size of the statistical sample for the running average and the hard limits to populate the sample
        :param sample_size: the size of the sample used for the statiscal model
        :type sample_size: int
        :param normal_limits: a tuple indicating the limits to use to initially populate the sample
        :type normal_limits: tuple
        :param visualise: shows a real time graph of the characteristics of the sample
        :type visualise: bool
        :param tolerance: tolerance factor to be used to decide if contour is an outlier
        :type tolerance: float

        :return:
        '''
        
        self.sample_size = sample_size
        self.normal_limits = normal_limits
        self.tolerance = tolerance
        
        self.limited_pool = deque(maxlen = sample_size)
        self.total_pool = []
        
        self._visualise = visualise

        if self._visualise:
            plt.ion()
            self.fig, (self.ax1, self.ax2)  = plt.subplots(1,2)
            self.fig.suptitle('Live analysis of contours - sample size %s - tolerance %s' % (sample_size, tolerance))

    def _is_outlier(self, value, tolerance=0.7):
        '''
        Not intended as statistical outlier (we don't compare against std)
        Anything bigger or smaller than tolerance * mean is excluded
        '''
        return abs(value - np.mean(self.limited_pool)) > tolerance * np.mean(self.limited_pool)
    
    def is_contour_valid(self, contour, img):
        
        area = cv2.contourArea(contour)

        mean = np.mean(self.limited_pool)
        std = np.std(self.limited_pool)

        self.total_pool.append(area)

        if self._visualise and len(self.total_pool) % 1000 == 0:

            # refresh plot every 1000 contours received
            self.ax1.clear() # not sure why I need to clear the axis here. In principle it should not be necessary.
            self.ax2.clear()
            self.ax1.set_title('All contours')
            self.ax2.set_title('Within limits')

            self.bp1 = self.ax1.boxplot(self.total_pool)
            self.bp2 = self.ax2.boxplot(self.limited_pool)

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

        # The initial phase. This is not completely agnostic: we add everything to the training pool as long as it is within the reasonable limits
        # Limits are quite loose though and refinement happens during the actual tracking
        if len(self.limited_pool) < self.sample_size and area >= self.normal_limits[0] and area <= self.normal_limits[1]:
            self.limited_pool.append(area)
            return True
       
        # Once we have a running queue, we add everything that is not an outlier
        if not self._is_outlier(area, tolerance=self.tolerance):
            self.limited_pool.append(area)
            return True
        
        else:
            return False


class MultiFlyTracker(BaseTracker):
    _description = {"overview": "An experimental tracker to monitor several animals per ROI.",
                    "arguments": []}



    def __init__(self, roi, data=None, maxN=50):
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
        
        self.maxN = maxN
        self.last_positions = np.zeros((self.maxN,2))

        self._debug = False
        
        if self._debug:
            self.multi_fly_tracker_window = "tracking_preview"
            cv2.namedWindow(self.multi_fly_tracker_window, cv2.WINDOW_AUTOSIZE)

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
        cv2.GaussianBlur(self._buff_grey,(blur_rad,blur_rad),1.2, self._buff_grey)
        if darker_fg:
            cv2.subtract(255, self._buff_grey, self._buff_grey)

        mean = cv2.mean(self._buff_grey, mask)

        scale = 128. / mean[0]

        cv2.multiply(self._buff_grey, scale, dst = self._buff_grey)


        if mask is not None:
            cv2.bitwise_and(self._buff_grey, mask, self._buff_grey)
            return self._buff_grey

    def _closest_node(self, node, nodes):
        '''
        Find the closest distance between node and the vector of nodes
        Returns the value found and its index in nodes
        '''
        d = distance.cdist([node], nodes)
        return d.min(), d.argmin()

    def _find_position(self, img, mask,t):

        grey = self._pre_process_input_minimal(img, mask, t)
        try:
            return self._track(img, grey, mask, t)
        except NoPositionError:
            self._bg_model.update(grey, t)
            raise NoPositionError


    def _track(self, img,  grey, mask,t):
        '''
        The tracking routine
        Runs once per ROI
        '''

        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
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

        valid_contours = []

        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        else :
            for c in contours:
                if self._fg_model.is_contour_valid(c, img):
                    valid_contours.append(c)

        if len(valid_contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        out_pos = []
        raw_pos = []
        
        for n_vc, vc in enumerate(valid_contours):
            
            #calculates the parameters to draw the centroid
            (x,y) ,(w,h), angle  = cv2.minAreaRect(vc)
            
            #adjust the orientation for consistency
            if w < h:
                angle -= 90
                w,h = h,w
            angle = angle % 180

            #ignore if the ellipse is drawn outside the actual picture
            h_im = min(grey.shape)
            w_im = max(grey.shape)
            max_h = 2*h_im
            if w>max_h or h>max_h:
                continue
                
            pos = x +1.0j*y
            pos /= w_im

            #draw the ellipse around the blob
            cv2.ellipse(self._buff_fg , ((x,y), (int(w*1.5),int(h*1.5)),angle), 255, 1)

            ## Some debugging info
            ##contour_area = cv2.contourArea(vc)
            ##contour_moments = cv2.moments(vc)
            
            ##cX = int(contour_moments["m10"] / contour_moments["m00"])
            ##cY = int(contour_moments["m01"] / contour_moments["m00"])
            ##contour_crentroid = (cX, cY) # this is actually the same as x,y - so pointless to calculate
            
            # # idx = 0
            # # nf = 0
            # # d = 0
            # # ox = 0
            # # oy = 0
            # # if not self._firstrun:
                # # d, idx = self._closest_node((x, y), self.last_positions)
                # # print (d, idx)
                
                # # self.last_positions[idx] = [x,y]

                # # if d < 10:
                    # # nf = idx
                    # # ox, oy = self.last_positions[idx]

                # # else: 
                    # # nf = "new"
            
            # # label = "%s: %.1f" % (nf, d)
            # # cv2.putText(self._buff_fg , label, (cX, cY), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 1)

            # # cv2.circle(self._buff_fg, (cX, cY), 3, (255, 0, 0), -1)
            # # cv2.drawMarker(self._buff_fg, (int(ox), int(oy)), (255, 0, 0), cv2.MARKER_CROSS, 10)

            # store the blob info in a list
            x_var = XPosVariable(int(round(x)))
            y_var = YPosVariable(int(round(y)))
            w_var = WidthVariable(int(round(w)))
            h_var = HeightVariable(int(round(h)))
            phi_var = PhiVariable(int(round(angle)))
            
            raw = (x, y, w, h, angle)
            raw_pos.append(raw)
            
            
            out = DataPoint([ x_var, y_var, w_var, h_var, phi_var ])
            out_pos.append(out)

        # end the for loop iterating within contours

        if self._debug:
            cv2.imshow( self.multi_fly_tracker_window, self._buff_fg )
        
        if len(out_pos) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        cv2.bitwise_and(self._buff_fg_backup, self._buff_fg,self._buff_fg_backup)


        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)

        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)


        return out_pos
