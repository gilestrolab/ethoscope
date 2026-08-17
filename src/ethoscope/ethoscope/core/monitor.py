__author__ = "quentin"

import datetime
import logging
import os
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
        self._last_diagnostics_frame_idx = 0

        # Last light level written to LIGHT_EVENTS. A sentinel rather than None,
        # so the first observation is always recorded - including an observation
        # of zero, because "the lights were off when this run began" is itself
        # information. See _sample_light().
        self._last_light_pct = self._LIGHT_UNSET
        self._light_client = None

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
    # for an experiment and keeps the cost off the tracking loop. Calibration and
    # bench work need answers in seconds, not minutes, hence the override.
    _DIAGNOSTICS_INTERVAL = int(
        os.environ.get("ETHOSCOPE_DIAGNOSTICS_INTERVAL_MS", 60 * 1000)
    )

    # Quantile of the per-frame displacement distribution taken as the noise
    # floor. Most animals are quiescent at any moment, so the low tail of the
    # distribution is the tracker's jitter rather than real movement - which
    # means the floor can be measured without knowing which animals are asleep.
    _JITTER_QUANTILE = 10

    # Below this many observed positions the quantile is meaningless, so no
    # number is reported rather than a misleading one.
    _MIN_JITTER_SAMPLES = 30

    # Sentinel for "no light level has been observed yet", distinct from a
    # genuine reading of 0 (lights off) and from None (no daemon reachable).
    _LIGHT_UNSET = object()

    # Timeout for the light daemon status call, in seconds. Well below the
    # client default: this runs on the tracking thread, so a hung daemon must
    # cost a fraction of a frame rather than a full second of tracking.
    _LIGHT_TIMEOUT = 0.25

    def _sample_light(self):
        """
        Ask the light daemon what the panel is currently doing.

        The daemon is a separate process with its own lifetime, so this is the
        only way the tracker can know: it may be absent (no light hardware),
        stopped, or mid-fade. Any failure yields None, which is recorded as
        "unknown" rather than mistaken for darkness.

        Returns:
            tuple: (light_pct, mode), both None if the daemon cannot be reached.
                light_pct is the true commanded level 0-100, so a crepuscular
                fade reads as intermediate values.
        """
        try:
            from ethoscope.hardware.interfaces.light_daemon import (
                LightDaemonClient,
                LightDaemonUnavailable,
            )
        except Exception:
            return None, None

        try:
            if self._light_client is None:
                self._light_client = LightDaemonClient(timeout=self._LIGHT_TIMEOUT)

            status = self._light_client.status()
            if not isinstance(status, dict):
                return None, None

            level = status.get("led")
            return (
                float(level) if level is not None else None,
                status.get("mode"),
            )

        except LightDaemonUnavailable:
            # Expected on any ethoscope without a light module. Not worth a log
            # line once a minute for the lifetime of the experiment.
            return None, None
        except Exception as e:
            logging.warning(f"Could not sample the light daemon: {e}")
            return None, None

    def _record_light_change(self, t, result_writer):
        """
        Write a LIGHT_EVENTS row if the panel level has moved since the last one.

        Edge-triggered so a 12:12 cycle costs a handful of rows a day. The first
        observation of a run always counts as a change, so the starting state is
        recorded rather than left to be assumed.

        A null reading - no daemon, or one that could not be reached - is not
        an event: it would otherwise be indistinguishable from the lights going
        out, which is the one mistake this table exists to prevent.

        Args:
            t (int): Timestamp of the observation, in milliseconds.
            result_writer: The active result writer, or None.
        """
        if result_writer is None or not hasattr(result_writer, "write_light_event"):
            return

        light_pct = self._diagnostics.get("light_pct")
        if light_pct is None:
            return

        if (
            self._last_light_pct is not self._LIGHT_UNSET
            and light_pct == self._last_light_pct
        ):
            return

        self._last_light_pct = light_pct
        result_writer.write_light_event(
            t, light_pct, self._diagnostics.get("light_mode")
        )

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
                # Single-frame noise estimate: available immediately, whereas
                # image_noise waits on the background model to converge.
                "frame_noise": self._frame_noise(frame),
                # Core temperature, because dark current roughly doubles every
                # 6-8 C and its shot noise goes as the square root: a noise
                # reading cannot be interpreted without the temperature it was
                # taken at, and an enclosure or a warm room changes it.
                "cpu_temp": self._core_temperature(),
                # Variance of the Laplacian: high is sharp, low is defocused.
                "sharpness": self._frame_sharpness(frame),
                # Fraction of ROI width: the noise floor of the movement signal,
                # in the same units as the movement threshold itself.
                "jitter": float(np.median(jitters)) if jitters else None,
                "n_rois_sampled": len(jitters),
            }

            # Sampled on the same slow interval as everything else here, and on
            # the same terms: a light daemon that is missing or wedged costs a
            # null reading, never the experiment.
            light_pct, light_mode = self._sample_light()
            self._diagnostics["light_pct"] = light_pct
            self._diagnostics["light_mode"] = light_mode

        except Exception:
            logging.warning(
                f"Could not collect tracking diagnostics: {traceback.format_exc()}"
            )

    # Immerkaer's 3x3 kernel: a Laplacian-of-Laplacian that responds to noise
    # while cancelling smooth gradients and straight edges, so a single frame
    # yields a noise estimate without any temporal reference.
    _NOISE_KERNEL = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)

    @classmethod
    def _frame_noise(cls, frame):
        """
        Sensor noise estimated from a single frame, in grey levels.

        Unlike ``image_noise``, which measures deviation from the background
        model and is therefore only meaningful once that model has converged,
        this needs one frame. That makes a reading available seconds after
        tracking starts rather than minutes, which matters when sweeping a
        setting - each value otherwise costs a full convergence.

        It is also computable on a stored JPEG, so live readings and archived
        snapshots can be compared on the same scale (with the caveat that JPEG
        compression attenuates the estimate).

        Args:
            frame (numpy.ndarray): The current frame.

        Returns:
            float: Estimated Gaussian noise sigma, or None if unavailable.
        """
        try:
            if frame is None:
                return None
            grey = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = grey.shape[:2]
            if h < 3 or w < 3:
                return None
            conv = cv2.filter2D(grey.astype(np.float32), -1, cls._NOISE_KERNEL)
            return float(
                np.sqrt(np.pi / 2) * np.abs(conv).sum() / (6.0 * (w - 2) * (h - 2))
            )
        except Exception:
            return None

    @staticmethod
    def _core_temperature():
        """
        Core temperature in degrees C, or None off a Pi.

        A proxy for sensor temperature rather than a measurement of it - the
        camera sits on its own board - but it tracks the enclosure and the room,
        which is what changes between a warm afternoon and a cooled incubator.
        """
        try:
            from ethoscope.utils import pi

            return float(pi.get_core_temperature())
        except Exception:
            return None

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
                    # Achieved rate since the previous sample. Recorded next to
                    # the noise figures because the movement statistic depends
                    # on dt, so a run cannot be interpreted without it.
                    fps = None
                    if (
                        self._last_diagnostics_t is not None
                        and t > self._last_diagnostics_t
                    ):
                        fps = (i - self._last_diagnostics_frame_idx) / (
                            (t - self._last_diagnostics_t) / 1000.0
                        )

                    self._last_diagnostics_t = t
                    self._last_diagnostics_frame_idx = i
                    self._collect_diagnostics(t, frame)

                    # hasattr rather than a bare call: writers that predate the
                    # diagnostics table (or stand in for one) must not break a
                    # run just because they cannot record a sample.
                    if result_writer is not None and hasattr(
                        result_writer, "write_diagnostics"
                    ):
                        result_writer.write_diagnostics(
                            t_with_offset, self._diagnostics, fps=fps
                        )

                    self._record_light_change(t_with_offset, result_writer)

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
