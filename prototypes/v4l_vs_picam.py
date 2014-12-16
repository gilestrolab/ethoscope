__author__ = 'quentin'


import cv2
import numpy as np
import time

capture = cv2.VideoCapture(0)
capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH,640)
capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 480)

cv2.waitKey(2000)
_,im = capture.read()


NFRAMES = 1000
print "ok, frame shape=", im.shape

t0 = time.time()
for _ in range(NFRAMES):
    _, im = capture.read()
    cv2.imshow("frame", im)
    cv2.waitKey(1)

    #im = np.copy(im)
    assert(len(im.shape) == 3)
t1= time.time()

print (t1-t0) / float(NFRAMES)
