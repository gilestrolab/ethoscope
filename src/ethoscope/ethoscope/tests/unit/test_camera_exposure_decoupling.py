#!/usr/bin/env python3
"""
Unit tests for decoupling the sensor exposure ceiling from the tracking FPS cap.

Regression coverage for issue #222: the device ``maxfps_setting`` (a *tracking*
CPU throttle) was being passed straight to libcamera's ``FrameRate`` control,
which pins ``FrameDurationLimits`` and therefore caps the maximum exposure time
at ``1 / FrameRate``. With a fixed analogue gain this forced shorter, noisier
exposures at higher FPS caps, jittering the tracked blob and inflating the
movement signal used for sleep scoring (spurious loss of the afternoon siesta).

Expected behaviour:

* Tracking (``exposure_decoupled=True``, not recording) -> the controls set a
  generous ``FrameDurationLimits`` (allowing long exposures) and do NOT pin
  ``FrameRate``.
* Video recording -> the exact ``FrameRate`` is pinned, exposure follows it.
"""

import queue
from unittest.mock import patch

import pytest

from ethoscope.hardware.input.cameras import PiFrameGrabber2


def _make_grabber(target_fps, *, exposure_decoupled, record_video=False, gain=1.0):
    """Instantiate a PiFrameGrabber2 without touching any camera hardware."""
    with patch(
        "ethoscope.hardware.input.cameras.pi.get_gain_setting", return_value=gain
    ):
        return PiFrameGrabber2(
            target_fps,
            (1280, 960),
            queue.Queue(maxsize=1),
            queue.Queue(maxsize=1),
            video_prefix="/tmp/prefix" if record_video else None,
            record_video=record_video,
            exposure_decoupled=exposure_decoupled,
        )


def test_tracking_mode_does_not_pin_framerate():
    """Tracking must allow long exposures instead of pinning FrameRate."""
    g = _make_grabber(10, exposure_decoupled=True)
    controls = g._build_camera_controls()

    assert "FrameRate" not in controls
    assert "FrameDurationLimits" in controls
    min_dur, max_dur = controls["FrameDurationLimits"]
    assert min_dur == PiFrameGrabber2._MIN_FRAME_DURATION_US
    assert max_dur == PiFrameGrabber2._MAX_EXPOSURE_US
    # Auto-exposure with fixed gain (the tracking-quality settings).
    assert controls["ExposureTime"] == 0
    assert controls["AnalogueGain"] == 1.0
    assert controls["AwbEnable"] is False


def test_tracking_exposure_ceiling_independent_of_fps_cap():
    """The exposure ceiling must be identical for a 5 and a 10 FPS cap.

    This is the crux of issue #222: two ethoscopes with different maxfps_setting
    must be allowed the same maximum exposure, so their movement/sleep signals
    are comparable.
    """
    c5 = _make_grabber(5, exposure_decoupled=True)._build_camera_controls()
    c10 = _make_grabber(10, exposure_decoupled=True)._build_camera_controls()
    assert c5["FrameDurationLimits"] == c10["FrameDurationLimits"]


def test_max_exposure_matches_known_good_5fps():
    """The exposure ceiling should be at least the known-good 5 FPS budget (200 ms)."""
    # 1/5 s == 200_000 us. The clean dataset was acquired at a 5 FPS ceiling, so
    # exposure must be allowed to reach that long.
    assert PiFrameGrabber2._MAX_EXPOSURE_US >= 200_000


def test_video_mode_pins_exact_framerate():
    """Recording must honour the exact requested FrameRate for playback timing."""
    g = _make_grabber(20, exposure_decoupled=False)
    controls = g._build_camera_controls()

    assert controls["FrameRate"] == 20
    assert "FrameDurationLimits" not in controls


def test_recording_overrides_decoupling():
    """Even if decoupling was requested, active recording pins FrameRate."""
    g = _make_grabber(15, exposure_decoupled=True, record_video=True)
    controls = g._build_camera_controls()

    assert controls["FrameRate"] == 15
    assert "FrameDurationLimits" not in controls


def test_default_grabber_is_exposure_coupled():
    """Backward-safe default: without the flag, behaviour is the legacy FrameRate pin."""
    g = _make_grabber(8, exposure_decoupled=False)
    assert g._exposure_decoupled is False
    assert "FrameRate" in g._build_camera_controls()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
