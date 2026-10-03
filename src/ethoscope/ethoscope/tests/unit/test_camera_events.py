#!/usr/bin/env python3
"""
Unit tests for how a run records and reacts to camera dropouts.

The Monitor writes the gap a dropout leaves into CAMERA_EVENTS (so it is not
mistaken for missing flies), passes a stop to a camera that is waiting out a
dropout, and the control thread ends a run whose camera stopped for good instead
of leaving it "running" with nothing behind it.
"""

import tempfile
from unittest.mock import Mock, patch

import numpy as np

from ethoscope.control.tracking import ControlThread
from ethoscope.core.monitor import Monitor
from ethoscope.core.roi import ROI
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.trackers.trackers import BaseTracker


class Still(BaseTracker):
    def _find_position(self, img, mask, t):
        return []


class FakeCamera:
    """Yields frames at given times; its dropout count changes as scripted."""

    def __init__(self, times, dropouts_at=None, gave_up=False):
        self._times = times
        self._dropouts_at = dropouts_at or {}
        self._gave_up = gave_up
        self._dropouts = 0
        self.interrupted = False

    def __iter__(self):
        for t in self._times:
            self._dropouts = self._dropouts_at.get(t, self._dropouts)
            yield t, np.zeros((100, 200), np.uint8)

    def camera_state(self):
        return {"dropouts": self._dropouts, "recovering": False, "last_power": "ok",
                "gave_up": self._gave_up}  # fmt: skip

    def interrupt(self):
        self.interrupted = True


def run(camera):
    roi = ROI(np.array([[10, 10], [190, 10], [190, 40], [10, 40]]), 1)
    monitor = Monitor(camera, Still, [roi])
    writer = Mock()
    with (
        patch.object(monitor, "_collect_diagnostics"),
        patch.object(monitor, "_record_light_change"),
    ):
        monitor.run(result_writer=writer)
    return [c.args[:2] for c in writer.write_camera_event.call_args_list]


class TestCameraEvents:
    def test_a_dropout_is_written_as_the_gap_it_left(self):
        events = run(FakeCamera([0, 200, 400, 15400, 15600], dropouts_at={15400: 1}))
        assert events == [(400, "dropout"), (15400, "recovered")]

    def test_a_camera_that_gave_up_is_written_at_the_end(self):
        events = run(FakeCamera([0, 200, 400], gave_up=True))
        assert events == [(400, "gave_up")]

    def test_a_run_without_dropouts_writes_nothing(self):
        assert run(FakeCamera([0, 200, 400])) == []

    def test_stop_interrupts_a_waiting_camera(self):
        camera = FakeCamera([0])
        roi = ROI(np.array([[10, 10], [190, 10], [190, 40], [10, 40]]), 1)
        Monitor(camera, Still, [roi]).stop()
        assert camera.interrupted


class TestEndOfCamera:
    def thread(self, status="running"):
        control = ControlThread.__new__(ControlThread)
        control._info = {"status": status}
        control.stop = Mock()
        # ControlThread.__del__ removes this directory; a stand-in needs one too.
        control._tmp_dir = tempfile.mkdtemp(prefix="test_camera_events_")
        return control

    def test_a_camera_that_gave_up_ends_the_run_with_an_error(self):
        control = self.thread()
        camera = Mock()
        camera.camera_state.return_value = {"gave_up": True, "dropouts": 2,
                                            "last_power": "under-voltage"}  # fmt: skip
        control._end_if_camera_ended(camera)
        (message,) = control.stop.call_args.args
        assert "could not be reopened" in message and "power supply" in message

    def test_the_end_of_a_video_ends_the_run_cleanly(self):
        control = self.thread()
        control._end_if_camera_ended(MovieVirtualCamera.__new__(MovieVirtualCamera))
        control.stop.assert_called_once_with()

    def test_a_requested_stop_is_left_alone(self):
        control = self.thread(status="stopping")
        control._end_if_camera_ended(Mock())
        control.stop.assert_not_called()
