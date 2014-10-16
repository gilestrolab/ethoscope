__author__ = 'quentin'

import roi_builders as rbs
from tracking_unit import TrackingUnit
import logging
import cv2

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



    def run(self):
         for t, frame in self._camera:
             for track_u in self._unit_trackers:
                track_u(t, frame)
                track_u.interactor()
             #cv2.waitKey(30)




                 # if self._interactor_map:
                 #     interactor = self._interactor_map[rt]
                 #     interactor.interact()



