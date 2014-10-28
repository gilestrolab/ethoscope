__author__ = 'quentin'

import roi_builders as rbs
from tracking_unit import TrackingUnit
import logging
import cv2


import pandas as pd


class Monitor(object):

    def __init__(self, camera, tracker_class, roi_builder = None, interactors=None):

        self._camera = camera

        if roi_builder is None:
            roi_builder = rbs.DefaultROIBuilder()

        # We build the roi, possibly from images and/or templates. By default all the image is the ROI
        rois = roi_builder(camera)
        self._camera.restart()


        if interactors is None:
            self._unit_trackers = [TrackingUnit(tracker_class, r, None) for r in rois]

        elif len(interactors) == len(rois):
            self._unit_trackers = [TrackingUnit(tracker_class, r, inter) for r, inter in zip(rois, interactors)]
        else:
            raise ValueError("You should have one interactor per ROI")



    def _draw_on_frame(self,track_u, row, frame):
        if row is None:
            return

        pos = track_u.get_last_position(absolute=True)

        cv2.drawContours(frame,[track_u.roi.polygon],-1, (0,0,255), 1, cv2.CV_AA)

        if pos is None:
            return

        if "interact" in row and bool(row.interact.item()):
            colour = (0, 255, 0)
        else:
            colour = (255, 0, 0)

        cv2.ellipse(frame,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),colour,1,cv2.CV_AA)





    def run(self):
        out  = []

        for t, frame in self._camera:
            copy = frame.copy()
            for track_u in self._unit_trackers:

                data_row = track_u(t, frame)
                if data_row is not None:
                    out.append(data_row)

                self._draw_on_frame(track_u, data_row, copy)


            cv2.imshow("el", copy)
            cv2.waitKey(1)
            print t / 60.

