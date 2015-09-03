__author__ = 'quentin'

import cv2
import numpy as np
from ethoscope.rois.roi_builders import BaseROIBuilder


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
        cv2.imshow("map",map); cv2.waitKey(-1)

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

        print sorted_src_pts

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



from ethoscope.hardware.input.cameras import MovieVirtualCamera
test_rb = TargetGridROIBuilderBase()



import itertools
def make_grid(n_col, n_row,
              top_margin=0, bottom_margin=0,
              left_margin=0, right_margin=0,
              horizontal_fill = 1, vertical_fill=1):

    y_positions = (np.arange(n_row) * 2.0 + 1) * (1-top_margin-bottom_margin)/(2*n_row) + top_margin
    x_positions = (np.arange(n_col) * 2.0 + 1) * (1-left_margin-right_margin)/(2*n_col) + left_margin

    all_centres = [np.array([x,y]) for y,x in itertools.product(y_positions, x_positions)]


    sign_mat = np.array([
        [-1, -1],
        [+1, -1],
        [+1, +1],
        [-1, +1]

    ])

    sign_mat = (sign_mat/2) * np.array([horizontal_fill, vertical_fill])
    xy_size_vec = np.array([1.0/n_col,1.0/n_row])
    rectangles = [sign_mat *xy_size_vec + c for c in all_centres]
    return rectangles

make_grid(2,3)


#cam = MovieVirtualCamera("/data/psv_misc/tube_monitor_validation/tube_monitor_validation_raw.mp4")

#test_rb(cam)

