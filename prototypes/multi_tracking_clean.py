__author__ = 'diana'

__author__ = 'diana'

import numpy as np
import cv2
import copy
from scipy import ndimage

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

try:
    from cv2.cv import CV_FOURCC as VideoWriter_fourcc
except ImportError:
    from cv2 import VideoWriter_fourcc

bgSubThreshold = 50
cap_region_x_begin = 0.1  # start point/total width
cap_region_y_end=0.95 # start point/total width
threshold = 10  #  BINARY threshold
#previous value
#blurValue = 39 # GaussianBlur parameter
blurValue = 7
colors = [(255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (0, 0, 0)]
ids = range(1, 8)

cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-24_09-08-49/whole_2017-05-24_09-08-49_065d6ba04e534be486069c3db7b10827_SD20_1280x960@25_00000_clean.mp4")

if (CV_VERSION == 3):
    bgModel = cv2.createBackgroundSubtractorMOG2(0, bgSubThreshold)
else:
    bgModel = cv2.BackgroundSubtractorMOG2(0, bgSubThreshold, bShadowDetection=False)


def removeBG(frame, learningRate):
    fgmask = bgModel.apply(frame, learningRate=learningRate)
    kernel = np.ones((1, 1), np.uint8)
    fgmask = cv2.erode(fgmask, kernel, iterations=1)
    res = cv2.bitwise_and(frame, frame, mask=fgmask)
    return res

contours = []

i=0
ret, frame = cap.read()
(h, w) = frame.shape[:2]
vw = cv2.VideoWriter("/home/diana/Desktop/hugo.avi", VideoWriter_fourcc(*"DIVX"), 25, (w,h), False)

while(1):
    ret, frame = cap.read()
    frame = cv2.bilateralFilter(frame, 5, 50, 100) # smoothing filter
    i = i + 1
    ret, frame = cap.read()
    if i < 100:
        learningRate = 0.01
    elif len(contours) > 7:
        learningRate = 0.001
    else:
        learningRate = 0.0
    img = removeBG(frame, learningRate)

     # convert the image into binary image
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    blur = cv2.GaussianBlur(grey, (blurValue, blurValue), 0)
    ret, thresh = cv2.threshold(blur, threshold, 255, cv2.THRESH_BINARY)


    if i > 35 and i < 400:
        vw.write(thresh)

    if i > 300:
        print 'Gata'
        break

vw.release()
cv2.destroyAllWindows()