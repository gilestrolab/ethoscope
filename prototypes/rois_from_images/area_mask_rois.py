__author__ = 'diana'

import cv2
from ethoscope.utils.debug import EthoscopeException


try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

from ethoscope.core.monitor import Monitor
import cv2
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel, ObjectModel
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
import numpy as np
import logging
#from ethoscope.core.roi import ROI

class ROI(object):

    def __init__(self, polygon, idx, value=None, orientation = None, regions=None, hierarchy=None):
        """
        Class to define a region of interest(ROI).
        Internally, ROIs are single polygons.
        At the moment, they cannot have any holes.
        The polygon defining the ROI is used to draw a mask to exclude off-target pixels (so cross-ROI info).

        :param polygon: An array of points
        :type polygon: :class:`~numpy.ndarray`
        :param idx: the index of this ROI
        :type idx: int
        :param value: an optional value to be save for this ROI (e.g. to define left and right side)
        :param orientation: Optional orientation Not implemented yet
        :param regions: Optional sub-regions within the ROI.
        :param hierarchy: The hierarchy of subregions in the ROI
        """

        # TODO if we do not need polygon, we can drop it
        self._polygon = np.array(polygon)
        if len(self._polygon.shape) == 2:
            self._polygon = self._polygon.reshape((self._polygon.shape[0],1,self._polygon.shape[1]))


        x,y,w,h = cv2.boundingRect(self._polygon)
        self._mask = np.zeros((h,w), np.uint8)
        cv2.drawContours(self._mask, [self._polygon], 0, 255,-1,offset=(-x,-y))

        self._rectangle = x,y,w,h
        # todo NOW! sort rois by value. if no values, left to right/ top to bottom!
        self._idx = idx

        if value is None:
            self._value = self._idx
        else:
            self._value = value

        if regions is None:
            self._regions = self._polygon
        else:
            # if CV_VERSION == 3:
            #     _, self._regions, self._hierarchy = cv2.findContours(np.copy(self._mask), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            # else:
            #     self._regions, self._hierarchy = cv2.findContours(np.copy(self._mask), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            self._regions = regions
            self._hierarchy = hierarchy

    @property
    def idx(self):
        """
        :return: The index of this ROI
        :rtype: int
        """
        return self._idx

    def bounding_rect(self):
        raise NotImplementedError


    def mask(self):
        """
        :return: The mask as a single chanel, `uint8` image.
        :rtype: :class:`~numpy.ndarray`
        """
        return self._mask

    @property
    def offset(self):
        """
        :return: the x,y offset of the ROI compared to the frame it was build on.
        :rtype: (int,int)
        """
        x,y,w,h = self._rectangle
        return x,y

    @property
    def polygon(self):
        """
        :return: the internal polygon defining the ROI.
        :rtype: :class:`~numpy.ndarray`
        """
        return self._polygon


    @property
    def longest_axis(self):
        """
        :return: the value of the longest axis (w or h)
        :rtype: float
        """
        x,y,w,h = self._rectangle
        return float(max(w, h))

    @property
    def rectangle(self):
        """
        :return: The upright bounding rectangle to the ROI formatted (x,y,w,h). Where x and y are to coordinates of the top left corner
        :rtype: (int,int,int,int)
        """
        return self._rectangle

    def get_feature_dict(self):
        """
        :return: A dictionary of freatures for this roi. It containes the folowing fields:

        * "x"
        * "y"
        * "w"
        * "h"
        * "value"
        * "idx"

        :rtype: dict
        """
        x,y,w,h = self._rectangle
        return {"x":x,
                "y":y,
                "w":w,
                "h":h,
                "value":self._value,
                "idx":self.idx
        }





    def set_value(self, new_val):
        """
        :param new_val: assign a nex value to a ROI
        """
        self._value = new_val

    @property
    def value(self):
        """
        :return: the value of a ROI
        """
        return self._value

    def apply(self,img):
        """
        Cut an image where the ROI is defined.

        :param img: An image. Typically either one or three channels `uint8`.
        :type img: :class:`~numpy.ndarray`
        :return: a tuple containing the resulting cropped image and the associated mask (both have the same dimension).
        :rtype: (:class:`~numpy.ndarray`, :class:`~numpy.ndarray`)
        """
        x,y,w,h = self._rectangle



        try:
            out = img[y : y + h, x : x +w]
        except:
            raise EthoscopeException("Error whilst slicing region of interest %s" % str(self.get_feature_dict()), img)

        if out.shape[0:2] != self._mask.shape:
            raise EthoscopeException("Error whilst slicing region of interest. Possibly, the region out of the image: %s" % str(self.get_feature_dict()), img )

        return out, self._mask

    @property
    def regions(self):
        """
        :return: the regions of a ROI
        """
        return self._regions

    @property
    def hierachy(self):
        """
        :return: the hierarchy of regions in a ROI
        """
        return self._hierarchy

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
        params.minThreshold = 0;
        params.maxThreshold = 100;

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

        #cv2.imshow('here', img)
        #cv2.waitKey(0)

        keypoints = detector.detect(img)

        if np.size(keypoints) !=3:
            logging.error('Just %s targets found instead of three', np.size(keypoints))

        return keypoints

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

    def _get_corrected_mask(self, img):
        rows, cols, _ = img.shape
        frame_targets_pts_sorted = self._get_targets_sorted(img)
        mask_target_pts_sorted = self._get_targets_sorted(self._mask)
        M = cv2.getAffineTransform(np.float32(mask_target_pts_sorted), np.float32(frame_targets_pts_sorted))
        mask_transformed = cv2.warpAffine(self._mask,M,(cols, rows))
        return mask_transformed

    def _is_contour_rectangular(self, c):
	    # approximate the contour
	    peri = cv2.arcLength(c, True)
	    approx = cv2.approxPolyDP(c, 0.02 * peri, True)
	    # the contour is 'bad' if it is not a rectangle
	    return len(approx) == 4

    def _rois_from_img(self,img):
        corrected_mask = self._get_corrected_mask(img)
        edged = cv2.Canny(corrected_mask, 50, 100)
        cv2.imshow("edges", edged)
        #get all external contours
        if CV_VERSION == 3:
            _, contours, hierarchy = cv2.findContours(np.copy(edged), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        else:
            contours, hierarchy = cv2.findContours(np.copy(edged), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(corrected_mask, contours, -1, (255, 255, 0), 3)
            #cv2.imshow('corrected mask contours', corrected_mask)
            #cv2.waitKey(0)

        rois = []

        for i,c in enumerate(contours):
            x = []
            y = []
            if self._is_contour_rectangular(c):
                # for point in c:
                #     x.append(point[0][0])
                #     y.append(point[0][1])
                # x1, x2, y1, y2 = min(x), max(x), min(y), max(y)
                # roi = corrected_mask[y1:y2, x1:x2]
                tmp_mask = np.zeros_like(corrected_mask)
                cv2.drawContours(tmp_mask, [c], -1, (255,255,255), -1)
                my_roi = cv2.bitwise_and(corrected_mask, corrected_mask, mask=tmp_mask)
                cv2.imshow('corrected mask', corrected_mask)
                cv2.waitKey(0)
                cv2.imshow('my roi', my_roi)
                cv2.waitKey(0)
                edged_roi = cv2.Canny(my_roi, 50, 100)
                cv2.imshow('edged_roi', edged_roi)
                cv2.waitKey(0)
                if CV_VERSION == 3:
                    _, sub_contours, sub_hierarchy = cv2.findContours(np.copy(edged_roi), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                else:
                    sub_contours, sub_hierarchy = cv2.findContours(np.copy(edged_roi), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                #select all the contours appart the one that is at the first level (they have no parents)
                sub_contours_2 = [sub_contours[j] for j in range(len(sub_contours)) if (sub_hierarchy[0][j][3] != -1)]
                rois.append(ROI(c, i+1, value=None, regions=sub_contours_2, hierarchy=sub_hierarchy))

        return rois


INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4"
OUTPUT_VIDEO = "/home/diana/Desktop/regions_from_mask.avi"
OUTPUT_DB = "/home/diana/Desktop/results.db"
#MASK = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks/arena_hole_beneath.png"
#MASK = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks/trial_mask.png"
MASK = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks/general3.png"

# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO, drop_each=1)

# here, we generate ROIs automatically from the targets in the images
roi_builder = ArenaMaskROIBuilder(MASK)
rois = roi_builder.build(cam)
# Then, we go back to the first frame of the video
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video

drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)
# We build our monitor

monitor = Monitor(cam, AdaptiveBGModel, rois)

# Now everything ius ready, we run the monitor with a result writer and a drawer
with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
 monitor.run(rw,drawer)
