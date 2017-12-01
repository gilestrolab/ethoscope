
import cv2
try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

try:
    from cv2 import CV_LOAD_IMAGE_GRAYSCALE as IMREAD_GRAYSCALE
except ImportError:
    from cv2 import IMREAD_GRAYSCALE

import numpy as np
from ethoscope.roi_builders.img_roi_builder import ImgMaskROIBuilder

from ethoscope.core.roi import ROI
import logging

class ArenaMaskROIBuilder(ImgMaskROIBuilder):

    def _find_target_coordinates(self, img):
        params = cv2.SimpleBlobDetector_Params()
        params.minThreshold = 10
        params.maxThreshold = 200

        #Filter by Area.
        params.filterByArea = True
        params.minArea = 300  #exclude the very small blobs
        params.maxArea = 10000

        # Filter by Circularity
        params.filterByCircularity = True
        params.minCircularity = 0.6

        # Filter by Convexity
        params.filterByConvexity = True
        params.minConvexity = 0.6

        # Filter by Inertia
        params.filterByInertia = True
        params.minInertiaRatio = 0.7

        if(CV_VERSION == 3):
            detector = cv2.SimpleBlobDetector_create(params)
        else:
            detector = cv2.SimpleBlobDetector(params)

        # we want to obtain an image with white background and dark targets on it
        #if we have a color image than we threshold it and transform in white everything that is not black
        #otherwise if we have a mask (black background and white on top we invert it)

        img = self._get_black_targets_white_background(img)

        keypoints = detector.detect(img)
        if np.size(keypoints) !=3:
            logging.error('Just %s targets found instead of three', np.size(keypoints))

        return keypoints

    def _get_black_targets_white_background(self, img):
        if len(img.shape) > 2:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            img = cv2.bitwise_not(img)

        #get an image that contains the pixels values that are black. The pixels values > 10 become white.
        ret, thresh = cv2.threshold(img, 10, 255, cv2.THRESH_BINARY)
        return thresh

    def _remove_targets(self, img):
        #select white pixels (targets always made with 255)
        #all the white pixels in the image become black
        white_pixels = img == 255
        img[white_pixels] = 0
        return img

    def _distance(self, keypoint1, keypoint2):
        return np.sqrt((keypoint1.pt[0] - keypoint2.pt[0]) ** 2 + (keypoint1.pt[1] - keypoint2.pt[1]) ** 2)

    def _sort(self, keypoints):
        #-----------A
        #-----------
        #C----------B

        a, b, c = keypoints
        pairs = [(a,b), (b,c), (a,c)]

        dists = [self._distance(*p) for p in pairs]

        # that is the AC pair
        ac_vertices = pairs[np.argmax(dists)]

        # this is B : the only point not in (a,c)
        for p in keypoints:
            if not p in ac_vertices:
                break
        sorted_b = p

        dist = 0
        for p in keypoints:
            if sorted_b is p:
                continue
            # b-c is the largest distance, so we can infer what point is c
            if self._distance(p, sorted_b) > dist:
                dist = self._distance(p, sorted_b)
                sorted_c = p

        # a is the remaining point
        sorted_a = np.setdiff1d(keypoints, [sorted_b, sorted_c])[0]
        return np.array([sorted_a.pt, sorted_b.pt, sorted_c.pt], dtype=np.float32)

    def _get_targets_sorted(self, img):
        targets = self._find_target_coordinates(img)
        targets_sorted = self._sort(targets)
        return targets_sorted

    def _get_corrected_mask_without_targets(self, img):
        rows, cols, _ = img.shape
        frame_targets_pts_sorted = self._get_targets_sorted(img)
        mask_target_pts_sorted = self._get_targets_sorted(self._mask)
        #cv2.circle(img, (frame_targets_pts_sorted[0][0], frame_targets_pts_sorted[0][1]), 10, (255, 0, 0), 10)
        #cv2.circle(img, (frame_targets_pts_sorted[1][0], frame_targets_pts_sorted[1][1]), 10, (0, 255, 0), 10)
        #cv2.circle(img, (frame_targets_pts_sorted[2][0], frame_targets_pts_sorted[2][1]), 10, (0, 0, 255), 10)
        #cv2.imshow('my img', img)
        #cv2.waitKey(0)
        targets_removed = self._remove_targets(self._mask)
        M = cv2.getAffineTransform(np.float32(mask_target_pts_sorted), np.float32(frame_targets_pts_sorted))
        mask_transformed = cv2.warpAffine(targets_removed, M, (cols, rows), flags=cv2.INTER_NEAREST,
                                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        return mask_transformed

    def _rois_from_img(self,img):
        corrected_mask = self._get_corrected_mask_without_targets(img)
        corrected_mask_edged = cv2.Canny(corrected_mask, 50, 100)
        cv2.GaussianBlur(corrected_mask_edged,(5,5),1.2, corrected_mask_edged)


        original_mask_edged = cv2.Canny(self._mask, 50, 100)


        if CV_VERSION == 3:
            _, contours_corrected_mask, hierarchy = cv2.findContours(np.copy(corrected_mask_edged),
                                                                     cv2.RETR_EXTERNAL,
                                                                     cv2.CHAIN_APPROX_SIMPLE)
            _, contours_original_mask, hierarchy_original_mask = cv2.findContours(np.copy(original_mask_edged),
                                                                                  cv2.RETR_EXTERNAL,
                                                                                  cv2.CHAIN_APPROX_SIMPLE)

        else:
            contours_corrected_mask, hierarchy = cv2.findContours(np.copy(corrected_mask_edged),
                                                                  cv2.RETR_EXTERNAL,
                                                                  cv2.CHAIN_APPROX_SIMPLE)
            contours_original_mask, hierarchy_original_mask = cv2.findContours(np.copy(original_mask_edged),
                                                                                  cv2.RETR_EXTERNAL,
                                                                                  cv2.CHAIN_APPROX_SIMPLE)

        if (len(contours_corrected_mask) != len(contours_original_mask)):
            raise ValueError('The mask does not fit the video! The proportions of distances are not right! '
                          'Please generate the mask using the original arena targets, rois and subrois!')


        rois = []

        for i,c in enumerate(contours_corrected_mask):
            x, y, w, h = cv2.boundingRect(c)
            sub_rois = corrected_mask[y : y + h, x : x + w]
            rois.append(ROI(c, i+1, value=None, sub_rois=sub_rois))
        return rois