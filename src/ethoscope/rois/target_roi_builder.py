__author__ = 'quentin'

import cv2
import numpy as np
import logging
from ethoscope.rois.roi_builders import BaseROIBuilder, ROI
from ethoscope.utils.debug import EthoscopeException


class TargetGridROIBuilderBase(BaseROIBuilder):

    _adaptive_med_rad = 0.10
    _expected__min_target_dist = 10 # the minimal distance between two targets, in 'target diameter'
    _vertical_spacing = None
    _horizontal_spacing = None # the distance between 3 consecutive rois (proportion of target diameter)
    _n_rows = None
    _n_cols = None
    _horizontal_margin_left = .75 # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_top = -1.0 # from the center of the target to the external border (positive value makes grid larger)
    _horizontal_margin_right = _horizontal_margin_left # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_bottom = _vertical_margin_top # from the center of the target to the external border (positive value makes grid larger)



        ############# sort/name points as:


        #                            A
        #                            |
        #                            |
        #                            |
        # C------------------------- B

    # roi sorting =
    # 1 4 7
    # 2 5 8
    # 3 6 9


    def __init__(self):
        if self._vertical_spacing is None:
            raise NotImplementedError("_vertical_offset attribute cannot be None")
        if self._horizontal_spacing is None:
            raise NotImplementedError("_horizontal_offset attribute cannot be None")
        if self._n_rows is None:
            raise NotImplementedError("_n_rows attribute cannot be None")
        if self._n_cols is None:
            raise NotImplementedError("_n_cols attribute cannot be None")

    def _find_blobs(self, im, scoring_fun):
        grey= cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        rad = int(self._adaptive_med_rad * im.shape[1])
        if rad % 2 == 0:
            rad += 1

        med = np.median(grey)
        scale = 255/(med)
        cv2.multiply(grey,scale,dst=grey)
        bin = np.copy(grey)
        score_map = np.zeros_like(bin)
        for t in range(0, 255,5):
            cv2.threshold(grey, t, 255,cv2.THRESH_BINARY_INV,bin)
            if np.count_nonzero(bin) > 0.7 * im.shape[0] * im.shape[1]:
                continue
            contours, h = cv2.findContours(bin,cv2.RETR_EXTERNAL,cv2.cv.CV_CHAIN_APPROX_SIMPLE)
            bin.fill(0)
            for c in contours:
                score = scoring_fun(c, im)
                if score >0:
                    cv2.drawContours(bin,[c],0,score,-1)
            cv2.add(bin, score_map,score_map)
        return score_map

    def _add_margin_to_src_pts(self, pts, mean_diam):

        sign_mat = np.array([
            [+1, -1],
            [+1, +1],
            [-1, +1]

        ])

        margin = np.array([
            [mean_diam * self._horizontal_margin_right, mean_diam * self._vertical_margin_top],
            [mean_diam * self._horizontal_margin_right, mean_diam * self._vertical_margin_bottom],
            [mean_diam * self._horizontal_margin_left, mean_diam * self._vertical_margin_bottom]
        ])
        margin  =  sign_mat * margin
        pts = pts + margin.astype(pts.dtype)

        return pts

    def dist_pts(self, pt1, pt2):
        x1 , y1  = pt1
        x2 , y2  = pt2
        return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def _rois_from_img(self,img):

        map = self._find_blobs(img, self._score_targets)
        bin = np.zeros_like(map)

        # as soon as we have three objects, we stop
        for t in range(0, 255,1):
            cv2.threshold(map, t, 255,cv2.THRESH_BINARY  ,bin)
            contours, h = cv2.findContours(bin,cv2.RETR_EXTERNAL,cv2.cv.CV_CHAIN_APPROX_SIMPLE)

            if len(contours) <3:
                raise EthoscopeException("There should be three targets. Only %i objects have been found" % (len(contours)), img)
            if len(contours) == 3:
                break

        target_diams = [cv2.boundingRect(c)[2] for c in contours]

        mean_diam = np.mean(target_diams)
        mean_sd = np.std(target_diams)

        if mean_sd/mean_diam > 0.10:
            raise EthoscopeException("Too much variation in the diameter of the targets. Something must be wrong since all target should have the same size", img)

        src_points = []
        for c in contours:
            moms = cv2.moments(c)
            x , y = moms["m10"]/moms["m00"],  moms["m01"]/moms["m00"]

            src_points.append((x,y))



        a ,b, c = src_points
        pairs = [(a,b), (b,c), (a,c)]


        dists = [self.dist_pts(*p) for p in pairs]
        # that is the AC pair
        hypo_vertices = pairs[np.argmax(dists)]

        # this is B : the only point not in (a,c)
        for sp in src_points:
            if not sp in hypo_vertices:
                break

        sorted_b = sp


        dist = 0
        for sp in src_points:
            if sorted_b is sp:
                continue
            # b-c is the largest distance, so we can infer what point is c
            if self.dist_pts(sp, sorted_b) > dist:
                dist = self.dist_pts(sp, sorted_b)
                sorted_c = sp

        # the remaining point is a
        sorted_a = [sp for sp in src_points if not sp is sorted_b and not sp is sorted_c][0]

        sorted_src_pts = np.array([sorted_a, sorted_b, sorted_c], dtype=np.float32)

        sorted_src_pts = self._add_margin_to_src_pts(sorted_src_pts,mean_diam)

        dst_points = np.array([(0,-1),
                               (0,0),
                               (-1,0)], dtype=np.float32)


        wrap_mat = cv2.getAffineTransform(dst_points, sorted_src_pts)


        origin = np.array((sorted_src_pts[1][0],sorted_src_pts[1][1]), dtype=np.float32)

        rois = []
        val = 1

        fnrows = float(self._n_rows)
        fncols = float(self._n_cols)

        for j in range(self._n_cols):
            for i in range(self._n_rows):

                y = -1 + float(i)/fnrows
                x = -1 + float(j)/fncols


                pt1 = np.array([
                                x + self._horizontal_spacing,
                                y + self._vertical_spacing,0],
                    dtype=np.float32)

                pt2 = np.array([
                                x + self._horizontal_spacing,
                                y + 1./fnrows - self._vertical_spacing,0],
                    dtype=np.float32)

                pt4 = np.array([
                                x + 1./fncols - self._horizontal_spacing,
                                y + self._vertical_spacing,0],
                    dtype=np.float32)

                pt3 = np.array([
                                x + 1./fncols - self._horizontal_spacing,
                                y + 1./fnrows - self._vertical_spacing,0],
                   dtype=np.float32)

                pt1, pt2 = np.dot(wrap_mat, pt1),  np.dot(wrap_mat, pt2)
                pt3, pt4 = np.dot(wrap_mat, pt3),  np.dot(wrap_mat, pt4)
                pt1 += origin
                pt2 += origin
                pt3 += origin
                pt4 += origin
                pt1 = pt1.astype(np.int)
                pt2 = pt2.astype(np.int)
                pt3 = pt3.astype(np.int)
                pt4 = pt4.astype(np.int)

                ct = np.array([pt1,pt2, pt3, pt4]).reshape((1,4,2))
                rois.append(ROI(ct, value=val))

                cv2.drawContours(img,[ct], -1, (255,0,0),-1)
                val += 1
        return rois

    def _score_targets(self,contour, im):

        area = cv2.contourArea(contour)
        perim = cv2.arcLength(contour,True)

        if perim == 0:
            return 0
        circul =  4 * np.pi * area / perim ** 2

        if circul < .8: # fixme magic number
            return 0
        return 1


