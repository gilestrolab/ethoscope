__author__ = 'quentin'

import roi_builders as rbs
from tracking_unit import TrackingUnit
import logging
import cv2
import numpy as np
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



    def _draw_on_frame(self,t, frame):
        for track_u in self._unit_trackers:

            xy, wh, a = track_u.get_last_position(absolute=True)

            if np.isnan(xy):
                continue

            x = int(np.round(np.real(xy)))
            y = int(np.round(np.imag(xy)))

            w = int(np.round(np.real(wh)))
            h = int(np.round(np.imag(wh)))

            a = int(np.round(np.real(a)))

            cv2.ellipse(frame,((x,y), (w,h), a),(0,255,0),2)
            cv2.drawContours(frame,[track_u.roi.polygon],-1, (255,0,0), 2)
        cv2.imshow("el", frame)
        cv2.waitKey(1)

    def run(self):
        for t, frame in self._camera:
            for track_u in self._unit_trackers:
                track_u(t, frame)
                # track_u.interactor()
            self._draw_on_frame(t,frame)





                 # if self._interactor_map:
                 #     interactor = self._interactor_map[rt]
                 #     interactor.interact()



