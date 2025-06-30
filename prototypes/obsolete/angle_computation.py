__author__ = 'quentin'
import numpy as np
import cv2


im = np.zeros((1080,1920),np.uint8)


s = 180
for i in range(1,s):
    # x=im.shape[1]

    w=32
    h=64
    y=(i * im.shape[0]) / s
    x=(i * im.shape[1]) / s

    angle=i*3

    if w < h:
        angle -= 90
        w,h = h,w

    angle = angle % 180

    print((w,h,angle))

    # cv2.ellipse(frame_cp,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),black_colour,3,cv2.CV_AA)
    cv2.ellipse(im,((x,y),(w,h),angle),color=(i*5 %200) + 55)
    cv2.imshow("i",im)
    cv2.waitKey(-1)
# 
