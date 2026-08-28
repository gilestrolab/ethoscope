#!/usr/bin/env python3
"""
Unit tests for the AGC exposure mode used during acquisition.

``FrameDurationLimits`` does not buy the long exposures it appears to. libcamera's
AGC only requests shutter values from its tuning file's exposure-mode table, and
the ``normal`` table used by default stops at 66.7 ms on every Raspberry Pi
tuning file, NoIR or not. ``_MAX_EXPOSURE_US`` (200 ms) is therefore unreachable,
and in the dark phase the camera sits pinned at that ceiling, underexposed.

The ``long`` table in the same file runs to 120 ms and is selected at runtime, so
no forked tuning file has to be shipped. Measured on a Pi 3 with an imx219, IR
backlight only and gain pinned at 3.0:

===========  ==========  =============  ========  =====
mode         mean grey   exposure       noise     SNR
===========  ==========  =============  ========  =====
normal       57.4        66.7 ms        1.98      29.0
long         79.5        120.0 ms       1.84      43.3
===========  ==========  =============  ========  =====

With the daylight LED on the two are indistinguishable (SNR 81.0 against 81.9),
because the first four table entries are identical. That is what makes the
setting safe to apply unconditionally, and it is the property pinned below.
"""

import queue
from unittest.mock import MagicMock, patch

import pytest

from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import PiFrameGrabber2


class _FakeExposureModeEnum:
    Normal = 0
    Short = 1
    Long = 2


class _FakeLibcameraControls:
    AeExposureModeEnum = _FakeExposureModeEnum


def _make_grabber(target_fps=5, record_video=False, exposure_decoupled=True):
    """Build a PiFrameGrabber2 without touching any hardware."""
    with patch.object(cameras.pi, "get_gain_setting", return_value=3.0):
        return PiFrameGrabber2(
            target_fps,
            (1280, 960),
            queue.Queue(maxsize=1),
            queue.Queue(maxsize=1),
            video_prefix=None,
            record_video=record_video,
            exposure_decoupled=exposure_decoupled,
        )


class TestLongExposureMode:
    def test_the_long_agc_table_is_selected(self):
        """Regression: the default table caps at 66.7 ms, not _MAX_EXPOSURE_US."""
        grabber = _make_grabber()
        with patch.object(cameras, "libcamera_controls", _FakeLibcameraControls):
            controls = grabber._build_camera_controls()

        assert controls["AeExposureMode"] == _FakeExposureModeEnum.Long

    def test_it_is_set_for_video_too(self):
        """Frame duration bounds exposure there anyway, so this cannot overshoot."""
        grabber = _make_grabber(record_video=True, exposure_decoupled=False)
        with patch.object(cameras, "libcamera_controls", _FakeLibcameraControls):
            controls = grabber._build_camera_controls()

        assert controls["AeExposureMode"] == _FakeExposureModeEnum.Long
        assert controls["FrameRate"] == 5

    def test_the_rest_of_the_controls_are_untouched(self):
        """The gain must stay pinned; the exposure mode is the only addition."""
        grabber = _make_grabber()
        with patch.object(cameras, "libcamera_controls", _FakeLibcameraControls):
            controls = grabber._build_camera_controls()

        assert controls["ExposureTime"] == 0
        assert controls["AnalogueGain"] == 3.0
        assert controls["AwbEnable"] is False
        assert controls["FrameDurationLimits"] == (
            PiFrameGrabber2._MIN_FRAME_DURATION_US,
            PiFrameGrabber2._MAX_EXPOSURE_US,
        )

    def test_it_is_omitted_when_libcamera_is_absent(self):
        """Off a Pi there is no libcamera, and the control must not be invented."""
        grabber = _make_grabber()
        with patch.object(cameras, "libcamera_controls", None):
            controls = grabber._build_camera_controls()

        assert "AeExposureMode" not in controls
        # Everything else still has to be there.
        assert controls["AnalogueGain"] == 3.0


@pytest.mark.parametrize("decoupled", [True, False])
def test_exposure_mode_is_independent_of_the_fps_regime(decoupled):
    """It is an AGC table choice, so neither acquisition path should skip it."""
    grabber = _make_grabber(exposure_decoupled=decoupled)
    with patch.object(cameras, "libcamera_controls", _FakeLibcameraControls):
        controls = grabber._build_camera_controls()

    assert controls["AeExposureMode"] == _FakeExposureModeEnum.Long
