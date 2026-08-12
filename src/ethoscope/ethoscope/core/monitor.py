__author__ = "quentin"

import datetime
import logging
import time
import traceback

import cv2
import numpy as np

from .tracking_unit import TrackingUnit


class Monitor:

    def __init__(
        self,
        camera,
        tracker_class,
        rois=None,
        reference_points=None,
        stimulators=None,
        time_offset=0,
        *args,
        **kwargs,  # extra arguments for the tracker objects
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
        :param reference_points: A list containing the coordinates of the points used to build the ROIs
        :type reference_points: list
        :param stimulators: The class that will be used to analyse the position of the object and interact with the system/hardware.
        :type stimulators: list(:class:`~ethoscope.stimulators.stimulators.BaseInteractor`)
        :param time_offset: The time offset in milliseconds to start the experiment from.
        :type time_offset: int
        :param args: additional arguments passed to the tracking algorithm
        :param kwargs: additional keyword arguments passed to the tracking algorithm
        """

        self._camera = camera
        self._last_frame_idx = 0
        self._force_stop = False
        self._last_positions = {}
        self._time_offset = time_offset
        self._last_time_stamp = self._time_offset
        self._is_running = False
        self._reference_points = reference_points

        # Acquisition-quality diagnostics, refreshed on a slow interval so they
        # cost nothing on the tracking hot path. See _collect_diagnostics().
        self._diagnostics = {}
        self._last_diagnostics_t = None

        if rois is None:
            raise NotImplementedError("rois must exist (cannot be None)")

        if stimulators is None:
            self._unit_trackers = [
                TrackingUnit(tracker_class, r, None, *args, **kwargs) for r in rois
            ]

        elif len(stimulators) == len(rois):
            self._unit_trackers = [
                TrackingUnit(tracker_class, r, inter, *args, **kwargs)
                for r, inter in zip(rois, stimulators, strict=False)
            ]
        else:
            raise ValueError("You should have one interactor per ROI")

    # How often the diagnostics are refreshed, in milliseconds. Noise and focus
    # drift on the scale of the room, not the frame, so once a minute is ample
    # and keeps the cost off the tracking loop.
    _DIAGNOSTICS_INTERVAL = 60 * 1000

    # Quantile of the per-frame displacement distribution taken as the noise
    # floor. Most animals are quiescent at any moment, so the low tail of the
    # distribution is the tracker's jitter rather than real movement - which
    # means the floor can be measured without knowing which animals are asleep.
    _JITTER_QUANTILE = 10

    # Below this many observed positions the quantile is meaningless, so no
    # number is reported rather than a misleading one.
    _MIN_JITTER_SAMPLES = 30

    @property
    def diagnostics(self):
        """
        :return: The most recent acquisition-quality measurements: image noise,\
            focus and tracker jitter. Empty until the first sample is taken.
        :rtype: dict
        """
        return self._diagnostics

    def _collect_diagnostics(self, t, frame):
        """
        Sample acquisition quality: how noisy the image is, how sharp it is, and
        how much the tracked position jitters.

        These are the three quantities behind the sleep-scoring problem in issue
        #222. Image noise and focus are the candidate *causes* of centroid
        jitter, and jitter is the *effect* that gets scored as movement, so all
        three are recorded together: which cause dominates is then a question
        the data answers rather than one we have to assume.

        Everything is derived from state the tracker already keeps, so nothing
        is added to the per-frame path. Failures are swallowed: diagnostics must
        never interrupt an experiment.

        Args:
            t (int): Current frame timestamp, in milliseconds.
            frame (numpy.ndarray): The current frame.
        """
        try:
            noises = []
            jitters = []

            for track_u in self._unit_trackers:
                # Guarded per ROI: one misbehaving tracker must cost its own
                # sample, not the whole plate's.
                try:
                    tracker = track_u.tracker

                    noise = None
                    if hasattr(tracker, "image_noise"):
                        noise = tracker.image_noise()
                    if noise is not None:
                        noises.append(noise)

                    jitter = self._roi_jitter(tracker)
                    if jitter is not None:
                        jitters.append(jitter)

                except Exception as e:
                    logging.warning(f"Could not sample diagnostics for an ROI: {e}")

            self._diagnostics = {
                "t": t,
                # Grey levels: sensor noise, driven by illumination and gain.
                "image_noise": float(np.median(noises)) if noises else None,
                # Variance of the Laplacian: high is sharp, low is defocused.
                "sharpness": self._frame_sharpness(frame),
                # Fraction of ROI width: the noise floor of the movement signal,
                # in the same units as the movement threshold itself.
                "jitter": float(np.median(jitters)) if jitters else None,
                "n_rois_sampled": len(jitters),
            }

        except Exception:
            logging.warning(
                f"Could not collect tracking diagnostics: {traceback.format_exc()}"
            )

    @staticmethod
    def _frame_sharpness(frame):
        """
        Focus proxy: the variance of the Laplacian of the frame.

        Defocus is the second candidate cause of centroid jitter - a blurred
        blob has poorly defined edges, so its centroid wanders even in a clean
        image. Computed on the whole frame rather than per ROI because focus is
        a property of the optics.

        Args:
            frame (numpy.ndarray): The current frame.

        Returns:
            float: Variance of the Laplacian, or None if it cannot be computed.
        """
        try:
            if frame is None:
                return None
            grey = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            return float(cv2.Laplacian(grey, cv2.CV_64F).var())
        except Exception:
            return None

    @classmethod
    def _roi_jitter(cls, tracker):
        """
        Noise floor of the movement signal for one ROI.

        Takes a low quantile of the per-frame displacements the tracker has
        already recorded, which is the jitter of a quiescent animal. Inferred
        positions are excluded: inference repeats the previous displacement
        verbatim, so including them would bias the floor with values that were
        never measured (the same artefact that produced ghost movement bouts in
        issue #224).

        Args:
            tracker: The tracker whose rolling history is sampled.

        Returns:
            float: Displacement as a fraction of ROI width, or None if the
                history is too short to estimate one.
        """
        try:
            distances = []

            for points in tracker.positions:
                if not points:
                    continue
                point = points[0]
                if point.get("is_inferred", False):
                    continue
                # Stored as log10(distance) * 1000, distance being a fraction of
                # the ROI width.
                distances.append(10.0 ** (point["xy_dist_log10x1000"] / 1000.0))

            if len(distances) < cls._MIN_JITTER_SAMPLES:
                return None

            return float(np.percentile(distances, cls._JITTER_QUANTILE))

        except Exception:
            return None

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

    def run(self, result_writer=None, drawer=None, verbose=False):
        """
        Runs the monitor indefinitely.

        :param result_writer: A result writer used to control how data are saved. `None` means no results will be saved.
        :type result_writer: :class:`~ethoscope.utils.io.ResultWriter`
        :param drawer: A drawer to plot the data on frames, display frames and/or save videos. `None` means none of the aforementioned actions will performed.
        :type drawer: :class:`~ethoscope.drawers.drawers.BaseDrawer`
        """

        try:
            logging.info("Monitor starting a run")
            self._is_running = True

            for i, (t, frame) in enumerate(self._camera):

                # This is useful feedback when we do offline tracking
                if verbose and t % 5000 == 0:
                    print(str(datetime.timedelta(milliseconds=t)), end="\r", flush=True)

                if self._force_stop:
                    logging.info("Monitor object stopped from external request")
                    break

                self._last_frame_idx = i
                self._last_time_stamp = t + self._time_offset
                self._frame_buffer = frame

                # Adjust timestamp for database writes when appending
                t_with_offset = t + self._time_offset

                for _j, track_u in enumerate(self._unit_trackers):
                    data_rows = track_u.track(t, frame)
                    if len(data_rows) == 0:
                        self._last_positions[track_u.roi.idx] = []
                        continue

                    abs_pos = track_u.get_last_positions(absolute=True)

                    # if abs_pos is not None:
                    self._last_positions[track_u.roi.idx] = abs_pos

                    if result_writer is not None:
                        result_writer.write(t_with_offset, track_u.roi, data_rows)

                if result_writer is not None:
                    result_writer.flush(t_with_offset, frame)

                if drawer is not None:
                    drawer.draw(
                        frame,
                        self._last_positions,
                        self._unit_trackers,
                        self._reference_points,
                    )

                if (
                    self._last_diagnostics_t is None
                    or t - self._last_diagnostics_t >= self._DIAGNOSTICS_INTERVAL
                ):
                    self._last_diagnostics_t = t
                    self._collect_diagnostics(t, frame)

                self._last_t = t
                time.sleep(0.001)

        except Exception as e:
            logging.error(
                f"Monitor closing with an exception: '{traceback.format_exc()}'"
            )
            raise e

        finally:
            self._is_running = False
            logging.info(f"Monitor closing - processed {i} frames")
            if verbose:
                print(f"Monitor closing - processed {i} frames")