class SleepMonitorWithTargetROIBuilder(TargetGridROIBuilderBase):

    _vertical_spacing =  0.1/16.
    _horizontal_spacing =  .1/100.
    _n_rows = 16
    _n_cols = 2


class TubeMonitorWithTargetROIBuilder(TargetGridROIBuilderBase):


    _vertical_spacing =  .15/10.
    _horizontal_spacing =  .1/100.
    _n_rows = 10
    _n_cols = 2
    _horizontal_margin_left = .75 # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_top = -1.25 # from the center of the target to the external border (positive value makes grid larger)


class TargetArenaTest(TargetGridROIBuilderBase):

    _vertical_spacing =  .15/10.
    _horizontal_spacing =  .1/100.
    _horizontal_margin_left = .75 # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_top = -1.25 # from the center of the target to the external border (positive value makes grid larger)

    description = {"overview": "The default sleep monitor arena with ten rows of two tubes.",
                    "arguments": [
                                    {"type": "number", "min": 1, "max": 64, "step":1, "name": "n_cols", "description": "The number of columns","default":1},
                                    {"type": "number", "min": 1, "max": 64, "step":1, "name": "n_rows", "description": "The number of rows","default":1},
                                    {"type": "str", "name": "dummy_str", "description": "The number of rows","default":"Luis' easter egg"},
                                    {"type": "number", "min": -2.1, "max": 5.2, "step":0.01, "name": "dummy_float", "description": "Another dummy parameter to test","default":0.1},
                                    {"type": "datetime", "name": "dummy_datetime", "description": "Can we set a date","default":1441035646}
                                   ]}


    def __init__(self, n_cols, n_rows, dummy_datetime, dummy_str, dummy_float ):
        self._n_rows = n_rows
        self._n_cols = n_cols
        logging.warning(dummy_datetime)
        logging.warning(dummy_float)
        logging.warning(dummy_str)
        super(TargetArenaTest, self).__init__()


class WellsMonitorWithTargetROIBuilder(TargetGridROIBuilderBase):
    _vertical_spacing =  .9/100.
    _horizontal_spacing =  .6/100.
    _n_rows = 6
    _n_cols = 12
    _horizontal_margin_left = 0.5 # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_top = -1.6 # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_bottom = -1.6