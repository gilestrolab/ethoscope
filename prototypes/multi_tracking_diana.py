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

def min_distance(x, y, centers):
    distances_to_centers = []
    for center in centers:
        center_x, center_y = center
        d = np.sqrt((center_x - x)**2 + (center_y - y)**2)
        distances_to_centers.append(d)
    print distances_to_centers
    return distances_to_centers

def removeBG(frame, learningRate):
    fgmask = bgModel.apply(frame, learningRate=learningRate)
    kernel = np.ones((1, 1), np.uint8)
    fgmask = cv2.erode(fgmask, kernel, iterations=1)
    res = cv2.bitwise_and(frame, frame, mask=fgmask)
    return res

def get_n_px_intersection_2(contour_a, contour_b):
    mask_a = np.zeros_like(grey, np.uint8)
    cv2.drawContours(mask_a, [contour_a], 0, 255, -1)
    n_px_a = np.count_nonzero(mask_a)

    mask_b = np.zeros_like(grey, np.uint8)
    cv2.drawContours(mask_b, [contour_b], 0, 200, -1)
    n_px_b = np.count_nonzero(mask_b)

    intersection = cv2.bitwise_and(mask_a, mask_b)
    n_px_intersection = np.count_nonzero(intersection)

    return n_px_intersection

all_flies_found = False
i = 0
coloredcontours = []
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
    # cv2.imshow('ori', thresh)

    original_flies = cv2.bitwise_and(frame, frame, mask=thresh)


    thresh1 = copy.deepcopy(thresh)
    if (CV_VERSION == 3):
        _, contours, hierarchy = cv2.findContours(thresh1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    else:
        contours, hierarchy = cv2.findContours(thresh1, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)


    #consec_contour waits for 5 consecutive frame in which the flies are found
    if all_flies_found is False and len(contours) != 7:
        consec_contor = 0


    if len(coloredcontours) > 0:
        counts_intersesctions = []
        for new_contour in contours:
            area = cv2.contourArea(new_contour)
            if area > 300:
                old_contours_touched_indexes = []
                for b, tuple  in enumerate(coloredcontours):
                    old_contour, color, id = tuple
                    if get_n_px_intersection_2(new_contour, old_contour) > 0:
                        old_contours_touched_indexes.append(b)
                if len(old_contours_touched_indexes) == 0:
                    print 'Aiaiaiaiaiaiaiai'
                    mask_new_contour = np.zeros_like(grey, np.uint8)
                    cv2.drawContours(mask_new_contour, [new_contour], 0, 255, -1)
                    new_y, new_x = ndimage.measurements.center_of_mass(mask_new_contour)
                    center_of_mass_old_contours =[]
                    for contour, color, id in coloredcontours:
                        mask_old_contours = np.zeros_like(grey, np.uint8)
                        cv2.drawContours(mask_old_contours, [contour], 0, 255, -1)
                        y,x = ndimage.measurements.center_of_mass(mask_old_contours)
                        center_of_mass_old_contours.append((x, y))
                    distances_to_old_contours = min_distance(new_x, new_y, center_of_mass_old_contours)
                    index_old_contour = np.argmin(distances_to_old_contours)
                    old_contour, old_color, old_id = coloredcontours[index_old_contour]
                    coloredcontours[index_old_contour] = (new_contour, old_color, old_id)
                if len(old_contours_touched_indexes) == 1:
                    print old_contours_touched_indexes
                    _, old_color, old_id = coloredcontours[old_contours_touched_indexes[0]]
                    coloredcontours[old_contours_touched_indexes[0]] = (new_contour, old_color, old_id)
                elif len(old_contours_touched_indexes) > 1:
                    mask_new_contour = np.zeros_like(grey, np.uint8)
                    cv2.drawContours(mask_new_contour, [new_contour], 0, 255, -1)
                    # cv2.imshow('new contour', mask_new_contour)
                    old_colored_contours = [coloredcontours[l] for l in old_contours_touched_indexes]

                    mask_all_old_contours = np.zeros_like(grey, np.uint8)
                    center_of_mass_old_contours = []
                    for contour, color, id in old_colored_contours:
                        mask_old_contours = np.zeros_like(grey, np.uint8)
                        cv2.drawContours(mask_old_contours, [contour], 0, 255, -1)
                        cv2.drawContours(mask_all_old_contours, [contour], 0, 255, -1)
                        y,x = ndimage.measurements.center_of_mass(mask_old_contours)
                        center_of_mass_old_contours.append((x, y))
                        cv2.circle(mask_all_old_contours, (int(x), int(y)), 10, (0, 0, 0), 2)

                    print center_of_mass_old_contours

                    y_ind, x_ind = mask_new_contour.nonzero()

                    #distances_to_old_centers = np.zeros((len(x_ind), len(center_of_mass_old_contours)))

                    #distances_to_old_centers[x_ind] = min_distance(x_ind, y_ind, center_of_mass_old_contours)

                    #print distances_to_old_centers

                    distances = np.transpose(min_distance(x_ind, y_ind, center_of_mass_old_contours))


                    copy_mask_new_cnt = mask_new_contour.copy()

                    fly_index = [np.argmin(row) + 10 for row in distances]

                    copy_mask_new_cnt[y_ind, x_ind] = fly_index


                    for m, tuple in enumerate(old_colored_contours):
                        print 'heeeerrrrrrrrrrrrrrrrrrrrrrrrrrre', m
                        another_copy_mask_new_cnt = copy_mask_new_cnt.copy()
                        fly_2_pixels = another_copy_mask_new_cnt != (m + 10)
                        another_copy_mask_new_cnt[fly_2_pixels] = 0
                        fly_1_pixels = another_copy_mask_new_cnt == m + 10
                        another_copy_mask_new_cnt[fly_1_pixels] = 255
                        old_contour, color, id = tuple
                        if (CV_VERSION == 3):
                            _, contours, hierarchy = cv2.findContours(another_copy_mask_new_cnt, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                        else:
                            contours, hierarchy = cv2.findContours(another_copy_mask_new_cnt, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                        if len(contours) > 1:
                            coloredcontours[old_contours_touched_indexes[m]] = (contours[0], color, id)



                    fly_1_pixels = copy_mask_new_cnt == 10
                    copy_mask_new_cnt[fly_1_pixels] = 255

                    fly_2_pixels = copy_mask_new_cnt == 11
                    copy_mask_new_cnt[fly_2_pixels] = 50


                    # cv2.imshow('final', copy_mask_new_cnt)


                    #cv2.drawContours(mask_old_contours, ocs, 0, 255, -1)

                    # cv2.imshow('old contour', mask_all_old_contours)
                    # cv2.waitKey(0)

    else:
        consec_contor = consec_contor + 1
        if (consec_contor > 5):
            coloredcontours = zip(contours, colors, ids)
            all_flies_found = True

    for contouri, color, id in coloredcontours:
        cv2.drawContours(frame, [contouri], -1, color, 2)

    cv2.imshow('output', frame)

    k = cv2.waitKey(30) & 0xff
    if k == 27:
        break

cap.release()
cv2.destroyAllWindows()