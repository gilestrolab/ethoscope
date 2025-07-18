__author__ = 'quentin'


from ethoscope.tracking.cameras import *
import cv2


# cam = MovieVirtualCamera("/home/quentin/Desktop/drosoAdult_short.avi")
#

cam = V4L2Camera(0,target_fps=50)

for t,frame in cam:
    cv2.imshow("Test", frame)
    cv2.waitKey(1)


for t,frame in cam:
    cv2.imshow("Test", frame)
    cv2.waitKey(1)


cam = V4L2Camera(0,target_fps=1)

for t,frame in cam:
    print(t, frame.shape)
    if t > 5:
         break

for t,frame in cam:
    print(t, frame.shape)
    if t > 5:
         break