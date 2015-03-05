r"""
=====================
Monitor
=====================

this module does ...


--------------
subsection 1
--------------
ewsf s
gtfrdegbvtsd
gds gvdr
#
#
# >>> test
# >>> voila
"""

__author__ = 'quentin'

import roi_builders as rbs
from tracking_unit import TrackingUnit

import logging
import cv2
from collections import deque
import numpy as np
from pysolovideo.utils.debug import PSVException


# TODO
# def psv_exception_checker_decorator(*args, **kwargs):
#

class Monitor(object):

    def __init__(self, camera, tracker_class, rois = None, interactors=None,
                draw_results=False, draw_every_n=1,
                video_out = None,
                max_duration=None):
        r"""
        Class to orchestrate the tracking of several object in separate regions of interest (ROIs) and interacting

        :param camera: a camera object responsible of acquiring frames and associated time stamps.
        :type camera: :class:`~pysolovideo.tracking.cameras.BaseCamera`
        :param tracker_class: The class that will be used for tracking. It must inherit from ``
        :param rois: A list of region of interest.
        :param interactors: The class that will be used for analysing the position of the object and interacting with the system/hardware.
        :param result_writer: An optional result writer (directory name or ResultWriter)
        :param draw_results: whether to draw the results of the tracking on a window (OpenCV frontend). This is mainly for debugging purposes and will result in using more resources.
        :param draw_every_n: When `draw_results` is `True`, only draw   every `draw_every_n` frames. this can help to save some CPU time.
        :param video_out: An optional filename where to write the original frames annotated with the location of the ROIs and position of the objects.
          Note that this will use quite a lot of resources since it requires 1) drawing on the frames and 2) encoding the video in real time.
        :param max_duration: tracking stops when the elapsed time is greater
        :type max_duration: float
        """

        self._camera = camera

        self._draw_results = draw_results
        # self._result_writer = result_writer
        self._last_frame_idx =0
        if self._draw_results:
            import os
            self._window_name = "psv_" + str(os.getpid())

        self.draw_every_n = draw_every_n
        if not max_duration is None:
            self._max_duration = max_duration * 1000 # in ms
        else:
            self._max_duration = None
        
        self._video_out = video_out


        self._frame_buffer = None
        self._force_stop = False
        self._last_positions = {}
        self._last_time_stamp = 0
        self._is_running = False

        # effective fps computation
        # self._last_t = 0
        # self._fps = 0
        # self._time_diffs = []

        if rois is None:
            rois = rbs.DefaultROIBuilder()(camera)

        self._camera.restart()

        if interactors is None:
            self._unit_trackers = [TrackingUnit(tracker_class, r, None) for r in rois]

        elif len(interactors) == len(rois):
            self._unit_trackers = [TrackingUnit(tracker_class, r, inter) for r, inter in zip(rois, interactors)]
        else:
            raise ValueError("You should have one interactor per ROI")

    @property
    def last_positions(self):
        return self._last_positions

    # @property
    # def fps(self):
    #
    #     return (self._last_frame_idx +1.0) / self._last_time_stamp

    @property
    def last_time_stamp(self):
        time_from_start = self._last_time_stamp / 1e3
        return time_from_start

    @property
    def last_frame_idx(self):
        return self._last_frame_idx
    @property
    def last_drawn_frame(self):
        return self._draw_on_frame(self._frame_buffer)

    def stop(self):
        self._force_stop = True

    def _draw_on_frame(self, frame):
        if frame is None:
            return
        frame_cp = frame.copy()
        positions = self._last_positions
        for track_u in self._unit_trackers:
            # cv2.putText(frame_cp, str(track_u.roi.idx), track_u.roi.offset, cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,255,0))
            x,y = track_u.roi.offset
            y += track_u.roi.rectangle[3]/2

            cv2.putText(frame_cp, str(track_u.roi.idx), (x,y), cv2.FONT_HERSHEY_COMPLEX_SMALL, 1, (255,255,0))
            black_colour = (0, 0,0)
            roi_colour = (0, 255,0)
            cv2.drawContours(frame_cp,[track_u.roi.polygon],-1, black_colour, 3, cv2.CV_AA)
            cv2.drawContours(frame_cp,[track_u.roi.polygon],-1, roi_colour, 1, cv2.CV_AA)
            try:
                pos = positions[track_u.roi.idx]
                if pos is None:
                    continue
            except KeyError:
                continue

            # if pos["has_interacted"]:
            #     roi_colour = (0, 255,0)
            # else:
            #     roi_colour = (255,0 , 255)


            if pos["is_inferred"]== True:
                colour = (255,0,0)
            else:
                colour = (0,255,255)


            cv2.ellipse(frame_cp,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),black_colour,3,cv2.CV_AA)
            cv2.ellipse(frame_cp,((pos["x"],pos["y"]), (pos["w"],pos["h"]), pos["phi"]),colour,1,cv2.CV_AA)

        return frame_cp

    def run(self, result_writer = None):
        vw = None
        try:

            if self._draw_results:
                cv2.namedWindow(self._window_name, cv2.CV_WINDOW_AUTOSIZE)



            logging.info("Monitor starting a run")
            self._is_running = True
            for i,(t, frame) in enumerate(self._camera):



                if self._force_stop:
                    logging.info("Monitor object stopped from external request")
                    break
                elif (self._max_duration is not None and t > self._max_duration):
                    logging.info("Monitor object stopped by timeout")
                    break
                self._last_frame_idx = i
                self._last_time_stamp = t
                self._frame_buffer = frame

                if self._video_out is not None and vw is None:
                    vw = cv2.VideoWriter(self._video_out, cv2.cv.CV_FOURCC(*'DIVX'), 50, (frame.shape[1], frame.shape[0])) # fixme the 50 is arbitrary

                for j,track_u in enumerate(self._unit_trackers):
                    data_row = track_u(t, frame)

                    if data_row is None:
                        self._last_positions[track_u.roi.idx] = None
                        continue

                    abs_pos = track_u.get_last_position(absolute=True)

                    # if abs_pos is not None:
                    self._last_positions[track_u.roi.idx] = abs_pos

                    if not result_writer is None:
                        result_writer.write(t,track_u.roi, data_row)

                if not result_writer is None:
                    result_writer.flush(t, frame)

                if (self._draw_results and i % self.draw_every_n == 0) or not vw is None :
                    tmp = self._draw_on_frame(frame)
                    if (self._draw_results and i % self.draw_every_n == 0):
                        cv2.imshow(self._window_name, tmp)
                        cv2.waitKey(1)

                    if not vw is None:
                        vw.write(tmp)

                self._last_t = t

        except Exception as e:
            logging.info("Monitor closing with an exception: '%s'" % str(e))
            raise e

        finally:
            self._is_running = False
            try:
                #Fixme not working
                cv2.waitKey(1)
                cv2.destroyAllWindows()
                cv2.waitKey(1)
            except:
                pass

            if not vw is None:
                vw.release()
            logging.info("Monitor closing")


