__author__ = 'diana'

import numpy as np
import cv2

#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/064d6ba04e534be486069c3db7b10827/ETHOSCOPE_064/2017-03-08_10-13-56/video_chunks/000210.mp4")
#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/018c6ba04e534be486069c3db7b10827/ETHOSCOPE_018/2017-09-13_09-40-11/whole_2017-09-13_09-40-11_018c6ba04e534be486069c3db7b10827__1920x1080@25_00000.mp4")
#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-17_09-02-52/whole_2017-05-17_09-02-52_065d6ba04e534be486069c3db7b10827_single_1280x960@25_00000_clean.mp4")

cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4")

fgbg = cv2.BackgroundSubtractorMOG(history=200, backgroundRatio=0.7, nmixtures=5, noiseSigma=0)
#fgbg = cv2.BackgroundSubtractorMOG2()
while(1):
    ret, frame = cap.read()

    fgmask = fgbg.apply(frame, learningRate=0.1)
    #erosion = cv2.erode(fgmask,None,iterations = 1);
    #dilation = cv2.dilate(erosion,None,iterations = 1);
    #cv2.findContours(dilation.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    #cv2.imshow('frame',dilation)
    cv2.imshow('frame',fgmask)

    k = cv2.waitKey(30) & 0xff
    if k == 27:
        break

cap.release()
cv2.destroyAllWindows()