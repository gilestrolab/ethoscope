#!/usr/bin/env python3
"""
Unit tests for riding out a camera dropout during tracking.

On a weak power supply the camera's frontend times out and picamera2's capture
never returns; the run used to end 30 s later. The grabber now captures with a
timeout, closes the stalled camera, opens a new one and carries on, while the
camera object waits for it and a stop still gets through (ETHOSCOPE_354 and
ETHOSCOPE_358, 2026-10-02).
"""

import queue
import threading
import time
from unittest.mock import patch

import numpy as np
import pytest

from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import OurPiCameraAsync, PiFrameGrabber2
from ethoscope.utils.debug import EthoscopeException

H, W = 960, 1280


def frame(camera, n):
    """A frame tagged with the camera that made it (pixel 0) and its number (pixel 1)."""
    image = np.zeros((H * 3 // 2, W), dtype=np.uint8)
    image[0, 0], image[0, 1] = camera, n
    return image


class FakeCamera:
    """A Picamera2 that delivers ``frames`` frames, then stalls (wait times out)."""

    def __init__(self, frames, opened):
        self._left = frames
        self._n = 0
        self.camera_controls = {}
        opened.append(self)
        self._index = len(opened)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def create_video_configuration(self, **kwargs):
        return {}

    def configure(self, config):
        pass

    def set_controls(self, controls):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    @staticmethod
    def global_camera_info():
        return [{"Model": "imx219"}]

    def capture_array(self, name="main", wait=None):
        return "job"

    def wait(self, job, timeout=None):
        if self._left is not None and self._left <= 0:
            raise TimeoutError()
        if self._left is not None:
            self._left -= 1
        self._n += 1
        time.sleep(0.005)
        return frame(self._index, self._n)


def picamera2(plan, opened):
    """
    A stand-in for the Picamera2 class.

    Args:
        plan (list): One entry per camera opened: a number of frames before it
            stalls, None for frames forever, or an exception to raise on opening.
        opened (list): Receives every camera made.
    """
    plan = list(plan)

    def make(tuning=None):
        step = plan.pop(0) if plan else None
        if isinstance(step, Exception):
            raise step
        return FakeCamera(step, opened)

    make.global_camera_info = staticmethod(lambda: [{"Model": "imx219"}])
    make.set_logging = staticmethod(lambda level: None)
    return make


@pytest.fixture
def grabber():
    with patch.object(cameras.pi, "get_gain_setting", return_value=3.0):
        g = PiFrameGrabber2(5, (W, H), queue.Queue(), queue.Queue(maxsize=1))
    g.REOPEN_BACKOFF_S = (0,)
    g.WARMUP_S = 0.0
    return g


def run(grabber, plan, until, timeout=10):
    """Run the grabber in a thread until ``until(frames)`` holds, then stop it."""
    opened, frames = [], []
    patches = [
        patch.object(cameras, "Picamera2", picamera2(plan, opened)),
        patch.object(cameras.pi, "get_camera_tuning_file", return_value=None),
        patch.object(cameras.pi, "set_camera_tuning_status"),
        patch.object(cameras.pi, "underPowered", return_value=True),
        patch.object(grabber, "_save_camera_info"),
        patch.object(grabber, "_apply_live_gain"),
        patch.object(OurPiCameraAsync, "_perform_camera_cleanup"),
    ]
    for p in patches:
        p.start()
    try:
        thread = threading.Thread(target=grabber.run, daemon=True)
        thread.start()
        deadline = time.time() + timeout
        while time.time() < deadline and not until(frames):
            try:
                frames.append(grabber._queue.get(timeout=0.1))
            except queue.Empty:
                pass
        grabber._stop_queue.put(None)
        thread.join(5)
        while not grabber._queue.empty():
            frames.append(grabber._queue.get_nowait())
        return opened, frames, thread
    finally:
        for p in reversed(patches):
            p.stop()


def values(frames):
    """(camera, frame number) of every frame received."""
    return [(int(f[0, 0]), int(f[0, 1])) for f in frames if f is not None]


class TestReopen:
    def test_a_stalled_camera_is_reopened_and_frames_resume(self, grabber):
        opened, frames, thread = run(
            grabber, [3, None], until=lambda f: len(values(f)) >= 8
        )
        assert len(opened) == 2 and getattr(opened[0], "closed", False)
        assert grabber.dropouts == 1 and not grabber.recovering
        assert grabber.last_power == "under-voltage"
        assert grabber.last_recovered >= grabber.last_dropout
        assert all(f is not None for f in frames)
        got = values(frames)
        assert got[:3] == [(1, 1), (1, 2), (1, 3)]
        assert {c for c, _ in got[3:]} == {2}  # the rest from the reopened camera
        assert not thread.is_alive()

    def test_a_reopen_that_fails_is_retried(self, grabber):
        busy = RuntimeError("Camera __init__ sequence did not complete.")
        opened, frames, _ = run(
            grabber, [2, busy, busy, None], until=lambda f: len(values(f)) >= 6
        )
        assert len(opened) == 2  # the two failures made no camera
        assert grabber.dropouts == 1 and not grabber.recovering
        assert all(f is not None for f in frames)

    def test_it_gives_up_after_the_maximum_and_ends_the_iteration(self, grabber):
        grabber.MAX_REOPEN_ATTEMPTS = 3
        busy = RuntimeError("camera busy")
        opened, frames, thread = run(
            grabber,
            [2, busy, busy, busy, busy],
            until=lambda f: any(x is None for x in f),
        )
        assert grabber.gave_up and not grabber.recovering
        assert frames[-1] is None
        assert not thread.is_alive()

    def test_a_stop_during_the_back_off_is_prompt(self, grabber):
        grabber.REOPEN_BACKOFF_S = (60,)
        started = time.time()
        _, _, thread = run(
            grabber, [2, None], until=lambda f: grabber.recovering, timeout=5
        )
        assert not thread.is_alive()
        assert time.time() - started < 10

    def test_frames_are_dropped_while_exposure_settles_after_a_reopen(self, grabber):
        grabber.WARMUP_S = 0.3
        _, frames, _ = run(grabber, [2, None], until=lambda f: len(values(f)) >= 6)
        reopened = [n for c, n in values(frames) if c == 2]
        # each fake frame takes >= 5 ms, so ~0.3 s of them were never handed on
        assert reopened and reopened[0] > 5


class StubGrabber:
    recovering = False
    dropouts = 0
    last_dropout = None
    last_recovered = None
    last_power = None
    gave_up = False


def make_camera(wait_s=1):
    cam = OurPiCameraAsync.__new__(OurPiCameraAsync)
    cam._queue = queue.Queue(maxsize=1)
    cam._interrupted = threading.Event()
    cam._p = StubGrabber()
    cam._start_time = time.time()
    cam._frame_idx = 0
    cam.FRAME_WAIT_S = wait_s
    return cam


def deliver_later(cam, delay, value=7):
    threading.Timer(delay, lambda: cam._queue.put(frame(9, value))).start()


class TestCameraWaits:
    def test_it_waits_through_a_reopen(self):
        cam = make_camera(wait_s=1)
        cam._p.recovering = True
        deliver_later(cam, 2.5)
        assert cam._next_image() is not None  # 2.5 s > FRAME_WAIT_S, no raise

    def test_outside_a_reopen_it_gives_up_with_a_readable_message(self):
        cam = make_camera(wait_s=1)
        with pytest.raises(EthoscopeException) as error:
            cam._next_image()
        assert "%s" not in str(error.value) and "none for" in str(error.value)

    def test_interrupt_returns_at_once(self):
        cam = make_camera(wait_s=30)
        cam._p.recovering = True
        threading.Timer(0.3, cam.interrupt).start()
        started = time.time()
        assert cam._next_image() is None
        assert time.time() - started < 2

    def test_a_frame_is_stamped_when_it_arrives(self):
        cam = make_camera(wait_s=5)
        deliver_later(cam, 1.2)
        t, image = cam._next_time_image()
        assert image is not None and t >= 1.2

    def test_camera_state_reports_the_grabber(self):
        cam = make_camera()
        cam._p.dropouts, cam._p.last_power = 2, "under-voltage"
        state = cam.camera_state()
        assert state["dropouts"] == 2 and state["last_power"] == "under-voltage"
        assert state["recovering"] is False and state["gave_up"] is False
