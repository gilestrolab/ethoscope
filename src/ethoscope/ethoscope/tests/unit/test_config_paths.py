#!/usr/bin/env python3
"""
Unit tests for where the device keeps its settings and its runtime state.

``/etc/ethoscope`` is being retired. Settings a user can change belong in the
configuration directory (``$ETHOSCOPE_CONFIG_DIR``, else
``{ETHOSCOPE_DATA_DIR}/config``); state that only describes the current boot
belongs under ``/run``, which is cleared on reboot and already holds the light
daemon's socket and schedule.

The split matters in both directions. A cache written to ``/etc`` survives a
reboot and can go stale against the hardware it describes, and it needs root to
write, which is what made an unwritable camera cache look like a missing ribbon
cable. A setting written to ``/run`` is lost on reboot.

Reads fall back to the old location so a device that has not been migrated keeps
its gain and frame-rate settings rather than silently reverting to defaults.
Writes never do, so migration happens the first time a setting is changed.
"""

import os
from unittest.mock import patch

import pytest

from ethoscope.utils import pi


@pytest.fixture
def clean_env():
    saved = {
        k: os.environ.get(k) for k in ("ETHOSCOPE_DATA_DIR", "ETHOSCOPE_CONFIG_DIR")
    }
    for k in saved:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


class TestResolution:
    def test_config_defaults_under_the_data_directory(self, clean_env):
        assert pi.resolve_config_dir() == "/ethoscope_data/config"

    def test_the_data_directory_can_be_moved(self, clean_env):
        os.environ["ETHOSCOPE_DATA_DIR"] = "/mnt/other"
        assert pi.resolve_config_dir() == "/mnt/other/config"

    def test_an_explicit_config_directory_wins(self, clean_env):
        os.environ["ETHOSCOPE_DATA_DIR"] = "/mnt/other"
        os.environ["ETHOSCOPE_CONFIG_DIR"] = "/etc/somewhere"
        assert pi.resolve_config_dir() == "/etc/somewhere"

    def test_nothing_resolves_into_the_retired_directory(self, clean_env):
        assert not pi.config_path("gain_setting").startswith(pi.LEGACY_CONFIG_DIR)
        assert not pi.runtime_path("camera-tuning").startswith(pi.LEGACY_CONFIG_DIR)


class TestRuntimeState:
    @pytest.mark.parametrize(
        "path", [pi.PICAMERA_VERSION_FILE, pi.CAMERA_TUNING_STATUS_FILE]
    )
    def test_boot_specific_state_lives_under_run(self, path):
        """Both describe the camera attached right now, not a user setting."""
        assert path.startswith("/run/"), path


class TestLegacyFallback:
    def test_an_unmigrated_setting_is_still_read(self, clean_env, tmp_path):
        """Regression: moving the read path would drop existing gain settings."""
        legacy = tmp_path / "etc"
        legacy.mkdir()
        (legacy / "gain_setting").write_text("5.0")

        with patch.object(pi, "LEGACY_CONFIG_DIR", str(legacy)):
            with patch.object(
                pi, "resolve_config_dir", return_value=str(tmp_path / "cfg")
            ):
                assert pi.get_gain_setting() == 5.0

    def test_the_new_location_takes_precedence(self, clean_env, tmp_path):
        legacy = tmp_path / "etc"
        legacy.mkdir()
        (legacy / "gain_setting").write_text("5.0")
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / "gain_setting").write_text("2.0")

        with patch.object(pi, "LEGACY_CONFIG_DIR", str(legacy)):
            with patch.object(pi, "resolve_config_dir", return_value=str(cfg)):
                assert pi.get_gain_setting() == 2.0

    def test_writes_go_to_the_new_location_only(self, clean_env, tmp_path):
        """Changing a setting is what migrates it; writes must not touch /etc."""
        legacy = tmp_path / "etc"
        legacy.mkdir()
        cfg = tmp_path / "cfg"

        with patch.object(pi, "LEGACY_CONFIG_DIR", str(legacy)):
            with patch.object(pi, "resolve_config_dir", return_value=str(cfg)):
                pi.set_gain_setting(4.0)

        assert (cfg / "gain_setting").read_text().strip() == "4.0"
        assert not (legacy / "gain_setting").exists()

    def test_a_missing_setting_still_returns_the_default(self, clean_env, tmp_path):
        with patch.object(pi, "LEGACY_CONFIG_DIR", str(tmp_path / "none")):
            with patch.object(
                pi, "resolve_config_dir", return_value=str(tmp_path / "cfg")
            ):
                assert pi.get_gain_setting() == pi.DEFAULT_CAMERA_GAIN
                assert pi.get_maxfps_setting() == pi.DEFAULT_MAXFPS
