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

        pos = track_u.get_last_position(absolute=True)


        cv2.putText(frame, str(track_u.roi.idx+1),track_u.roi.offset, cv2.FONT_HERSHEY_COMPLEX_SMALL,0.75,(255,255,0))

        if pos is None:
            return

        if row["interact"]:

            colour = (0, 255, 255)
        else:
            colour = (0, 0, 255)

        cv2.drawContours(frame,[track_u.roi.polygon],-1, colour, 1, cv2.CV_AA)
        cv2.ellipse(frame,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),(255,0,0),1,cv2.CV_AA)


    def run(self):
        out  = []

        SHOW_N_FRAMES = 1
        try:
            for k,(t, frame) in enumerate(self._camera):
                # if vw is None:
                    # vw = None
                    # vw = cv2.VideoWriter("/home/quentin/Desktop/new_tracker_show_off_speed=x60.avi", cv2.cv.CV_FOURCC(*'DIVX'), 50, (frame.shape[1], frame.shape[0]))
                if k % SHOW_N_FRAMES == 0:
                    copy = frame.copy()

                for i,track_u in enumerate(self._unit_trackers):
                    # if i != 22:
                    #     continue

                    data_row = track_u(t, frame)
                    if data_row is None:
                        continue
                    data_row["roi_value"] = i
                    out.append(data_row)


                    # if i == 25:
                    #     print data_row
                    if k % SHOW_N_FRAMES == 0:
                        self._draw_on_frame(track_u, data_row, copy)

                    if "interact" in data_row and bool(data_row["interact"]):
                        print i+1


                if k % SHOW_N_FRAMES == 0:
                    cv2.imshow("el", copy)
                    cv2.waitKey(1)
                # vw.write(copy)

                print k, t / 60./ 60.
        except KeyboardInterrupt:
            df = pd.DataFrame(out)
            print df
            df.to_csv("/tmp/test.csv")
        # vw.release()
