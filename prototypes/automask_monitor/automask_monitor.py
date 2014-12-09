__author__ = 'quentin'

from pysolovideo.tracking.roi_builders import BaseROIBuilder
from pysolovideo.utils.debug import show

import numpy as np
import cv2


class SleepMonitorWithTargetROIBuilder(BaseROIBuilder):
    _expected__min_target_dist = 10 # the minimal distance between two targets, in 'target diameter'

    _adaptive_med_rad = 0.10

    def _find_blobs(self, im, scoring_fun):
        grey= cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        rad = int(self._adaptive_med_rad * im.shape[1])
        if rad % 2 == 0:
            rad += 1


        # med = cv2.medianBlur(grey, rad)
        # cv2.subtract(med, grey, dst = med)
        #

        #
        bin = np.copy(grey)
        score_map = np.zeros_like(bin)
        for t in range(0, 255,1):
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





    def _rois_from_img(self,img):
        map = self._find_blobs(img, self._score_targets)
        bin = np.zeros_like(map)

        # as soon as we have three objects, we stop

        for t in range(0, 255,1):
            cv2.threshold(map, t, 255,cv2.THRESH_BINARY  ,bin)

            contours, h = cv2.findContours(bin,cv2.RETR_EXTERNAL,cv2.cv.CV_CHAIN_APPROX_SIMPLE)

            if len(contours) <3:
                raise Exception("There should be three targets. Only %i objects have been found" % (len(contours)))
            if len(contours) == 3:
                break
        #cv2.threshold(map, t, 255,cv2.THRESH_BINARY , map)

        target_diams = [cv2.boundingRect(c)[2] for c in contours]

        mean_diam = np.mean(target_diams)
        mean_sd = np.std(target_diams)

        if mean_sd/mean_diam > 0.05:
            raise Exception("Two much variation in the diameter of the targets. Something must be wrong since all target should have the same size")



        src_points = []
        for c in contours:
            moms = cv2.moments(c)
            x , y = moms["m10"]/moms["m00"],  moms["m01"]/moms["m00"]
            src_points.append((x,y))

        # todo sort src_points ? ABC
        src_points = np.array(src_points, dtype=np.float32)

        print src_points

        # dst_points = np.array([(0,1),
        #                        (0,0),
        #                        (1,0)], dtype=np.float32)

        dst_points = np.array([(0,1),
                               (1,0),
                               (0,0)], dtype=np.float32)

        wrap_mat = cv2.getAffineTransform(dst_points, src_points)

        lines_to_draw = []
        for i in range(16 + 1):
            x = float(i)/17.0
            y = 0
            pt1 = np.array([x,y,0], dtype=np.float32)
            pt2 = np.array([x,y,1], dtype=np.float32)
            a, b = np.dot(wrap_mat, pt1).astype(np.int), np.dot(wrap_mat, pt2).astype(np.int)
            # print a,b
            cv2.line(img, tuple(a), tuple(b), (255,255,0),3)






        show(img)


    def _score_targets(self,contour, im):

        area = cv2.contourArea(contour)
        perim = cv2.arcLength(contour,True)

        if perim == 0:
            return 0
        circul =  4 * np.pi * area / perim ** 2

        if circul < .8: # fixme magic number
            return 0
        return 1


im = cv2.imread("./shot0004.png")
rbuilder = SleepMonitorWithTargetROIBuilder()
rbuilder(im)


