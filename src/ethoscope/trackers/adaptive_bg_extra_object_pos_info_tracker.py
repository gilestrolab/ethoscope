
import cv2
try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

import numpy as np
from scipy import ndimage
from ethoscope.core.variables import XPosVariable, YPosVariable, XYDistance, WidthVariable, HeightVariable, PhiVariable, \
                                        SubRoiValueObjectCenterVariable
from ethoscope.core.data_point import DataPoint
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel, NoPositionError
from math import log10
from ethoscope.core.variables import BaseIntVariable

##Extra variables to be added in the database for this tracker
class SubRoi1ValueVariable(BaseIntVariable):
    """
    Type encoding the sub-roi inside the ROI, that contains the maximum number of the objects's pixels.
    It can contain all the pixels belonging to the object in which case, the object is completely inside this sub-roi.
    This variable is particularly useful when the object is between subrois.
    """
    sql_data_type = "TINYINT UNSIGNED"
    header_name = "sub_roi1"
    functional_type = "grey_value"

class SubRoi2ValueVariable(BaseIntVariable):
    """
    Type encoding the sub-roi inside the ROI, that contains the second biggest number of the objects's pixels.
    If the object is completly contained in one subroi then this variable is 0.
    This variable is particularly useful when the object is between subrois.
    """
    sql_data_type = "TINYINT UNSIGNED"
    header_name = "sub_roi2"
    functional_type = "grey_value"

class NPixelsSubRoi1Variable(BaseIntVariable):
    """
    Type encoding the number of pixels of the object that sits in the first sub-roi.
    """
    header_name = "n_px_sub_roi_1"
    functional_type = "nr_pixels"

class NPixelsSubRoi2Variable(BaseIntVariable):
    """
    Type encoding the number of pixels of the object that sits in the second sub-roi.
    """
    header_name = "n_px_sub_roi_2"
    functional_type = "nr_pixels"

class NPxObjectVariable(BaseIntVariable):
    """
    Type encoding the total number of pixels of the object.
    """
    header_name = "total_n_px"
    functional_type = "nr_pixels"


