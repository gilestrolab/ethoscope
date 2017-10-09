__author__ = 'diana'

import numpy as np
import cv2

cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/064d6ba04e534be486069c3db7b10827/ETHOSCOPE_064/2017-03-08_10-13-56/video_chunks/000210.mp4")
fgbg = cv2.BackgroundSubtractorMOG2()

while(1):
    ret, frame = cap.read()

    fgmask = fgbg.apply(frame)

    cv2.imshow('frame',fgmask)
    k = cv2.waitKey(30) & 0xff
    if k == 27:
        break

cap.release()
cv2.destroyAllWindows()