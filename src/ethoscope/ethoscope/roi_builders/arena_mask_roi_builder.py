__author__ = "diana"

import cv2

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

import numpy as np
import logging

from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI


class ArenaMaskROIBuilder(BaseROIBuilder):

    def __init__(self, mask_path):
        """
        Class to build rois from greyscale image file.
        Each rectangular region found at level 0 in the hierarchy of contours defines a ROI (All childs are excluded).
        """

        self._mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

        super(ArenaMaskROIBuilder, self).__init__()

    def _find_target_coordinates(self, img):
        params = cv2.SimpleBlobDetector_Params()
        # Change thresholds
        params.minThreshold = 0
        params.maxThreshold = 100

        # Filter by Area.
        params.filterByArea = True
        params.minArea = 1000
        params.maxArea = 10000

        # Filter by Circularity
        params.filterByCircularity = True
        params.minCircularity = 0.6

        # Filter by Convexity
        params.filterByConvexity = True
        params.minConvexity = 0.3
        #
        # # Filter by Inertia
        # params.filterByInertia = True
        # params.minInertiaRatio = 0.01

        detector = cv2.SimpleBlobDetector(params)

        # cv2.imshow('here', img)
        # cv2.waitKey(0)

        keypoints = detector.detect(img)

        if np.size(keypoints) != 3:
            logging.error("Just %s targets found instead of three", np.size(keypoints))

        return keypoints

    def _sort(keypoints):
        # -----------A
        # -----------
        # C----------B
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

    def _get_corrected_mask(self, img):
        frame_targets_pts_sorted = self._get_targets_sorted(self, img)
        mask_target_pts_sorted = self._get_targets_sorted(self, self._mask)
        M = cv2.getAffineTransform(
            np.float32(mask_target_pts_sorted), np.float32(frame_targets_pts_sorted)
        )
        cols, rows, _ = self._mask.shape
        mask_transformed = cv2.warpAffine(self._mask, M, (cols, rows))
        return mask_transformed

    def _is_contour_rectangular(c):
        # approximate the contour
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        # the contour is 'bad' if it is not a rectangle
        return len(approx) == 4

    def _rois_from_img(self, img):
        corrected_mask = self._get_corrected_mask(self, self._mask)
        # get all external contours
        if CV_VERSION == 3:
            _, contours, hierarchy = cv2.findContours(
                np.copy(corrected_mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
        else:
            contours, hierarchy = cv2.findContours(
                np.copy(corrected_mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

        rois = []

        for i, c in enumerate(contours):
            if self._is_contour_rectangular(c):
                tmp_mask = np.zeros_like(corrected_mask)
                cv2.drawContours(tmp_mask, [c], 0, 1)

                if CV_VERSION == 3:
                    _, sub_contours, sub_hierarchy = cv2.findContours(
                        np.copy(tmp_mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                else:
                    sub_contours, sub_hierarchy = cv2.findContours(
                        np.copy(tmp_mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )

                rois.append(
                    ROI(
                        c,
                        i + 1,
                        value=None,
                        regions=sub_contours,
                        hierarchy=sub_hierarchy,
                    )
                )

        return rois
