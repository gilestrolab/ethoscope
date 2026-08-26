#!/usr/bin/env python3
"""
Unit tests for the "no camera on the CSI bus" guard.

A camera missing from the bus - an unseated ribbon cable, a dead sensor - used
to be reported as anything but that: first a complaint that no NoIR tuning file
could be resolved, then ``IndexError: list index out of range`` raised from
inside picamera2, and finally, because that message matches none of the hardware
keywords the grabber looks for, a 30 s wait for a first frame that was never
coming. These tests pin the diagnosis to the actual cause.
"""

import logging
import queue
import threading
from unittest.mock import MagicMock, patch

import pytest

from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import OurPiCameraAsync, PiFrameGrabber2
from ethoscope.utils.debug import EthoscopeException


def _make_grabber():
    """
    Build a PiFrameGrabber2 without touching any hardware.

    Returns:
        PiFrameGrabber2: a grabber whose queues can be inspected by the test.
    """
    with patch.object(cameras.pi, "get_gain_setting", return_value=3.0):
        return PiFrameGrabber2(
            5,
            (1280, 960),
            queue.Queue(maxsize=1),
            queue.Queue(maxsize=1),
        )


class TestNoCameraGuard:
    """The grabber's own reaction to an empty camera list."""

    def test_empty_camera_list_is_named_and_signalled(self, caplog):
        """No attached camera: say so, flag it, and hand None to the parent."""
        fake_picamera2 = MagicMock()
        fake_picamera2.global_camera_info.return_value = []

        grabber = _make_grabber()
        with patch.object(cameras, "Picamera2", fake_picamera2):
            with caplog.at_level(logging.ERROR):
                grabber.run()

        assert grabber.no_camera_detected is True
        assert grabber._queue.get_nowait() is None
        # The camera is never constructed, so picamera2 gets no chance to raise
        # its IndexError from global_camera_info()[camera_num].
        fake_picamera2.assert_not_called()

        message = caplog.text
        assert "No camera detected on the CSI bus" in message
        assert "ribbon cable" in message
        assert "vcgencmd get_camera" in message
        # The tuning file is resolved further down run(), so the misleading
        # "no NoIR tuning file" error can no longer precede the real cause.
        assert "tuning" not in message.lower()

    def test_unqueryable_camera_list_does_not_block_startup(self, caplog):
        """If the probe itself fails, carry on - construction will report it."""
        fake_picamera2 = MagicMock()
        fake_picamera2.global_camera_info.side_effect = RuntimeError("libcamera busy")
        # Fail at construction too, so run() returns instead of entering the
        # capture loop. Any error will do; what matters is that we got there.
        fake_picamera2.side_effect = RuntimeError("no such device")

        grabber = _make_grabber()
        with patch.object(cameras, "Picamera2", fake_picamera2):
            with patch.object(cameras.pi, "get_camera_tuning_file", return_value=None):
                with caplog.at_level(logging.WARNING):
                    grabber.run()

        assert grabber.no_camera_detected is False
        fake_picamera2.assert_called()
        assert "Could not query the list of attached cameras" in caplog.text
        assert "No camera detected on the CSI bus" not in caplog.text


class _AbsentCameraGrabber(threading.Thread):
    """A stand-in grabber that finds no camera, as PiFrameGrabber2 now does."""

    instances = []

    def __init__(self, target_fps, target_resolution, frame_queue, stop_queue, **kw):
        super().__init__()
        self._queue = frame_queue
        self.no_camera_detected = False
        type(self).instances.append(self)

    def run(self):
        self.no_camera_detected = True
        self._queue.put(None)


class TestMissingCameraIsTerminal:
    """The parent must fail once, with the reason, rather than retry."""

    def test_camera_absence_fails_without_a_second_attempt(self):
        """No retry, and an error naming the bus rather than a frame timeout."""
        _AbsentCameraGrabber.instances = []

        with patch.object(cameras, "USE_PICAMERA2", True):
            with patch.object(cameras, "PiFrameGrabber2", _AbsentCameraGrabber):
                with patch.object(
                    OurPiCameraAsync,
                    "_perform_camera_cleanup",
                    staticmethod(MagicMock()),
                ):
                    with pytest.raises(EthoscopeException) as excinfo:
                        OurPiCameraAsync(target_fps=5, target_resolution=(1280, 960))

        error = str(excinfo.value)
        # ControlThread._run() keys off this phrasing to route the failure to
        # the gentle stopped-with-error path instead of a fatal traceback.
        assert "Camera hardware not available" in error
        assert "no camera is attached to the CSI bus" in error
        assert "ribbon cable" in error
        # Retrying cannot attach a camera; a second attempt would only rephrase
        # the failure as a picamera2 fallback problem.
        assert len(_AbsentCameraGrabber.instances) == 1
