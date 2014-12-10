__author__ = 'quentin'

from pysolovideo.tracking.roi_builders import BaseROIBuilder
from pysolovideo.tracking.roi_builders import ROI


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
                raise Exception("There should be three targets. Only %i objects have been found" % (len(contours)))
            if len(contours) == 3:
                break

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


        ############# sort/name points as:

        # B--------------------------C
        # |
        # |
        # |
        # A

        a ,b, c = src_points
        pairs = [(a,b), (b,c), (a,c)]


        dists = [ self.dist_pts(*p) for p in pairs]
        hypo_vertices = pairs[np.argmax(dists)]


        for sp in src_points:
            if not sp in hypo_vertices:

                break

        sorted_b = sp


        dist = 0
        for sp in src_points:
            if sorted_b is sp:
                continue
            if self.dist_pts(sp, sorted_b) > dist:
                dist = self.dist_pts(sp, sorted_b)
                sorted_c = sp

        sorted_a = [sp for sp in src_points if not sp is sorted_b and not sp is sorted_c][0]







        sorted_src_pts = np.array([sorted_a, sorted_b, sorted_c], dtype=np.float32)
        sorted_src_pts += [
                            [-mean_diam/2.,-mean_diam], # IMPORTANT A is not touching the grove, so we add + one radius
                            [-mean_diam/2.,mean_diam/2.],
                            [mean_diam/2.,mean_diam/2.]
                          ]


        dst_points = np.array([(0,1),
                               (0,0),
                               (1,0)], dtype=np.float32)


        wrap_mat = cv2.getAffineTransform(dst_points, sorted_src_pts)


        origin = np.array(sorted_src_pts[1], dtype=np.float32)


        rois = []
        val = 0
        for left in (True,False):
            for i in range(16):
                y = float(i)/16.0

                if left:
                    x = 0.
                else:
                    x = 0.5
                pt1 = np.array([x,y,0], dtype=np.float32)
                pt2 = np.array([x,y + 1./16.,0], dtype=np.float32)

                if left:
                    x = 0.5
                else:
                    x = 1.0

                pt4 = np.array([x,y,0], dtype=np.float32)
                pt3 = np.array([x,y + 1./16.,0], dtype=np.float32)


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


im = cv2.imread("./shot0003.png")
rbuilder = SleepMonitorWithTargetROIBuilder()
rois = rbuilder(im)




