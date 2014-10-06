__author__ = 'quentin'






from pysolovideo.tracking.cameras import *
import cv2
import numpy as np

# we start from a cropped video:
cam = MovieVirtualCamera("/stk/pysolo_video_samples/singleDamTube2_150min_night.avi")

mog = cv2.BackgroundSubtractorMOG(1000,2, 0.9, 1.0)
# mog = cv2.BackgroundSubtractorMOG()

lr =  1e-2
min_lr = 1e-7
for t,frame in cam:


    tmp = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)

    tmp = cv2.GaussianBlur(tmp,(3,3), 1.5)
    cv2.imshow("prev",tmp)
    fg = mog.apply(tmp, None, lr)

    if np.sum(fg):

        lr /= 1.01
        if lr < min_lr:
            lr = 0.0
        print lr




    cv2.imshow("fg",fg )
    cv2.waitKey(30)
