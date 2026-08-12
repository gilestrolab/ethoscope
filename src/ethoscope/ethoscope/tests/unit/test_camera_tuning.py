#!/usr/bin/env python3
"""
Unit tests for NoIR camera tuning resolution.

An ethoscope cannot work without an IR pass-through (NoIR) camera, so NoIR
tuning is unconditional and is not a user setting. What varies is the sensor and
the Pi generation:

* the tuning file used to be hardcoded to ``imx219_noir.json``, so any other
  sensor (ov5647 / imx477 / imx708) failed to load it and silently fell back to
  libcamera's default *colour* tuning, changing auto-exposure behaviour with no
  trace in the data (issue #222);
* the file lives under ``.../vc4`` on Pi 0-4 but ``.../pisp`` on the Pi 5, and
  picamera2's own ``load_tuning_file()`` search path only knows about ``vc4``.

The resolver must therefore pick the file by *detected sensor*, find it in
either directory, and report None rather than guessing when it cannot.
"""

from unittest.mock import patch

import pytest

from ethoscope.utils import pi


@pytest.fixture
def tuning_dirs(tmp_path):
    """Fake libcamera tuning directories: the Pi 5 pipeline and the legacy one."""
    pisp = tmp_path / "pisp"
    vc4 = tmp_path / "vc4"
    pisp.mkdir()
    vc4.mkdir()
    with patch.object(
        pi,
        "_LIBCAMERA_PIPELINE_DIRS",
        {"pisp": (str(pisp),), "vc4": (str(vc4),)},
    ):
        yield pisp, vc4


def test_resolves_tuning_for_the_detected_sensor(tuning_dirs):
    """The file is chosen from the detected sensor, not hardcoded to imx219."""
    _, vc4 = tuning_dirs
    (vc4 / "ov5647_noir.json").write_text("{}")

    with patch.object(pi, "_get_camera_sensor_info", return_value="ov5647"):
        assert pi.get_camera_tuning_file() == str(vc4 / "ov5647_noir.json")


def test_finds_tuning_in_the_pi5_directory(tuning_dirs):
    """Pi 5 keeps tuning under pisp/, which picamera2 alone would not search."""
    pisp, _ = tuning_dirs
    (pisp / "imx708_noir.json").write_text("{}")

    with patch.object(pi, "_get_camera_sensor_info", return_value="imx708"):
        assert pi.get_camera_tuning_file(model_number=5) == str(
            pisp / "imx708_noir.json"
        )


def test_pipeline_is_chosen_by_pi_generation_not_by_what_exists(tuning_dirs):
    """Both directories ship on a Pi 3, so "first match" picks the wrong one.

    Found on real hardware: a Pi 3 has /usr/share/libcamera/ipa/rpi/pisp *and*
    .../vc4, each holding imx219_noir.json. Searching pisp first resolved the
    Pi 5 ISP's tuning on a vc4 device.
    """
    pisp, vc4 = tuning_dirs
    (pisp / "imx219_noir.json").write_text("{}")
    (vc4 / "imx219_noir.json").write_text("{}")

    with patch.object(pi, "_get_camera_sensor_info", return_value="imx219"):
        assert pi.get_camera_tuning_file(model_number=3) == str(
            vc4 / "imx219_noir.json"
        )
        assert pi.get_camera_tuning_file(model_number=4) == str(
            vc4 / "imx219_noir.json"
        )
        assert pi.get_camera_tuning_file(model_number=5) == str(
            pisp / "imx219_noir.json"
        )


def test_unknown_pi_generation_prefers_the_legacy_pipeline(tuning_dirs):
    """vc4 is right for every currently deployed device, so it is the safe default."""
    pisp, vc4 = tuning_dirs
    (pisp / "imx219_noir.json").write_text("{}")
    (vc4 / "imx219_noir.json").write_text("{}")

    with patch.object(pi, "_get_camera_sensor_info", return_value="imx219"):
        assert pi.get_camera_tuning_file(model_number=0) == str(
            vc4 / "imx219_noir.json"
        )


def test_falls_back_to_the_other_pipeline_when_needed(tuning_dirs):
    """An unusual layout still resolves rather than dropping to default tuning."""
    pisp, _ = tuning_dirs
    # Only the pisp copy is installed, but this is a Pi 3.
    (pisp / "imx219_noir.json").write_text("{}")

    with patch.object(pi, "_get_camera_sensor_info", return_value="imx219"):
        assert pi.get_camera_tuning_file(model_number=3) == str(
            pisp / "imx219_noir.json"
        )


def test_explicit_sensor_overrides_detection(tuning_dirs):
    """A caller may name the sensor instead of relying on detection."""
    _, vc4 = tuning_dirs
    (vc4 / "imx477_noir.json").write_text("{}")

    assert pi.get_camera_tuning_file(sensor="imx477") == str(vc4 / "imx477_noir.json")


def test_returns_none_when_sensor_undetectable(tuning_dirs):
    """No sensor means no guess: the caller must report a degraded state."""
    with patch.object(pi, "_get_camera_sensor_info", return_value=None):
        assert pi.get_camera_tuning_file() is None


def test_returns_none_when_no_tuning_file_installed(tuning_dirs):
    """A detected sensor with no matching file must not fall back to another."""
    _, vc4 = tuning_dirs
    # A *different* sensor's file is present; it must not be used.
    (vc4 / "imx219_noir.json").write_text("{}")

    with patch.object(pi, "_get_camera_sensor_info", return_value="ov5647"):
        assert pi.get_camera_tuning_file() is None


def test_tuning_status_round_trip(tmp_path):
    """The grabber records what it loaded so the parent process can read it."""
    status = tmp_path / "camera-tuning"

    pi.set_camera_tuning_status(
        "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json", path=str(status)
    )

    assert pi.get_camera_tuning_status(path=str(status)) == (
        "/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json"
    )


def test_tuning_status_records_the_fallback(tmp_path):
    """Falling back to default tuning is recorded, never silent."""
    status = tmp_path / "camera-tuning"

    pi.set_camera_tuning_status(None, path=str(status))

    assert pi.get_camera_tuning_status(path=str(status)) == "DEFAULT"


def test_tuning_status_is_none_before_first_run(tmp_path):
    """Absent status file means tracking has not run yet, not a failure."""
    assert pi.get_camera_tuning_status(path=str(tmp_path / "missing")) is None


def test_noir_setting_is_no_longer_a_user_setting():
    """The old on/off flag is gone: NoIR tuning is unconditional.

    It defaulted to False when the file was absent, so devices were running
    libcamera's colour tuning on NoIR hardware unless someone had explicitly
    turned it on.
    """
    assert not hasattr(pi, "get_noir_setting")
    assert not hasattr(pi, "set_noir_setting")
