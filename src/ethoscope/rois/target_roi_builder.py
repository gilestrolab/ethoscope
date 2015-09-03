__author__ = 'quentin'

import cv2
import numpy as np
import logging
from ethoscope.rois.roi_builders import BaseROIBuilder, ROI
from ethoscope.utils.debug import EthoscopeException
import itertools

class TargetGridROIBuilderBase(BaseROIBuilder):

    _adaptive_med_rad = 0.10
    _expected__min_target_dist = 10 # the minimal distance between two targets, in 'target diameter'
    _n_rows = 10
    _n_cols = 2
    _top_margin =  0
    _bottom_margin = None
    _left_margin = 0
    _right_margin = None
    _horizontal_fill = 1
    _vertical_fill = None


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
        if self._vertical_fill is None:
            self._vertical_fill = self._horizontal_fill
        if self._right_margin is None:
            self._right_margin = self._left_margin
        if self._bottom_margin is None:
            self._bottom_margin = self._top_margin

        super(TargetGridROIBuilderBase,self).__init__()


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

    def _make_grid(self, n_col, n_row,
              top_margin=0.0, bottom_margin=0.0,
              left_margin=0.0, right_margin=0.0,
              horizontal_fill = 1.0, vertical_fill=1.0):

        y_positions = (np.arange(n_row) * 2.0 + 1) * (1-top_margin-bottom_margin)/(2*n_row) + top_margin
        x_positions = (np.arange(n_col) * 2.0 + 1) * (1-left_margin-right_margin)/(2*n_col) + left_margin
        all_centres = [np.array([x,y]) for x,y in itertools.product(x_positions, y_positions)]

        sign_mat = np.array([
            [-1, -1],
            [+1, -1],
            [+1, +1],
            [-1, +1]

        ])
        xy_size_vec = np.array([horizontal_fill/float(n_col), vertical_fill/float(n_row)]) / 2.0
        rectangles = [sign_mat *xy_size_vec + c for c in all_centres]
        return rectangles


    def dist_pts(self, pt1, pt2):
        x1 , y1  = pt1
        x2 , y2  = pt2
        return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def _score_targets(self,contour, im):

        area = cv2.contourArea(contour)
        perim = cv2.arcLength(contour,True)

        if perim == 0:
            return 0
        circul =  4 * np.pi * area / perim ** 2

        if circul < .8: # fixme magic number
            return 0
        return 1

    def _find_target_coordinates(self, img):
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
        # cv2.imshow("map",map); cv2.waitKey(-1)

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
        return sorted_src_pts

    def _rois_from_img(self,img):
        sorted_src_pts = self._find_target_coordinates(img)
        dst_points = np.array([(0,-1),
                               (0,0),
                               (-1,0)], dtype=np.float32)
        wrap_mat = cv2.getAffineTransform(dst_points, sorted_src_pts)

        rectangles = self._make_grid(self._n_cols, self._n_rows,
                                     self._top_margin, self._bottom_margin,
                                     self._left_margin,self._right_margin,
                                     self._horizontal_fill, self._vertical_fill)

        shift = np.dot(wrap_mat, [1,1,0]) - sorted_src_pts[1] # point 1 is the ref, at 0,0
        rois = []
        for i,r in enumerate(rectangles):
            r = np.append(r, np.zeros((4,1)), axis=1)
            mapped_rectangle = np.dot(wrap_mat, r.T).T
            mapped_rectangle -= shift
            ct = mapped_rectangle.reshape((1,4,2)).astype(np.int32)
            cv2.drawContours(img,[ct], -1, (255,0,0),1,cv2.CV_AA)
            rois.append(ROI(ct, value=i+1))
            # cv2.imshow("dbg",img)
            # cv2.waitKey(0)
        return rois

class TargetGridROIBuilder(TargetGridROIBuilderBase):

    description = {"overview": "A flexible ROI builder that allows users to select parameters for the ROI layout."
                               "Lengths are relative to the distance between the two bottom targets (width)",
                    "arguments": [
                                    {"type": "number", "min": 1, "max": 16, "step":1, "name": "n_cols", "description": "The number of columns","default":1},
                                    {"type": "number", "min": 1, "max": 16, "step":1, "name": "n_rows", "description": "The number of rows","default":1},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "top_margin", "description": "The vertical distance between the middle of the top ROIs and the middle of the top target.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "bottom_margin", "description": "Same as top_margin, but for the bottom.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "right_margin", "description": "Same as top_margin, but for the right.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "left_margin", "description": "Same as top_margin, but for the left.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "horizontal_fill", "description": "The proportion of the grid space user by the roi, horizontally.","default":0.90},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "left_margin", "description": "Same as horizontal_margin, but vertically.","default":0.90}
                                   ]}
    def __init__(self, n_rows=1, n_cols=1, top_margin=0, bottom_margin=0,
                 left_margin=0, right_margin=0, horizontal_fill=.9, vertical_fill=.9):
        self._n_rows = n_rows
        self._n_cols = n_cols
        self._top_margin =  top_margin
        self._bottom_margin = bottom_margin
        self._left_margin = left_margin
        self._right_margin = right_margin
        self._horizontal_fill = horizontal_fill
        self._vertical_fill = vertical_fill

        super(TargetGridROIBuilder,self).__init__()

class SleepMonitorWithTargetROIBuilder(TargetGridROIBuilderBase):
    description = {"overview": "The default sleep monitor arena with ten rows of two tubes.",
                    "arguments": []}
    _n_rows = 10
    _n_cols = 2
    _top_margin =  6.99 / 111.00
    _horizontal_fill = .9
    _vertical_fill = .7

class OlfactionAssayROIBuilder(TargetGridROIBuilderBase):
    description = {"overview": "The default odor assay  roi layout with ten rows of single tubes.",
                    "arguments": []}
    _n_rows = 10
    _n_cols = 1
    _top_margin =  6.99 / 111.00
    _horizontal_fill = .9
    _vertical_fill = .7
