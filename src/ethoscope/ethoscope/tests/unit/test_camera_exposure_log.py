#!/usr/bin/env python3
"""
Unit tests for recording the exposure and gain the camera actually ran at.

With gain adaptive (exposure-first auto-exposure), the gain setting no longer says
what the camera did, and a run's noise cannot be explained without it. The grabber
reads the values back once a minute and the writer stores them in CAMERA_EXPOSURE,
a table of its own so that a resumed run gets it cleanly.
"""

import queue
import types
from unittest.mock import MagicMock, patch

import numpy as np

from ethoscope.core.monitor import Monitor
from ethoscope.core.roi import ROI
from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import OurPiCameraAsync, PiFrameGrabber2
from ethoscope.io import SQLiteResultWriter
from ethoscope.trackers.trackers import BaseTracker

METADATA = {"ExposureTime": 199900, "AnalogueGain": 1.81, "DigitalGain": 1.02}
SAMPLE = {"exposure_us": 199900, "analogue_gain": 1.81, "digital_gain": 1.02}


def make_grabber():
    with patch.object(cameras.pi, "get_gain_setting", return_value=3.0):
        return PiFrameGrabber2(
            5, (1280, 960), queue.Queue(1), queue.Queue(1), exposure_decoupled=True
        )


def fake_capture(metadata=METADATA):
    capture = MagicMock()
    capture.capture_metadata.return_value = "job"
    capture.wait.return_value = metadata
    return capture


class TestGrabberSampling:
    def test_reads_back_exposure_and_gain(self):
        grabber = make_grabber()
        grabber._sample_exposure(fake_capture())
        assert grabber.exposure == SAMPLE

    def test_once_a_minute(self):
        grabber, capture = make_grabber(), fake_capture()
        grabber._sample_exposure(capture)
        grabber._sample_exposure(capture)
        assert capture.wait.call_count == 1

    def test_a_failed_read_never_interrupts_acquisition(self):
        grabber, capture = make_grabber(), fake_capture()
        capture.wait.side_effect = TimeoutError()
        grabber._sample_exposure(capture)  # must not raise
        assert grabber.exposure is None


class TestCameraAccessor:
    def test_reports_a_copy_of_the_grabbers_values(self):
        cam = OurPiCameraAsync.__new__(OurPiCameraAsync)
        cam._p = types.SimpleNamespace(exposure=dict(SAMPLE))
        state = cam.exposure_state()
        assert state == SAMPLE and state is not cam._p.exposure

    def test_none_before_the_first_sample(self):
        cam = OurPiCameraAsync.__new__(OurPiCameraAsync)
        cam._p = types.SimpleNamespace(exposure=None)
        assert cam.exposure_state() is None


class Still(BaseTracker):
    def _find_position(self, img, mask, t):
        return []


class TestMonitorSample:
    def test_the_diagnostics_sample_carries_the_cameras_values(self):
        camera = MagicMock()
        camera.exposure_state.return_value = dict(SAMPLE)
        roi = ROI(np.array([[10, 10], [190, 10], [190, 40], [10, 40]]), 1)
        monitor = Monitor(camera, Still, [roi])
        with patch.object(monitor, "_sample_light", return_value=(None, None)):
            monitor._collect_diagnostics(60000, np.zeros((100, 200), np.uint8))
        assert {k: monitor._diagnostics[k] for k in SAMPLE} == SAMPLE


def writer():
    """A SQLite writer that records the commands it would queue."""
    w = SQLiteResultWriter.__new__(SQLiteResultWriter)
    w._database_type = "SQLite3"
    w.commands = []
    w._write_async_command = lambda command, values=None: w.commands.append(
        (command, values)
    )
    return w


class TestWriter:
    def test_a_sample_with_exposure_also_fills_camera_exposure(self):
        w = writer()
        w.write_diagnostics(60000, {"frame_noise": 0.46, **SAMPLE}, fps=5.0)
        tables = [c.split()[2] for c, _ in w.commands]
        assert tables == ["DIAGNOSTICS", "CAMERA_EXPOSURE"]
        assert w.commands[1][1] == (60000, 199900, 1.81, 1.02)

    def test_a_sample_without_exposure_writes_diagnostics_only(self):
        w = writer()
        w.write_diagnostics(60000, {"frame_noise": 0.46}, fps=5.0)
        assert [c.split()[2] for c, _ in w.commands] == ["DIAGNOSTICS"]
