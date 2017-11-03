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
from ethoscope.core.roi import ROI

class ArenaMaskROIBuilder(BaseROIBuilder):

    def __init__(self, mask_path):
        """
        Class to build rois from greyscale image file.
        Each rectangular region found at level 0 in the hierarchy of contours defines a ROI (All childs are excluded).
        """

        self._mask = cv2.imread(mask_path, cv2.CV_LOAD_IMAGE_GRAYSCALE)

        super(ArenaMaskROIBuilder, self).__init__()

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

        #get an image that contains the pixels values that are black. The pixels values > 25 become white.
        ret, thresh = cv2.threshold(img, 25, 255, cv2.THRESH_BINARY)

        return thresh

    def _remove_targets(self, img):
        margin = 10
        targets = self._find_target_coordinates(img)
        result = img.copy()
        for target in targets:
            cv2.circle(result, (int(target.pt[0]), int(target.pt[1])), int(target.size) + margin, (0,0,0), -1)
        return result

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
        #white_pixels = self._mask == 255
        #remove targets
        #self._mask[white_pixels] = 0
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
            #tmp_mask = np.zeros_like(corrected_mask)
            #cv2.drawContours(tmp_mask, [c], 0, (255, 0, 0), thickness=-1)
            #my_roi = cv2.bitwise_and(corrected_mask, corrected_mask, mask=tmp_mask)
            x, y, w, h = cv2.boundingRect(c)
            regions = corrected_mask[y : y + h, x : x +w]
            rois.append(ROI(c, i+1, value=None, regions = regions))
        return rois


INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4"
#INPUT_VIDEO = "/home/diana/Desktop/hinata/11_whole_2017-10-25_12-47-35_011d6ba04e534be486069c3db7b10827__1280x960@25_00000.mp4"
OUTPUT_VIDEO = "/home/diana/Desktop/hinata/out_11_whole_2017-10-25_12-47-35_011d6ba04e534be486069c3db7b10827__1280x960@25_00000.mp4"
OUTPUT_DB = "/home/diana/Desktop/hinata/11_whole_2017-10-25_12-47-35_011d6ba04e534be486069c3db7b10827__1280x960@25_00000.db"

#MASK = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks/arena_hole_beneath.png"
#MASK = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks/trial_mask.png"
#MASK = "/data/Diana/data_node/InkscapeFiles/hinata_arena_drawing2.png"

#MASK = "/home/diana/Desktop/hinata/hinata_final_mask.png"
#MASK = "/data/Diana/data_node/InkscapeFiles/test1.png"
#MASK = "/data/Diana/data_node/InkscapeFiles/arena_hole_beneath.png"
#MASK = "/data/Diana/data_node/InkscapeFiles/general4.png"
MASK = "/data/Diana/data_node/InkscapeFiles/different_regions.png"

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