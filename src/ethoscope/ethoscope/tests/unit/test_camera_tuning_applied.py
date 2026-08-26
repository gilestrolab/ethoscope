#!/usr/bin/env python3
"""
Unit tests for *applying* the NoIR tuning file, as opposed to resolving it.

Resolving the right file (covered in ``test_camera_tuning.py``) turned out not
to be enough: on a Pi 4 running libcamera 0.7 the correct file was resolved,
recorded in ``/etc/ethoscope/camera-tuning``, and then not used at all. Two
mechanics in picamera2 caused it, and both are pinned here.

* ``LIBCAMERA_RPI_TUNING_FILE`` is read once, when the libcamera
  ``CameraManager`` registers the sensor. The attached-camera probe starts that
  manager, so a tuning exported *after* the probe - which is all the
  ``Picamera2(tuning=...)`` argument does - is silently ignored and the camera
  runs on the default *colour* tuning. Under IR illumination that is about
  three times too dark and the ROI targets stop being detectable.

* Handed a parsed dict, picamera2 dumps it to a ``NamedTemporaryFile`` and
  exports *that* path. The temp file is unlinked when the camera closes, so the
  next acquisition in the same process starts a ``CameraManager`` pointed at a
  path that no longer exists; libcamera then fails to register the sensor and
  every later attempt reports "no camera number 0" until the process restarts.
  That is what made one failed tracking run wedge the camera until reboot.
"""

import os
import queue
from unittest.mock import MagicMock, patch

import pytest

from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import PiFrameGrabber2

TUNING = "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"
ENV_VAR = "LIBCAMERA_RPI_TUNING_FILE"


@pytest.fixture
def clean_env():
    """Run with a known-empty tuning variable and restore it afterwards."""
    previous = os.environ.pop(ENV_VAR, None)
    try:
        yield
    finally:
        os.environ.pop(ENV_VAR, None)
        if previous is not None:
            os.environ[ENV_VAR] = previous


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


class TestTuningExport:
    """What _select_tuning_file() leaves in the environment."""

    def test_resolved_tuning_is_exported_as_a_path(self, clean_env):
        """libcamera is pointed at the file on disk, not at a temporary copy."""
        grabber = _make_grabber()
        with patch.object(cameras.pi, "get_camera_tuning_file", return_value=TUNING):
            with patch.object(cameras, "Picamera2", MagicMock()):
                path, problem = grabber._select_tuning_file()

        assert path == TUNING
        assert problem is None
        assert os.environ[ENV_VAR] == TUNING

    def test_unresolved_tuning_clears_a_stale_variable(self, clean_env):
        """A path left by an earlier acquisition must not stay in force.

        Regression: the stale value is typically a deleted temp file, and
        libcamera reacts to that by refusing to register the sensor at all.
        """
        os.environ[ENV_VAR] = "/tmp/tmp-deleted-by-the-previous-run"
        grabber = _make_grabber()
        with patch.object(cameras.pi, "get_camera_tuning_file", return_value=None):
            path, problem = grabber._select_tuning_file()

        assert path is None
        assert ENV_VAR not in os.environ
        assert "No NoIR tuning file" in problem

    def test_unloadable_tuning_is_named_and_not_exported(self, clean_env):
        """A malformed file must fail here, where it can still be named.

        Left to libcamera, an unloadable tuning stops the sensor registering,
        which then reads as absent hardware.
        """
        broken = MagicMock()
        broken.load_tuning_file.side_effect = ValueError("bad json")

        grabber = _make_grabber()
        with patch.object(cameras.pi, "get_camera_tuning_file", return_value=TUNING):
            with patch.object(cameras, "Picamera2", broken):
                path, problem = grabber._select_tuning_file()

        assert path is None
        assert ENV_VAR not in os.environ
        assert TUNING in problem
        assert "bad json" in problem


class TestTuningIsInForceBeforeTheProbe:
    """The ordering inside run(), which is what actually decides the tuning."""

    def test_environment_is_set_before_the_camera_manager_starts(self, clean_env):
        """The probe starts libcamera, so the tuning must already be exported."""
        seen = {}

        fake_picamera2 = MagicMock()
        fake_picamera2.global_camera_info.side_effect = lambda: (
            seen.setdefault("env", os.environ.get(ENV_VAR)),
            [{"Model": "imx219"}],
        )[1]

        grabber = _make_grabber()
        # Pre-fill the stop queue so the capture loop exits on its first check.
        grabber._stop_queue.put(None)

        with patch.object(cameras.pi, "get_camera_tuning_file", return_value=TUNING):
            with patch.object(cameras.pi, "set_camera_tuning_status"):
                with patch.object(grabber, "_save_camera_info"):
                    with patch.object(cameras, "Picamera2", fake_picamera2):
                        grabber.run()

        assert seen["env"] == TUNING, (
            "the tuning was exported after the probe had already started the "
            "libcamera CameraManager, so libcamera never saw it"
        )

    def test_camera_is_constructed_with_a_path_not_a_parsed_dict(self, clean_env):
        """A dict makes picamera2 export a temp file that later dangles."""
        fake_picamera2 = MagicMock()
        fake_picamera2.global_camera_info.return_value = [{"Model": "imx219"}]

        grabber = _make_grabber()
        grabber._stop_queue.put(None)

        with patch.object(cameras.pi, "get_camera_tuning_file", return_value=TUNING):
            with patch.object(cameras.pi, "set_camera_tuning_status"):
                with patch.object(grabber, "_save_camera_info"):
                    with patch.object(cameras, "Picamera2", fake_picamera2):
                        grabber.run()

        fake_picamera2.assert_called_once_with(tuning=TUNING)
