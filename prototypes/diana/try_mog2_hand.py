__author__ = 'diana'

import numpy as np
import cv2
import copy

bgSubThreshold = 50
cap_region_x_begin = 0.1  # start point/total width
cap_region_y_end=0.95 # start point/total width
threshold = 10  #  BINARY threshold
blurValue = 39 # GaussianBlur parameter

cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4")

#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-24_09-08-49/whole_2017-05-24_09-08-49_065d6ba04e534be486069c3db7b10827_SD20_1280x960@25_00000_clean.mp4")

#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/008d6ba04e534be486069c3db7b10827/ETHOSCOPE_008/2017-05-04_08-07-38/whole_2017-05-04_08-07-38_008d6ba04e534be486069c3db7b10827_3male_1280x960@25_00000_clean.mp4")

bgModel = cv2.BackgroundSubtractorMOG2(0, bgSubThreshold)

def removeBG(frame, learningRate):
    fgmask = bgModel.apply(frame, learningRate=learningRate)
    # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    # res = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, kernel)
    cv2.imshow('tada', fgmask)
    kernel = np.ones((1, 1), np.uint8)
    fgmask = cv2.erode(fgmask, kernel, iterations=1)
    res = cv2.bitwise_and(frame, frame, mask=fgmask)

    return res


i = 0

while(1):
    ret, frame = cap.read()
    frame = cv2.bilateralFilter(frame, 5, 50, 100) # smoothing filter
    cv2.imshow('original', frame)

    cv2.rectangle(frame, (int(cap_region_x_begin * frame.shape[1]), 0),
                            (frame.shape[1] - 200, int(cap_region_y_end * frame.shape[0])), (255, 0, 0), 2)
    cv2.imshow('rectangle', frame)

    i = i + 1
    ret, frame = cap.read()
    if i < 100:
        learningRate = 0.01
    else:
        learningRate = 0.0
    print learningRate
    img = removeBG(frame, learningRate)
    #img = img[0:int(cap_region_y_end * frame.shape[0]),
    #               int(cap_region_x_begin * frame.shape[1]):frame.shape[1]-200]  # clip the ROI
    cv2.imshow('mask', img)
    #original_flies = cv2.bitwise_and(frame, frame, mask=img)
    #cv2.imshow('original flies', original_flies)

     # convert the image into binary image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


    blur = cv2.GaussianBlur(gray, (blurValue, blurValue), 0)
    cv2.imshow('blur', blur)
    ret, thresh = cv2.threshold(blur, threshold, 255, cv2.THRESH_BINARY)
    cv2.imshow('ori', thresh)

    original_flies = cv2.bitwise_and(frame, frame, mask=thresh)
    cv2.imshow('original flies', original_flies)

    thresh1 = copy.deepcopy(thresh)
    contours, hierarchy = cv2.findContours(thresh1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    drawing = np.zeros(img.shape, np.uint8)
    cv2.drawContours(img, contours, -1, (0, 255, 0), 2)

    cv2.imshow('output', img)



    #fgmask = fgbg.apply(frame)
    #cv2.imshow('frame',fgmask)

    k = cv2.waitKey(30) & 0xff
    if k == 27:
        break

cap.release()
cv2.destroyAllWindows()