class AdaptiveBGModelExtraObjectPosInfo(AdaptiveBGModel):
    _description = {"overview": "The default tracker for fruit flies. One animal per ROI.",
                    "arguments": []}


    def _track(self, img,  grey, mask,t):

        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            self._buff_object= np.empty_like(grey)
            self._buff_fg_backup = np.empty_like(grey)
  #          self._buff_fg_diff = np.empty_like(grey)
            self._old_pos = 0.0 +0.0j
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

        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        elif len(contours) > 1:
            if not self.fg_model.is_ready:
                raise NoPositionError
            # hulls = [cv2.convexHull( c) for c in contours]
            hulls = contours
            #hulls = merge_blobs(hulls)

            hulls = [h for h in hulls if h.shape[0] >= 3]

            if len(hulls) < 1:
                raise NoPositionError

            elif len(hulls) > 1:
                is_ambiguous = True
            cluster_features = [self.fg_model.compute_features(img, h) for h in hulls]
            all_distances = [self.fg_model.distance(cf,t) for cf in cluster_features]
            good_clust = np.argmin(all_distances)

            hull = hulls[good_clust]
            distance = all_distances[good_clust]
        else:
            hull = contours[0]
            if hull.shape[0] < 3:
                self._bg_model.increase_learning_rate()
                raise NoPositionError

            features = self.fg_model.compute_features(img, hull)
            distance = self.fg_model.distance(features,t)

        if distance > self._max_m_log_lik:
            self._bg_model.increase_learning_rate()
            raise NoPositionError


        (x,y) ,(w,h), angle  = cv2.minAreaRect(hull)

        if w < h:
            angle -= 90
            w,h = h,w
        angle = angle % 180

        h_im = min(grey.shape)
        w_im = max(grey.shape)
        max_h = 2*h_im
        if w>max_h or h>max_h:
            raise NoPositionError

        cv2.ellipse(self._buff_fg ,((x,y), (int(w*1.5),int(h*1.5)),angle),255,-1)

        cv2.imshow('elipse', self._buff_fg)
        #cv2.waitKey(0)

        #todo center mass just on the ellipse area

        #extract the fly pixels and map them to the sub-rois mask in order to get information about the proportions of the fly in each subroi
        grey_object = self._buff_fg_backup


        cv2.bitwise_and(self._buff_fg_backup, self._buff_fg,self._buff_fg_backup)

        y,x = ndimage.measurements.center_of_mass(self._buff_fg_backup)

        pos = x +1.0j*y
        pos /= w_im

        xy_dist = round(log10(1./float(w_im) + abs(pos - self._old_pos))*1000)

        # cv2.bitwise_and(self._buff_fg_diff,self._buff_fg,dst=self._buff_fg_diff)
        # sum_diff = cv2.countNonZero(self._buff_fg_diff)
        # xor_dist = (sum_fg  + self._old_sum_fg - 2*sum_diff)  / float(sum_fg  + self._old_sum_fg)
        # xor_dist *=1000.
        # self._old_sum_fg = sum_fg
        self._old_pos = pos

        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask,  self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)
        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)

        self.fg_model.update(img, hull,t)

        x_var = XPosVariable(int(round(x)))
        y_var = YPosVariable(int(round(y)))
        distance = XYDistance(int(xy_dist))
        #xor_dist = XorDistance(int(xor_dist))
        w_var = WidthVariable(int(round(w)))
        h_var = HeightVariable(int(round(h)))
        phi_var = PhiVariable(int(round(angle)))
        # mlogl =   mLogLik(int(distance*1000))

        total_px_object = np.count_nonzero(grey_object)

        x_ind, y_ind = grey_object.nonzero()
        grey_object[x_ind, y_ind] = self._roi.find_sub_roi(y_ind, x_ind)

        histg = cv2.calcHist([grey_object[x_ind, y_ind]],[0],None,[256],[0,256])
        nonzeroind = np.nonzero(histg)[0] # the return is a little funny so I use the [0]
        print nonzeroind
        obj_sub_rois = nonzeroind
        n_pixels_in_subrois = histg[nonzeroind].flatten()
        n_pixels_in_subrois = [int(x) for x in n_pixels_in_subrois]


        if (len(obj_sub_rois)==1):
            sub_roi_1_grey_var = SubRoi1ValueVariable(obj_sub_rois[0])
            n_pixels_sub_roi_1 = NPixelsSubRoi1Variable(n_pixels_in_subrois[0])
            sub_roi_2_grey_var = SubRoi2ValueVariable(0)
            n_pixels_sub_roi_2 = NPixelsSubRoi2Variable(0)
        elif (len(obj_sub_rois) > 1):
            matched = zip(n_pixels_in_subrois, obj_sub_rois)
            sorted_n_pixels =sorted(matched, reverse=True)
            n_pixels_sorted = [point[0] for point in sorted_n_pixels]
            sub_rois_sorted = [point[1] for point in sorted_n_pixels]
            sub_roi_1_grey_var = SubRoi1ValueVariable(sub_rois_sorted[0])
            n_pixels_sub_roi_1 = NPixelsSubRoi1Variable(n_pixels_sorted[0])
            sub_roi_2_grey_var = SubRoi2ValueVariable(sub_rois_sorted[1])
            n_pixels_sub_roi_2 = NPixelsSubRoi2Variable(n_pixels_sorted[1])

        grey_value = self._roi.find_sub_roi(x_var, y_var)
        sub_roi_center = SubRoiValueObjectCenterVariable(grey_value)
        total_px_obj = NPxObjectVariable(total_px_object)

        out = DataPoint([x_var, y_var, w_var, h_var,
                         phi_var,
                         #mlogl,
                         distance,
                         #xor_dist
                        #Label(0)
                         sub_roi_center,
                         total_px_obj,
                         sub_roi_1_grey_var,
                         n_pixels_sub_roi_1,
                         sub_roi_2_grey_var,
                         n_pixels_sub_roi_2
                         ])


        self._previous_shape=np.copy(hull)
        return [out]
