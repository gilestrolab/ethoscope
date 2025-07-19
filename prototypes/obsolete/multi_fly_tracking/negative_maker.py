
__author__ = 'quentin'


import cv2
from ethoscope.hardware.input.cameras import MovieVirtualCamera
import numpy as np
from math import log10
import os
import random


class NegativeMaker(object):
    _path = open("/tmp/fly_snapshots/negative.csv","w")

    def run(self, camera):

        for j, (t,f) in enumerate(camera):
            if j % 10 != 0 :
                continue

            grey = cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
            h_g,w_g =  grey.shape

            for i in range(50):

                st_y, st_x = random.randint(0,h_g-50), random.randint(0,w_g-50)
                thr = random.randint(10,100)
                sub_grey = grey[st_y:st_y+50, st_x:st_x+50]
                _,thr_im= cv2.threshold(grey[st_y:st_y+50, st_x:st_x+50], thr, 255, cv2.THRESH_BINARY_INV| cv2.THRESH_OTSU)
                #sub_grey = grey[st_y:st_y+50, st_x:st_x+50]


                contours,hierarchy = cv2.findContours(thr_im, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                if len(contours) == 0:
                    continue

                x,y,w,h = cv2.boundingRect(contours[0])
                sub_grey= sub_grey[y : y + h, x : x + w]
                # cv2.imshow("t",sub_grey)
                # cv2.waitKey(30)
                sub_grey= cv2.resize(sub_grey, (24,24))


                x_arrstr = np.char.mod('%i', sub_grey)
                out = ", ".join(list(x_arrstr.flatten())) + "\n"
                self._path.write(out)






# change these three variables according to how you name your input/output files
INPUT_VIDEO = "/home/quentin/comput/ethoscope-git/src/ethoscope/tests/integration_server_tests/test_video.mp4"

cam = MovieVirtualCamera(INPUT_VIDEO)

nm = NegativeMaker()
nm.run(cam)