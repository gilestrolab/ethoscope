__author__ = 'quentin'


import cv2
import numpy as np
import time
import time


# capture = cv2.VideoCapture(0)
# capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH,640)
# capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 480)
#
# capture.set(cv2.cv.CV_CAP_PROP_FPS, 5)
#
# time.sleep(0.5)
# #cv2.waitKey(2000)
# _,im = capture.read()
#
#
# NFRAMES = 1000
# print "ok, frame shape=", im.shape
#
# t0 = time.time()
# try:
#     for _ in range(NFRAMES):
#
#         capture.grab()
#         capture.retrieve(im)
#
#         cv2.imshow("frame", im)
#         cv2.waitKey(1)
#
#
#
#         #im = np.copy(im)
#         assert(len(im.shape) == 3)
#     t1= time.time()
#
#     print (t1-t0) / float(NFRAMES)
# finally:
#     print "voila"
#     capture.release()
#
# print "test"


capture = cv2.VideoCapture(0)
time.sleep(2)

w, h = (640, 480)
if w <0 or h <0:
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 99999)
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 99999)
else:
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, w)
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, h)

capture.set(cv2.cv.CV_CAP_PROP_FPS, 5)


time.sleep(1)
_, im = capture.read()
cv2.imshow("im", im); cv2.waitKey(-1)


capture.release()

device=0
target_fps=1
target_resolution=(640,480)
capture = cv2.VideoCapture(device)
w, h = target_resolution
if w <0 or h <0:
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, 99999)
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, 99999)
else:
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_WIDTH, w)
    capture.set(cv2.cv.CV_CAP_PROP_FRAME_HEIGHT, h)
capture.set(cv2.cv.CV_CAP_PROP_FPS, target_fps)

_target_fps = float(target_fps)
time.sleep(1)
_, im = capture.read()

# preallocate image buffer => faster
_frame = im

cv2.imshow("im", im ); cv2.waitKey(-1)




#
# _start_time = time.time()
#
# for i in range(300):
#     expected_time =  _start_time +i / 5.0
#     now = time.time()
#
#     to_sleep = expected_time - now
#
#     # Warnings if the fps is so high that we cannot grab fast enough
#     if to_sleep < 0:
#         print "The target FPS could not be reached. Frame lagging by  %f seconds" % (-1 * to_sleep)
#         capture.grab()
#
#     # we simply drop frames until we go above expected time
#     while now < expected_time:
#         capture.grab()
#         now = time.time()
#     else:
#         capture.grab()
#
#     capture.retrieve(im)
#     cv2.imshow("im", im); cv2.waitKey(6)
#
#
# #
# # #TODO better exception handling is needed here / what do we do if initial capture fails...
# # assert(len(im.shape) >1)
