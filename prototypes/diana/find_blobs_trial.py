__author__ = 'diana'

import numpy as np
import cv2


img = cv2.imread('/home/diana/Desktop/trial12.png', cv2.IMREAD_GRAYSCALE)

params = cv2.SimpleBlobDetector_Params()

# Change thresholds
params.minThreshold = 0;
params.maxThreshold = 50;

# Filter by Area.
params.filterByArea = True
params.minArea = 1200

# Filter by Circularity
params.filterByCircularity = True
params.minCircularity = 0.5
#
# Filter by Convexity
params.filterByConvexity = True
params.minConvexity = 0.5
#
# # Filter by Inertia
# params.filterByInertia = True
# params.minInertiaRatio = 0.01


detector = cv2.SimpleBlobDetector(params)
keypoints = detector.detect(img)

# Detect blobs.
keypoints = detector.detect(img)

print keypoints[0].pt
print keypoints[0].size
print keypoints[1].pt
print keypoints[1].size
print keypoints[2].pt
print keypoints[2].size

myminx = min(keypoint.pt[0] for keypoint in keypoints)
myminy = min(keypoint.pt[1] for keypoint in keypoints)
print "min x is %s", myminx
print "min y is %s", myminy

a = cv2.KeyPoint()
b = cv2.KeyPoint()
c = cv2.KeyPoint()

for keypoint in keypoints:
    if keypoint.pt[0] == myminx:
        c = keypoint

for keypoint in keypoints:
    if keypoint.pt[1] == myminy:
        a = keypoint

print keypoints
b = np.setdiff1d(keypoints, [a, c])[0]
print a
print a.pt
print c
print c.pt
print b
print b.pt


# Draw detected blobs as red circles.
# cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS ensures the size of the circle corresponds to the size of blob
im_with_keypoints = cv2.drawKeypoints(img, keypoints, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

print 'first keypoint x coordinate %s', keypoints[0].pt[0]
print 'first keypoint y coordinate %s', keypoints[0].pt[1]
print 'first keypoint x coordinate %s', keypoints[1].pt[0]
print 'first keypoint y coordinate %s', keypoints[1].pt[1]
print 'first keypoint x coordinate %s', keypoints[2].pt[0]
print 'first keypoint y coordinate %s', keypoints[2].pt[1]


# Show keypoints
cv2.imshow("Keypoints", im_with_keypoints)
cv2.waitKey(0)
