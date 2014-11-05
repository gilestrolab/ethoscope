__author__ = 'quentin'

import roi_builders as rbs
from tracking_unit import TrackingUnit
import logging
import cv2


import pandas as pd


class Monitor(object):

    def __init__(self, camera, tracker_class, rois = None, interactors=None, out_file=None, draw_results=False, draw_every_n=1):

        self._camera = camera
        self._out_file = out_file
        self._draw_results = draw_results
        self.draw_every_n = draw_every_n

        if rois is None:
            rois = rbs.DefaultROIBuilder(camera)()

        self._camera.restart()


        if interactors is None:
            self._unit_trackers = [TrackingUnit(tracker_class, r, None) for r in rois]

        elif len(interactors) == len(rois):
            self._unit_trackers = [TrackingUnit(tracker_class, r, inter) for r, inter in zip(rois, interactors)]
        else:
            raise ValueError("You should have one interactor per ROI")



    def _draw_on_frame(self, frame, wait = 1):

        frame = frame.copy()
        for track_u in self._unit_trackers:
            pos = track_u.get_last_position(absolute=True)
            cv2.putText(frame, str(track_u.roi.value + 1),track_u.roi.offset, cv2.FONT_HERSHEY_COMPLEX_SMALL, 0.75, (255,255,0))
            if pos is None:
                continue
            if "interact" in pos.keys() and pos["interact"]:
                colour = (0, 255, 255)
            else:
                colour = (0, 0, 255)
            cv2.drawContours(frame,[track_u.roi.polygon],-1, colour, 1, cv2.CV_AA)
            cv2.ellipse(frame,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),(255,0,0),1,cv2.CV_AA)


        cv2.imshow("el", frame)
        cv2.waitKey(wait)


    def run(self):
        out  = []
        try:
            for i,(t, frame) in enumerate(self._camera):
                # if vw is None:
                    # vw = None
                    # vw = cv2.VideoWriter("/home/quentin/Desktop/new_tracker_show_off_speed=x60.avi", cv2.cv.CV_FOURCC(*'DIVX'), 50, (frame.shape[1], frame.shape[0]))


                for track_u in self._unit_trackers:
                    data_row = track_u(t, frame)
                    if data_row is None:
                        continue

                    if self._out_file is not None:
                        out.append(data_row)

                if self._draw_results and i % self.draw_every_n == 0:
                    self._draw_on_frame(frame)

                # vw.write(copy)

        except KeyboardInterrupt:
            if self._out_file is not None:
                df = pd.DataFrame(out)
                df.to_csv(self._out_file)
            #vw.release()
