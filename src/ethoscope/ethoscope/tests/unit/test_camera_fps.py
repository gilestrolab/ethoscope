#!/usr/bin/env python3
"""
Unit tests for camera FPS resolution.

Regression coverage for the bug where the device ``maxfps_setting`` (a *tracking*
speed limit) was incorrectly clamping the FPS requested for video recording.

The expected behaviour is:

* Tracking creates the camera without an explicit ``target_fps`` -> the camera
  falls back to ``maxfps_setting``.
* Video recording passes an explicit ``target_fps`` (the recorder's FPS field)
  -> that value is honoured as-is, even if it exceeds ``maxfps_setting``.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ethoscope.hardware.input.cameras import V4L2Camera


def _fake_capture():
    """A cv2.VideoCapture stand-in returning a single valid colour frame."""
    capture = MagicMock()
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    capture.read.return_value = (True, frame)
    capture.isOpened.return_value = True
    return capture


@pytest.fixture
def patched_camera_env():
    """Patch hardware/sleep dependencies so V4L2Camera.__init__ runs headless."""
    with (
        patch(
            "ethoscope.hardware.input.cameras.cv2.VideoCapture",
            return_value=_fake_capture(),
        ),
        patch(
            "ethoscope.hardware.input.cameras.pi.get_maxfps_setting", return_value=5
        ) as maxfps,
        patch("ethoscope.hardware.input.cameras.time.sleep"),
        patch.object(V4L2Camera, "_warm_up"),
    ):
        yield maxfps


def test_recording_fps_above_maxfps_is_honoured(patched_camera_env):
    """Explicit (recording) FPS above maxfps_setting must NOT be clamped."""
    # maxfps_setting is 5, recorder requests 20 (its FPS field).
    cam = V4L2Camera(device=0, target_fps=20, target_resolution=(960, 720))
    assert cam._target_fps == 20.0
    assert cam.fps == 20.0


def test_tracking_defaults_to_maxfps_setting(patched_camera_env):
    """With no explicit target_fps (tracking), fall back to maxfps_setting."""
    cam = V4L2Camera(device=0, target_fps=None, target_resolution=(960, 720))
    assert cam._target_fps == 5.0


def test_explicit_fps_below_maxfps_is_honoured(patched_camera_env):
    """An explicit FPS below the cap is still used verbatim."""
    cam = V4L2Camera(device=0, target_fps=3, target_resolution=(960, 720))
    assert cam._target_fps == 3.0
