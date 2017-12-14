__author__ = 'diana'

import numpy as np
import cv2
import copy
from scipy import ndimage
from random import randint

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

bgSubThreshold = 50
cap_region_x_begin = 0.1  # start point/total width
cap_region_y_end=0.95 # start point/total width
threshold = 10  #  BINARY threshold
blurValue = 39 # GaussianBlur parameter

cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4")

# accumulator = []
# for i in range(1, 100000, 1000):
#     ret, frame = cap.read(i)
#     accumulator.append(frame)
#     cv2.imshow('frame', frame)
#     cv2.waitKey(0)
# bg = np.median(np.array(accumulator),0).astype(np.uint8)
#
# cv2.imshow('background', bg)
# cv2.waitKey(0)
#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos_y_maze/024aeeee10184bb39b0754e75cef7900/ETHOSCOPE_024/2016-05-03_11-08-02/whole_2016-05-03_11-08-02_024aeeee10184bb39b0754e75cef7900_diana-dam-3-fly-10-etho-24-ctrl_1280x960@25_00000_clean.mp4")
cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-24_09-08-49/whole_2017-05-24_09-08-49_065d6ba04e534be486069c3db7b10827_SD20_1280x960@25_00000_clean.mp4")

#cap = cv2.VideoCapture("/data/Diana/data_node/ethoscope_videos/008d6ba04e534be486069c3db7b10827/ETHOSCOPE_008/2017-05-04_08-07-38/whole_2017-05-04_08-07-38_008d6ba04e534be486069c3db7b10827_3male_1280x960@25_00000_clean.mp4")

#cap = cv2.VideoCapture("/data/long.mp4")


if (CV_VERSION == 3):
    bgModel = cv2.createBackgroundSubtractorMOG2(0, bgSubThreshold)
else:
    bgModel = cv2.BackgroundSubtractorMOG2(0, bgSubThreshold, bShadowDetection=False)
#bgModel = cv2.BackgroundSubtractorMOG2(history=1000, bgSubThreshold)



def removeBG(frame, learningRate):
    fgmask = bgModel.apply(frame, learningRate=learningRate)
    kernel = np.ones((1, 1), np.uint8)
    fgmask = cv2.erode(fgmask, kernel, iterations=1)
    res = cv2.bitwise_and(frame, frame, mask=fgmask)
    return res



def get_n_px_intersection_2(contour_a, contour_b):
    grey= cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask_a = np.zeros_like(grey, np.uint8)
    cv2.drawContours(mask_a, [contour_a], 0, 255, -1)
    n_px_a = np.count_nonzero(mask_a)

    mask_b = np.zeros_like(grey, np.uint8)
    cv2.drawContours(mask_b, [contour_b], 0, 200, -1)
    n_px_b = np.count_nonzero(mask_b)

    intersection = cv2.bitwise_and(mask_a, mask_b)
    n_px_intersection = np.count_nonzero(intersection)

    return n_px_intersection

