import time
import logging
import os

from ethoscope import trackers
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.hardware.input.cameras import OurPiCameraAsync
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.utils.io import ResultWriter
from ethoscope.drawers.drawers import DefaultDrawer
import multiprocessing
import traceback
import numpy as np

__author__ = 'quentin'

from ethoscope.core.tracking_unit import TrackingUnit
import logging
import traceback


class Monitor(object):

    def __init__(self, camera, tracker_class,
                 rois = None, stimulators=None,
                 *args, **kwargs  # extra arguments for the tracker objects
                 ):
        r"""
        Class to orchestrate the tracking of multiple objects.
        It performs, in order, the following actions:

         * Requesting raw frames (delegated to :class:`~ethoscope.hardware.input.cameras.BaseCamera`)
         * Cutting frame portions according to the ROI layout (delegated to :class:`~ethoscope.core.tracking_unit.TrackingUnit`).
         * Detecting animals and computing their positions and other variables (delegated to :class:`~ethoscope.trackers.trackers.BaseTracker`).
         * Using computed variables to interact physically (i.e. feed-back) with the animals (delegated to :class:`~ethoscope.stimulators.stimulators.BaseStimulator`).
         * Drawing results on a frame, optionally saving video (delegated to :class:`~ethoscope.drawers.drawers.BaseDrawer`).
         * Saving the result of tracking in a database (delegated to :class:`~ethoscope.utils.io.ResultWriter`).

        :param camera: a camera object responsible of acquiring frames and associated time stamps
        :type camera: :class:`~ethoscope.hardware.input.cameras.BaseCamera`
        :param tracker_class: The algorithm that will be used for tracking. It must inherit from :class:`~ethoscope.trackers.trackers.BaseTracker`
        :type tracker_class: class
        :param rois: A list of region of interest.
        :type rois: list(:class:`~ethoscope.core.roi.ROI`)
        :param stimulators: The class that will be used to analyse the position of the object and interact with the system/hardware.
        :type stimulators: list(:class:`~ethoscope.stimulators.stimulators.BaseInteractor`
        :param args: additional arguments passed to the tracking algorithm
        :param kwargs: additional keyword arguments passed to the tracking algorithm
        """

        self._camera = camera
        self._last_frame_idx =0
        self._force_stop = False
        self._last_positions = {}
        self._last_time_stamp = 0
        self._is_running = False


        if rois is None:
            raise NotImplementedError("rois must exist (cannot be None)")

        if stimulators is None:
            self._unit_trackers = [TrackingUnit(tracker_class, r, None, *args, **kwargs) for r in rois]

        elif len(stimulators) == len(rois):
            self._unit_trackers = [TrackingUnit(tracker_class, r, inter, *args, **kwargs) for r, inter in zip(rois, stimulators)]
        else:
            raise ValueError("You should have one interactor per ROI")

    @property
    def last_positions(self):
        """
        :return: The last positions (and other recorded variables) of all detected animals
        :rtype: dict
        """
        return self._last_positions

    @property
    def last_time_stamp(self):
        """
        :return: The time, in seconds, since monitoring started running. It will be 0 if the monitor is not running yet.
        :rtype: float
        """
        time_from_start = self._last_time_stamp / 1e3
        return time_from_start

    @property
    def last_frame_idx(self):
        """
        :return: The number of the last acquired frame.
        :rtype: int
        """
        return self._last_frame_idx

    def stop(self):
        """
        Interrupts the `run` method. This is meant to be called by another thread to stop monitoring externally.
        """
        self._force_stop = True

    def run(self, result_writer = None, drawer = None):
        """
        Runs the monitor indefinitely.

        :param result_writer: A result writer used to control how data are saved. `None` means no results will be saved.
        :type result_writer: :class:`~ethoscope.utils.io.ResultWriter`
        :param drawer: A drawer to plot the data on frames, display frames and/or save videos. `None` means none of the aforementioned actions will performed.
        :type drawer: :class:`~ethoscope.drawers.drawers.BaseDrawer`
        """
        t0 = time.time()
        try:
            logging.info("Monitor starting a run")
            self._is_running = True

            for i,(t, frame) in enumerate(self._camera):

                if self._force_stop:
                    logging.info("Monitor object stopped from external request")
                    break

                self._last_frame_idx = i
                self._last_time_stamp = t
                self._frame_buffer = frame

                for j,track_u in enumerate(self._unit_trackers):
                    data_rows = track_u.track(t, frame)

                    if len(data_rows) == 0:
                        self._last_positions[track_u.roi.idx] = []
                        continue
                    if j == 0:
                        print((data_rows[0]["x"] / float(track_u.roi.get_feature_dict()["w"])))
                    abs_pos = track_u.get_last_positions(absolute=True)


                    # if abs_pos is not None:
                    self._last_positions[track_u.roi.idx] = abs_pos

                    if not result_writer is None:
                        result_writer.write(t,track_u.roi, data_rows)

                if result_writer is not None:
                    result_writer.flush(t, frame)

                if drawer is not None:
                    drawer.draw(frame, self._last_positions, self._unit_trackers)

                print((t - t0, np.mean(frame)))

                t0= t


        except Exception as e:
            logging.error("Monitor closing with an exception: '%s'" % traceback.format_exc())
            raise e

        finally:
            self._is_running = False
            logging.info("Monitor closing")






cap = OurPiCameraAsync(target_fps=2)
r = SleepMonitorWithTargetROIBuilder()

tracker_cls = AdaptiveBGModel
rois = r.build(cap)
_db_credentials = {"name": "ethoscope_db",
                      "user": "ethoscope",
                      "password": "ethoscope"}

rw = ResultWriter(_db_credentials, rois, take_frame_shots=True)

m = Monitor(cap, tracker_cls, rois)

dr = DefaultDrawer()
m.run(result_writer=rw, drawer=dr)
