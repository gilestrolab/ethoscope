__author__ = 'diana'

import cv2
import os
import numpy as np
from ethoscope.utils.debug import EthoscopeException

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

import logging

def sort(keypoints):
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

def find_target_coordinates(img):
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

def is_contour_bad(c):
	# approximate the contour
	peri = cv2.arcLength(c, True)
	approx = cv2.approxPolyDP(c, 0.02 * peri, True)
	# the contour is 'bad' if it is not a rectangle
	return not len(approx) == 4

#TEST_FRAMES = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks"
TEST_FRAMES = "/home/diana/github/ethoscope/prototypes/rois_from_images/frames"
IMAGE_FORMAT =".jpg"
MASK_PATH = "/home/diana/github/ethoscope/prototypes/rois_from_images/masks/arena_hole_beneath.png"

mask = cv2.imread(MASK_PATH)
rows,cols,ch = mask.shape

mask_targets = find_target_coordinates(mask)
mask_target_pts_sorted = sort(mask_targets)

print type(mask_targets)
print type(mask_target_pts_sorted)
mask_with_targets = cv2.drawKeypoints(mask, mask_targets, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
cv2.imshow('mask with targets', mask_with_targets)
cv2.waitKey(0)

imfilelist = [os.path.join(TEST_FRAMES, f) for f in os.listdir(TEST_FRAMES) if f.endswith(IMAGE_FORMAT)]

for f in imfilelist:
    frame = cv2.imread(f)
    targets = find_target_coordinates(frame)
    print frame.shape
    frame_targets_pts_sorted = sort(targets)

    M = cv2.getAffineTransform(np.float32(mask_target_pts_sorted), np.float32(frame_targets_pts_sorted))
    mask_transformed = cv2.warpAffine(mask,M,(cols,rows))
    cv2.imshow('Transformed mask', mask_transformed)
    cv2.waitKey(0)

    frame_with_keypoints = cv2.drawKeypoints(frame, targets, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
    cv2.imshow('frame with keypoints', frame_with_keypoints)
    cv2.waitKey(0)

gray = cv2.cvtColor(mask_transformed, cv2.COLOR_BGR2GRAY)
edged = cv2.Canny(gray, 50, 100)
cv2.imshow("edges", edged)

# find contours in the image and initialize the mask that will be
# used to remove the bad contours
(cnts, hierarchy) = cv2.findContours(edged.copy(), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
#print hierarchy[0][3][3]
#print hierarchy[0][3][3] < 0

my_contour = None
for i, c in enumerate(cnts):
    my_contour = c
    #print int(cv2.pointPolygonTest(c, (555, 800), False)) > 0
    #if hierarchy[0][i][3] < 0:
    if cv2.pointPolygonTest(c, (555, 800), False) > 0:
         cv2.drawContours(frame, [c], -1, (255, 0, 255), 3)
         #print type(cv2.pointPolygonTest(c, (555, 800), False))
    else:
        cv2.drawContours(frame, [c], -1, (255, 255, 0), 3)

cv2.imshow("ROIS on frame", frame)
cv2.waitKey(0)
mask = np.ones(mask_transformed.shape[:2], dtype="uint8") * 255

# loop over the contours
for c in cnts:
    # if the contour is bad, draw it on the mask
    if is_contour_bad(c):
        cv2.drawContours(mask, [c], -1, 0, -1)

# remove the contours from the image and show the resulting images
new_mask_without_targets = cv2.bitwise_and(mask_transformed, mask_transformed, mask=mask)
tmp_mask = np.zeros_like(new_mask_without_targets)
cv2.drawContours(tmp_mask, [my_contour],-1, (255, 255, 0), 3)

cv2.imshow("tnp mask", new_mask_without_targets[tmp_mask > 0])
cv2.waitKey(0)

cv2.imshow("Mask", mask)
cv2.imshow("After", new_mask_without_targets)
cv2.waitKey(0)