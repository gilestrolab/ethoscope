#!/usr/bin/env python3
"""
Unit tests for exposure-first auto-exposure during tracking.

With the gain pinned, auto-exposure could only shorten the exposure to hold the
image's brightness, so a higher gain meant a shorter exposure and a noisier frame.
Tracking now lengthens the exposure up to the frame period before it raises gain,
through a custom exposure table in a derived copy of the sensor's tuning file,
replacing its "long" exposure mode. Measured under the IR backlight alone:
ETHOSCOPE_380 (imx219), SNR 82 with the gain pinned at its default 3.0 against 114
exposure-first; ETHOSCOPE_354 (ov5647), 84-88 against 104. Both trackers use it;
video keeps the pinned gain and the exact frame rate.
"""

import json
import os
import queue
from unittest.mock import MagicMock, patch

import pytest

from ethoscope.hardware.input import cameras
from ethoscope.hardware.input.cameras import PiFrameGrabber2


class _FakeExposureModeEnum:
    Normal = 0
    Short = 1
    Long = 2
    Custom = 3


class _FakeLibcameraControls:
    AeExposureModeEnum = _FakeExposureModeEnum


def tuning(key="shutter", channels=True):
    """A minimal vc4 tuning file with the AGC exposure-mode tables."""
    modes = {
        "normal": {
            key: [100, 10000, 30000, 60000, 66666],
            "gain": [1.0, 2.0, 4.0, 6.0, 8.0],
        },
        "long": {
            key: [100, 10000, 30000, 60000, 120000],
            "gain": [1.0, 2.0, 4.0, 6.0, 10.0],
        },
    }
    agc = {"exposure_modes": modes, "metering_modes": {}}
    return {
        "version": 2.0,
        "target": "bcm2835",
        "algorithms": [
            {"rpi.black_level": {}},
            {"rpi.agc": {"channels": [agc]} if channels else agc},
        ],
    }


def make_grabber(target_fps=5, record_video=False, exposure_decoupled=True):
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


@pytest.fixture
def base(tmp_path, monkeypatch):
    """A tuning file on disk, and the runtime directory pointed at tmp_path."""
    monkeypatch.setattr(cameras.pi, "RUNTIME_DIR", str(tmp_path))
    path = tmp_path / "ov5647_noir.json"
    path.write_text(json.dumps(tuning()))
    return str(path)


def agc_modes(path):
    with open(path) as f:
        algorithms = json.load(f)["algorithms"]
    agc = next(a["rpi.agc"] for a in algorithms if "rpi.agc" in a)
    return (agc["channels"][0] if "channels" in agc else agc)["exposure_modes"]


class TestDerivedTuning:
    def test_exposure_runs_to_the_frame_period_before_any_gain(self, base):
        derived = make_grabber(target_fps=5)._exposure_first_tuning(base)
        mode = agc_modes(derived)["long"]
        assert mode["shutter"] == [100, 100000, 200000, 200000]
        assert mode["gain"] == [1.0, 1.0, 1.0, 10.0]  # the sensor's own highest gain

    def test_the_other_tables_and_the_original_file_are_untouched(self, base):
        derived = make_grabber()._exposure_first_tuning(base)
        assert agc_modes(derived)["normal"] == agc_modes(base)["normal"]
        assert agc_modes(base)["long"]["shutter"][-1] == 120000
        assert (
            derived != base
            and os.path.basename(derived) == "ov5647_noir_exposure_first_200ms.json"
        )

    @pytest.mark.parametrize("key,channels", [("exposure", True), ("shutter", False)])
    def test_both_tuning_layouts_are_understood(
        self, tmp_path, monkeypatch, key, channels
    ):
        monkeypatch.setattr(cameras.pi, "RUNTIME_DIR", str(tmp_path))
        path = tmp_path / "imx219_noir.json"
        path.write_text(json.dumps(tuning(key, channels)))
        derived = make_grabber()._exposure_first_tuning(str(path))
        assert agc_modes(derived)["long"][key][-1] == 200000

    def test_a_file_without_exposure_modes_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cameras.pi, "RUNTIME_DIR", str(tmp_path))
        path = tmp_path / "odd.json"
        path.write_text(json.dumps({"algorithms": [{"rpi.black_level": {}}]}))
        with pytest.raises(ValueError):
            make_grabber()._exposure_first_tuning(str(path))


class TestCeiling:
    @pytest.mark.parametrize(
        "fps,ceiling",
        [(5, 200000), (2, 200000), (10, 100000), (60, 33333), (0, 200000)],
    )
    def test_one_frame_period_of_the_cap_within_bounds(self, fps, ceiling):
        assert make_grabber(target_fps=fps)._exposure_ceiling_us() == ceiling


class TestSelection:
    def select(self, base, **kwargs):
        grabber = make_grabber(**kwargs)
        fake = MagicMock()
        fake.load_tuning_file.return_value = {}
        with (
            patch.object(cameras, "Picamera2", fake),
            patch.object(cameras.pi, "get_camera_tuning_file", return_value=base),
            patch.dict(os.environ, {}, clear=False),
        ):
            path, problem = grabber._select_tuning_file()
            exported = os.environ.get("LIBCAMERA_RPI_TUNING_FILE")
        return grabber, path, problem, exported

    def test_tracking_loads_the_derived_tuning(self, base):
        grabber, path, problem, exported = self.select(base)
        assert grabber._exposure_first and problem is None
        assert path == exported and path.endswith("_exposure_first_200ms.json")

    def test_video_keeps_the_sensor_tuning_and_the_pinned_gain(self, base):
        grabber, path, _, exported = self.select(
            base, record_video=True, exposure_decoupled=False
        )
        assert not grabber._exposure_first and path == base == exported

    def test_a_tuning_that_cannot_be_derived_falls_back_to_the_pinned_gain(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(cameras.pi, "RUNTIME_DIR", str(tmp_path))
        odd = tmp_path / "odd.json"
        odd.write_text(json.dumps({"algorithms": []}))
        grabber, path, _, _ = self.select(str(odd))
        assert not grabber._exposure_first and path == str(odd)


class TestControls:
    def test_gain_is_left_to_auto_exposure_in_the_long_mode(self):
        grabber = make_grabber(target_fps=5)
        grabber._exposure_first = True
        with patch.object(cameras, "libcamera_controls", _FakeLibcameraControls):
            controls = grabber._build_camera_controls()
        assert "AnalogueGain" not in controls
        assert controls["AeExposureMode"] == _FakeExposureModeEnum.Long
        assert controls["FrameDurationLimits"] == (33333, 200000)

    def test_a_live_gain_setting_does_not_pin_the_gain(self):
        grabber = make_grabber()
        grabber._exposure_first = True
        capture = MagicMock()
        with patch.object(cameras.pi, "get_gain_setting", return_value=5.0):
            grabber._apply_live_gain(capture)
        capture.set_controls.assert_not_called()

    def test_without_the_derived_tuning_the_gain_stays_pinned(self):
        grabber = make_grabber()
        with patch.object(cameras, "libcamera_controls", _FakeLibcameraControls):
            controls = grabber._build_camera_controls()
        assert controls["AnalogueGain"] == 3.0
