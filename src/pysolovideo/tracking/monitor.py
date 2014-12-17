__author__ = 'quentin'

import roi_builders as rbs
from tracking_unit import TrackingUnit
import csv
import logging
import cv2
from collections import deque


class Monitor(object):

    def __init__(self, camera, tracker_class, rois = None, interactors=None, out_file=None,
                draw_results=False, draw_every_n=1,
                video_out = None,
                max_duration=None):
        """
        Class to orchestrate the tracking of several object in separate regions of interest (ROIs) and interacting

        :param camera: a camera object responsible of acquiring frames and associated time stamps.
        :type: class:`pysolovideo.tracking_unit.cameras.BaseCamera`
        :param tracker_class: The class that will be used for tracking. It must inherit from ``
        :param rois: A list of region of interest.
        :param interactors: The class that will be used for analysing the position of the object and interacting with the system/hardware.
        :param out_file: An optional output file (file or filename)
        :param draw_results: whether to draw the results of the tracking on a window (OpenCV frontend). This is mainly for debugging purposes and will result in using more resources.
        :param draw_every_n: When `draw_results` is `True`, only draw   every `draw_every_n` frames. this can help to save some CPU time.
        :param video_out: An optional filename where to write the original frames annotated with the location of the ROIs and position of the objects.
          Note that this will use quite a lot of resources since it requires 1) drawing on the frames and 2) encoding the video in real time.
        :param max_duration: tracking stops when the elapsed time is greater
        :type max_duration: float

        """

        self._camera = camera


        if out_file is None or isinstance(out_file, file):
            self._out_file = out_file
        else:
             self._out_file = open(out_file, 'wb')
        # todo ensure file has opened OK


        self._draw_results = draw_results
        self.draw_every_n = draw_every_n
        self._max_duration = max_duration
        self._video_out = video_out
        self._data_history = deque()
        self._max_history_length = 60 *1# in seconds

        if rois is None:
            rois = rbs.DefaultROIBuilder(camera)()

        self._camera.restart()


        if interactors is None:
            self._unit_trackers = [TrackingUnit(tracker_class, r, None) for r in rois]

        elif len(interactors) == len(rois):
            self._unit_trackers = [TrackingUnit(tracker_class, r, inter) for r, inter in zip(rois, interactors)]
        else:
            raise ValueError("You should have one interactor per ROI")


    @property
    def data_history(self):
        return self._data_history

    def _draw_on_frame(self, frame):

        frame_cp = frame.copy()
        for track_u in self._unit_trackers:

            pos = track_u.get_last_position(absolute=True)
            cv2.putText(frame_cp, str(track_u.roi.idx + 1), track_u.roi.offset, cv2.FONT_HERSHEY_COMPLEX_SMALL, 0.75, (255,255,0))
            if pos is None:
                continue

            # if "interact" in pos.keys() and pos["interact"]:
            #     colour = (0, 255, 255)
            # else:
            colour = (0, 0, 255)
            cv2.drawContours(frame_cp,[track_u.roi.polygon],-1, colour, 1, cv2.CV_AA)
            cv2.ellipse(frame_cp,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),(255,0,0),1,cv2.CV_AA)

        return frame_cp


    def run(self):
        if self._out_file is not None:
            header = None

            file_writer  = csv.writer(self._out_file , quoting=csv.QUOTE_NONNUMERIC)

        vw = None
        try:
            for i,(t, frame) in enumerate(self._camera):
                # if i % 60 == 0:
                #     print t/60
                #

                if self._max_duration is not None and t > self._max_duration:
                    break

                if self._video_out is not None and vw is None:
                    vw = cv2.VideoWriter(self._video_out, cv2.cv.CV_FOURCC(*'DIVX'), 50, (frame.shape[1], frame.shape[0])) # fixme the 50 is arbitrary

                for j,track_u in enumerate(self._unit_trackers):
                    # if j != 5:
                    #     continue
                    data_row = track_u(t, frame)
                    if data_row is None:
                        continue

                    self._data_history.append(data_row)


                    if len(self._data_history) > 2 and (self._data_history[-1]["t"] - self._data_history[0]["t"]) > self._max_history_length:
                        self._data_history.popleft()

                    if self._out_file is not None:
                        if header is None:
                            header = sorted(data_row.keys())
                            file_writer.writerow(header)

                            row = []
                            for f in header:
                                dt = data_row[f]
                                try:
                                    dt = round(dt,4)
                                except:
                                    pass
                                row.append(dt)

                        file_writer.writerow()


                if (self._draw_results and i % self.draw_every_n == 0) or not vw is None :
                    tmp = self._draw_on_frame(frame)
                    if (self._draw_results and i % self.draw_every_n == 0):
                        cv2.imshow("psv", tmp)
                        cv2.waitKey(10)
                        # cv2.waitKey(10)
                    if not vw is None:
                        vw.write(tmp)

        except KeyboardInterrupt:
            pass

        if not vw is None:
            vw.release()
