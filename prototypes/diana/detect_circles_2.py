__author__ = 'diana'

import cv
import numpy as np

WAITKEY_DELAY_MS = 10
STOP_KEY = 'q'

cv.NamedWindow("image - press 'q' to quit", cv.CV_WINDOW_AUTOSIZE);
cv.NamedWindow("post-process", cv.CV_WINDOW_AUTOSIZE);

key_pressed = False
while key_pressed != STOP_KEY:

    # grab image
    orig = cv.LoadImage('/home/diana/Desktop/circle.png')

    # create tmp images
    grey_scale = cv.CreateImage(cv.GetSize(orig), 8, 1)
    processed = cv.CreateImage(cv.GetSize(orig), 8, 1)


    cv.Smooth(orig, orig, cv.CV_GAUSSIAN, 3, 3)

    cv.CvtColor(orig, grey_scale, cv.CV_RGB2GRAY)

    # do some processing on the grey scale image
    cv.Erode(grey_scale, processed, None, 10)
    cv.Dilate(processed, processed, None, 10)
    cv.Canny(processed, processed, 5, 70, 3)
    cv.Smooth(processed, processed, cv.CV_GAUSSIAN, 15, 15)

    storage = cv.CreateMat(orig.width, 1, cv.CV_32FC3)

    # these parameters need to be adjusted for every single image
    HIGH = 50
    LOW = 140

    try:
        # extract circles
        cv.HoughCircles(processed, storage, cv.CV_HOUGH_GRADIENT, 2, 32.0, HIGH, LOW)

        for i in range(0, len(np.asarray(storage))):
            print "circle #%d" %i
            Radius = int(np.asarray(storage)[i][0][2])
            x = int(np.asarray(storage)[i][0][0])
            y = int(np.asarray(storage)[i][0][1])
            center = (x, y)

            # green dot on center and red circle around
            cv.Circle(orig, center, 1, cv.CV_RGB(0, 255, 0), -1, 8, 0)
            cv.Circle(orig, center, Radius, cv.CV_RGB(255, 0, 0), 3, 8, 0)

            cv.Circle(processed, center, 1, cv.CV_RGB(0, 255, 0), -1, 8, 0)
            cv.Circle(processed, center, Radius, cv.CV_RGB(255, 0, 0), 3, 8, 0)

    except:
        print "nothing found"
        pass

    # show images
    cv.ShowImage("image - press 'q' to quit", orig)
    cv.ShowImage("post-process", processed)

    cv_key = cv.WaitKey(WAITKEY_DELAY_MS)
    key_pressed = chr(cv_key & 255)
