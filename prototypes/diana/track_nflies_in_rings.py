__author__ = 'diana'


from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.trackers.trackers import *
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.roi_builders.roi_builders import DefaultROIBuilder

from ethoscope.core.monitor import Monitor
from ethoscope.core.data_point import DataPoint
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.core.roi import ROI

from math import log10, sqrt, pi
import cv2
import numpy as np
import optparse
import logging
from ethoscope.utils.debug import EthoscopeException
from ethoscope.core.roi import ROI
import math


class MultiFlyTracker(BaseTracker):
    def __init__(self, roi, data=None):
        self._accum = None
        self._alpha = 0.0001
        super(MultiFlyTracker, self).__init__(roi, data)

    def _filter_contours(self, contours, min_area =50, max_area=200):
        out = []
        for c in contours:
            if c.shape[0] < 6:
                continue
            area = cv2.contourArea(c)
            if not min_area < area < max_area:
                continue

            out.append(c)
        return out

    def _find_position(self, img, mask,t):
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return self._track(img, grey, mask, t)

    def _track(self, img,  grey, mask, t):
        if self._accum is None:
            self._accum = grey.astype(np.float64)
            self._old_pos = 0.0 +0.0j

        frame_float64 = grey.astype(np.float64)
        cv2.accumulateWeighted(frame_float64, self._accum, self._alpha)
        bg = self._accum.astype(np.uint8)

        #cv2.imshow('bg', bg)
        #cv2.waitKey(30)

        diff = cv2.absdiff(bg, grey)

        cv2.imshow('this', diff)
        cv2.waitKey(30)

        cv2.medianBlur(grey, 7, grey)
        _, bin_im = cv2.threshold(diff, 10, 255, cv2.THRESH_BINARY)

        cv2.imshow('bin', bin_im)
        cv2.waitKey(30)

        contours,hierarchy = cv2.findContours(bin_im,
                                              cv2.RETR_EXTERNAL,
                                              cv2.CHAIN_APPROX_SIMPLE)

        contours= self._filter_contours(contours)

        if len(contours) != 1:
            raise NoPositionError
        hull = contours[0]

        (_,_) ,(w,h), angle = cv2.minAreaRect(hull)

        M = cv2.moments(hull)
        x = int(M['m10']/M['m00'])
        y = int(M['m01']/M['m00'])
        if w < h:
            angle -= 90
            w,h = h,w
        angle = angle % 180

        h_im = min(grey.shape)
        w_im = max(grey.shape)


        max_h = 2*h_im
        if w>max_h or h>max_h:
            raise NoPositionError


        pos = x +1.0j*y
        pos /= w_im

        xy_dist = round(log10(1./float(w_im) + abs(pos - self._old_pos))*1000)

        self._old_pos = pos

        x_var = XPosVariable(int(round(x)))
        y_var = YPosVariable(int(round(y)))
        w_var = WidthVariable(int(round(w)))
        h_var = HeightVariable(int(round(h)))
        phi_var = PhiVariable(int(round(angle)))
        distance = XYDistance(int(xy_dist))
        out = DataPoint([x_var, y_var, w_var, h_var, phi_var, distance])

        return [out]


if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-o", "--output", dest="out", help="the output file (eg out.csv   )", type="str",default=None)
    parser.add_option("-i", "--input", dest="input", help="the output video file", type="str")
    #
    parser.add_option("-r", "--result-video", dest="result_video", help="the path to an optional annotated video file."
                                                                "This is useful to show the result on a video.",
                                                                type="str", default=None)

    parser.add_option("-d", "--draw-every",dest="draw_every", help="how_often to draw frames", default=0, type="int")

    parser.add_option("-m", "--mask", dest="mask", help="the mask file with 3 targets", type="str")

    (options, args) = parser.parse_args()

    option_dict = vars(options)

    logging.basicConfig(level=logging.INFO)


    logging.info("Starting Monitor thread")

    cam = MovieVirtualCamera(option_dict ["input"], use_wall_clock=False)

    #my_image = cv2.imread(option_dict['mask'])
    #print option_dict['mask']

    # accum = []
    # for i, (_, frame) in enumerate(cam):
    #     accum.append(frame)
    #     if i  >= 5:
    #         break

    #accum = np.median(np.array(accum),0).astype(np.uint8)
    # cv2.imshow('window', my_image)

    roi_builder = DefaultROIBuilder()
    rois = roi_builder.build(cam)

    logging.info("Initialising monitor")

    cam.restart()

    metadata = {
                             "machine_id": "None",
                             "machine_name": "None",
                             "date_time": cam.start_time, #the camera start time is the reference 0
                             "frame_width":cam.width,
                             "frame_height":cam.height,
                             "version": "whatever"
                              }
    draw_frames = False
    if option_dict["draw_every"] > 0:
        draw_frames = True

    drawer = DefaultDrawer(video_out='/home/diana/Desktop/example_video3.avi', draw_frames=True)

    #monit = Monitor(cam, YMazeTracker, rois)
    monit = Monitor(cam, MultiFlyTracker, rois)

    with SQLiteResultWriter(option_dict["out"], rois, metadata) as rw:
        print rw
        monit.run(rw, drawer)

    logging.info("Stopping Monitor")
