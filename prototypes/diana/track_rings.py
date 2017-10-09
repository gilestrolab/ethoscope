
from ethoscope.core.monitor import Monitor
from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer

# You can also load other types of ROI builder. This one is for 20 tubes (two columns of ten rows)
from ethoscope.roi_builders.roi_builders import DefaultROIBuilder
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder

import cv2
import cv
import numpy as np
from ethoscope.core.roi import ROI
import argparse

# initialize the list of reference points and boolean indicating
# whether cropping is being performed or not
refPt = []
cropping = False

# change these three variables according to how you name your input/output files
INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/064d6ba04e534be486069c3db7b10827/ETHOSCOPE_064/2017-03-08_10-13-56/video_chunks/000210.mp4"
OUTPUT_VIDEO = "/tmp/my_output.avi"
OUTPUT_DB = "/tmp/results.db"

# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO)



class RingRoiBuilder(DefaultROIBuilder):

    # initialize the list of reference points and boolean indicating
    # whether cropping is being performed or not
    refPt = []
    cropping = False


    def _click_and_crop(self,event, x, y, flags, param):
        # grab references to the global variables
        global refPt, cropping

        # if the left mouse button was clicked, record the starting
        # (x, y) coordinates and indicate that cropping is being
        # performed
        if event == cv2.EVENT_LBUTTONDOWN:
            refPt = [(x, y)]
            cropping = True

        # check to see if the left mouse button was released
        elif event == cv2.EVENT_LBUTTONUP:
            # record the ending (x, y) coordinates and indicate that
            # the cropping operation is finished
            refPt.append((x, y))
            cropping = False
            #draw a rectangle around the region of interest
            cv2.rectangle(param, refPt[0], refPt[1], (0, 255, 0), 2)
            height, width = param.shape[:2]
            font = cv2.FONT_HERSHEY_SIMPLEX
            cv2.putText(param,"height" + str(refPt[1][1] - refPt[0][1]) +" width " + str(refPt[1][0] - refPt[0][0]),(10,500), font, 4,(255,255,255),2,cv.CV_AA)
            y_center = (refPt[1][1] + refPt[0][1])/2
            x_center = (refPt[1][0] + refPt[0][0])/2
            cv2.circle(param,(x_center,y_center), 1, (0,0,255), -1)
            cv2.imshow("image", param)


    def _rois_from_img(self,image):
        clone = image.copy()
        cv2.namedWindow("image")
        cv2.setMouseCallback("image", self._click_and_crop, image)

        # keep looping until the 'c' key is pressed
        while True:
            # display the image and wait for a keypress
            cv2.imshow("image", image)
            key = cv2.waitKey(1) & 0xFF

            # if the 'r' key is pressed, reset the cropping region
            if key == ord("r"):
                image = clone.copy()
                cv2.setMouseCallback("image", self._click_and_crop, image)


            # if the 'c' key is pressed, break from the loop
            elif key == ord("c"):
                break

        # if there are two reference points, then crop the region of interest
        # from teh image and display it
        if len(refPt) == 2:
            roi = clone[refPt[0][1]:refPt[1][1], refPt[0][0]:refPt[1][0]]
            cv2.imshow("ROI", roi)
            cv2.waitKey(0)


        rois = []
        rois.append(ROI(np.array(roi), idx=1))
        print 'what the fuck?'

        print rois
        print 'blalalalala'
        cv2.drawContours(image,[roi], -1, (255,0,0),1,cv2.CV_AA)
        cv2.imshow("dbg",image)
        cv2.waitKey(0)

        # close all open windows
        cv2.destroyAllWindows()
        return rois

# here, we generate ROIs automatically from the targets in the images
roi_builder = RingRoiBuilder()
rois = roi_builder.build(cam)
# Then, we go back to the first frame of the video
print rois
print 'blabla'
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video
drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)
# We build our monitor
monitor = Monitor(cam, MultiFlyTracker, rois)

# Now everything ius ready, we run the monitor with a result writer and a drawer
# with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
monitor.run(None, drawer)
