__author__ = 'quentin'


import cv2
import numpy as np
import time

capture = cv2.VideoCapture(0)
cv2.waitKey(2000)
im = capture.read()

NFRAMES = 1000
print "ok, frame shape=", im.shape

t0 = time.time()
for _ in range(NFRAMES):
    _, im = capture.read()
    im = np.copy(im)
    assert(len(im.shape) == 3)
t1= time.time()

print t0,t1
print (t1-t0) / float(NFRAMES)
