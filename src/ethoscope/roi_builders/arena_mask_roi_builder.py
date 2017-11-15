
import cv2
try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

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
        params.minArea = 100  #exclude the very small blobs
        params.maxArea = 10000

        # Filter by Circularity
        params.filterByCircularity = True
        params.minCircularity = 0.7

        # Filter by Convexity
        params.filterByConvexity = True
        params.minConvexity = 0.7

        # Filter by Inertia
        params.filterByInertia = True
        params.minInertiaRatio = 0.7

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

    def _sort(self, keypoints):
        #-----------A
        #-----------
        #C----------B
        # initialize the three targets that we want to found
        sorted_a = cv2.KeyPoint()
        sorted_b = cv2.KeyPoint()
        sorted_c = cv2.KeyPoint()


        # find the minimum x and the minimum y coordinate between the three targets
        minx = min(keypoint.pt[0] for keypoint in keypoints)
        miny = min(keypoint.pt[1] for keypoint in keypoints)

        # sort the targets; c is the target that has minimum x and a is the target that has minimum y

        for keypoint in keypoints:
            if keypoint.pt[0] == minx:
                sorted_c = keypoint
            if keypoint.pt[1] == miny:
                sorted_a = keypoint

        # b is the remaining point
        sorted_b = np.setdiff1d(keypoints, [sorted_a, sorted_c])[0]

        return np.array([sorted_a.pt, sorted_b.pt, sorted_c.pt], dtype=np.float32)

    def _get_targets_sorted(self, img):
        targets = self._find_target_coordinates(img)
        targets_sorted = self._sort(targets)
        return targets_sorted

    def _get_corrected_mask_without_targets(self, img):
        rows, cols, _ = img.shape
        frame_targets_pts_sorted = self._get_targets_sorted(img)
        mask_target_pts_sorted = self._get_targets_sorted(self._mask)
        targets_removed = self._remove_targets(self._mask)
        M = cv2.getAffineTransform(np.float32(mask_target_pts_sorted), np.float32(frame_targets_pts_sorted))
        mask_transformed = cv2.warpAffine(targets_removed, M, (cols, rows), flags=cv2.INTER_NEAREST)
        return mask_transformed

    def _rois_from_img(self,img):
        corrected_mask = self._get_corrected_mask_without_targets(img)
        edged = cv2.Canny(corrected_mask, 50, 100)
        if CV_VERSION == 3:
            _, contours, hierarchy = cv2.findContours(np.copy(edged), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        else:
            contours, hierarchy = cv2.findContours(np.copy(edged), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        rois = []

        for i,c in enumerate(contours):
            x, y, w, h = cv2.boundingRect(c)
            sub_rois = corrected_mask[y : y + h, x : x + w]
            rois.append(ROI(c, i+1, value=None, sub_rois=sub_rois))
        return rois