def get_n_px_intersection(contour_a, contour_b):
    grey= cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask_a = np.zeros_like(grey, np.uint8)
    cv2.drawContours(mask_a, [contour_a], 0, 255, -1)
    n_px_a = np.count_nonzero(mask_a)

    mask_b = np.zeros_like(grey, np.uint8)
    cv2.drawContours(mask_b, [contour_b], 0, 200, -1)
    n_px_b = np.count_nonzero(mask_b)

    diff = abs(n_px_b - n_px_a)
    # print 'a', n_px_a
    # print 'b', n_px_b
    # print 'diff', diff
    intersection = cv2.bitwise_and(mask_a, mask_b)
    n_px_intersection = np.count_nonzero(intersection)
    #print 'intersection', n_px_intersection

    if n_px_intersection > 0 and diff > 250:
        if (CV_VERSION == 3):
            #print 'problemo'
            _, contours, hierarchy = cv2.findContours(intersection, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            c_intersection = max(contours, key = cv2.contourArea)
            y,x = ndimage.measurements.center_of_mass(mask_a)
            cv2.circle(mask_a, (int(x), int(y)), 10, (0, 0, 0), 3)
            cv2.imshow('mask_a', mask_a)
            cv2.imshow('mask_b', mask_b)
            cv2.imshow('intersection', intersection)
            cv2.imshow('frame', frame)
            cv2.waitKey(0)

        else:
            contours, hierarchy = cv2.findContours(intersection, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            c_intersection = max(contours, key = cv2.contourArea)

    elif n_px_intersection == 0:
        #print 'baaaa'
        c_intersection = None
    else:
       # print 'icccci'
        c_intersection= contour_a
        n_px_intersection = n_px_a



    return c_intersection, n_px_intersection



def get_distance(contour_a, contour_b):
    M_a = cv2.moments(contour_a)
    cX_a = int(M_a['m10'] /M_a['m00'])
    cY_a = int(M_a['m01'] /M_a['m00'])
    M_b = cv2.moments(contour_b)
    cX_b = int(M_b['m10'] /M_b['m00'])
    cY_b = int(M_b['m01'] /M_b['m00'])
    distance = np.sqrt((cX_a - cX_b)**2 + (cY_a-cY_b)**2)
    return distance

i = 0
coloredcontours = []
past_contours = []
cont = 0
all_flies_found = False

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
    cv2.imshow('mask', img)



     # convert the image into binary image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


    blur = cv2.GaussianBlur(gray, (blurValue, blurValue), 0)
    cv2.imshow('blur', blur)
    ret, thresh = cv2.threshold(blur, threshold, 255, cv2.THRESH_BINARY)
    cv2.imshow('ori', thresh)

    original_flies = cv2.bitwise_and(frame, frame, mask=thresh)
    cv2.imshow('original flies', original_flies)

    thresh1 = copy.deepcopy(thresh)
    if (CV_VERSION == 3):
        _, contours, hierarchy = cv2.findContours(thresh1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    else:
        contours, hierarchy = cv2.findContours(thresh1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)


    colors = [(255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (0, 0, 0)]
    # colors = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255),
    #           (255, 0, 255),(192, 192, 192),(128, 128, 128),(128, 0, 0),(128, 128, 0),(0, 128, 0),(128, 0, 128),
    #           (0, 128, 128),(0, 0, 128), (21, 21, 0)]

    ids = range(1, 8)


    if all_flies_found is False and len(contours) != 7:
        consec_contor = 0


    if len(coloredcontours) > 0:
        #tuple_list = [(a, some_process(b)) for (a, b) in tuple_list]

        counts_intersesctions = []
        for new_contour in contours:
            old_contours_touched_indexes = []
            for b, tuple  in enumerate(coloredcontours):
                old_contour, color, id = tuple
                if get_n_px_intersection_2(new_contour, old_contour) > 0:
                    old_contours_touched_indexes.append(b)
            counts_intersesctions.append(old_contours_touched_indexes)


        for el in counts_intersesctions:
            print len(el)

        # for n, el in enumerate(counts_intersesctions):
        #     if len(el) == 1:
        #         coloredcontours[el[0]] == contours[n]
        #     elif len(el) > 1:
        #         print len(el)
        #         print  'write needs splitting'


        for m, tuple in enumerate(coloredcontours):
            contour, color, id = tuple
            intersections_with_old_contours = []
            # print 'here'
            for n, new_contour in enumerate(contours):
                c_intersection, n_px_intersection = get_n_px_intersection(new_contour, contour)
                intersections_with_old_contours.append((c_intersection, n_px_intersection))

            max_intersection = max(intersections_with_old_contours, key=lambda x:x[1])
            if (max_intersection[1] > 0):
                coloredcontours[m] = (max_intersection[0], color, id)
            else:
                print 'Olalalalalalalalalalalala'

            if (len(counts_intersesctions[n]) > 1):
                print 'needs splitting'
    else:
        consec_contor = consec_contor + 1
        if (consec_contor > 5):
            coloredcontours = zip(contours, colors, ids)
            all_flies_found = True


    # if len(contours) > 7:
    #     areaArray = []
    #     for j, c in enumerate(contours):
    #         area = cv2.contourArea(c)
    #         if len(contours) > 1:
    #             areaArray.append(area)
    #     #
    #     # sorteddata = sorted(zip(areaArray, contours), key=lambda x: x[0], reverse=True)
    #     #
    #     # #find the nth largest contour [n-1][1], in this case 2
    #     # secondlargestcontour = sorteddata[1][1]
    #     #
    #     # flies = []
    #     # for k in range(0, 15):
    #     #     flies.append(sorteddata[k][1])
    #     #     cv2.drawContours(frame, flies, -1, (0, 0, 255), 2)
    # else:
    for contouri, color, id in coloredcontours:
        cv2.drawContours(frame, [contouri], -1, color, 2)

    cv2.imshow('output', frame)


    # if len(contours) > 1:
    # #c = max(contours, key = cv2.contourArea)
    #         c =np.argsort(contours, key = cv2.contourArea)
    #         cv2.drawContours(img, [c], -1, (0, 255, 0), 2)
    # else:
    #         cv2.drawContours(img, contours, -1, (0, 255, 0), 2)




    #fgmask = fgbg.apply(frame)
    #cv2.imshow('frame',fgmask)

    k = cv2.waitKey(30) & 0xff
    if k == 27:
        break

cap.release()
cv2.destroyAllWindows()