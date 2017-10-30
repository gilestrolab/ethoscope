__author__ = 'diana'

import cv2
import numpy as np

cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4")
while True:
    _, frame = cap.read()



    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (11,11), 0)



    (minVal, maxVal, minLoc, maxLoc) = cv2.minMaxLoc(blur)


    hi, threshold = cv2.threshold(blur, maxVal-100, 230, cv2.THRESH_BINARY)
    thr = threshold.copy()



    cv2.resize(thr, (300,300))

    edged = cv2.Canny(threshold, 50, 150)

    cv2.imshow('this', edged)
    cv2.waitKey(0)

    lightcontours, hierarchy = cv2.findContours(edged, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)


    for (i, c) in enumerate(lightcontours):
        points = []
        (x, y, w, h) = cv2.boundingRect(c)
        ((cX, cY), radius) = cv2.minEnclosingCircle(c)
        cv2.circle(frame, (int(cX), int(cY)), int(radius),
            (0, 0, 255), 3)
        points.append([[int(cX), int(cY)]])
        print points
        cv2.putText(frame, "#{}".format(i + 1), (x, y - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2)


    cv2.imshow('light', thr)
    cv2.imshow('frame', frame)
    cv2.imshow('edges', edged)
    cv2.waitKey(4)
    key = cv2.waitKey(5) & 0xFF
    if key == ord('q'):
        break
cap.release()
cv2.destroyAllWindows()