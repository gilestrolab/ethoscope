"""
Tests for the LED daylight controller daemon.
"""

import datetime
import json
import os
import tempfile
from unittest.mock import call, patch

import pytest

from ethoscope.hardware.interfaces.light_daemon import LightController


class TestShouldLightBeOn:
    """Tests for the time-based schedule logic."""

    def test_normal_schedule_during_day(self):
        """Light should be on at noon for a 07:00-19:00 schedule."""
        noon = datetime.time(12, 0)
        assert LightController.should_light_be_on("07:00", "19:00", now=noon) is True

    def test_normal_schedule_during_night(self):
        """Light should be off at midnight for a 07:00-19:00 schedule."""
        midnight = datetime.time(0, 0)
        assert (
            LightController.should_light_be_on("07:00", "19:00", now=midnight) is False
        )

    def test_normal_schedule_at_on_time(self):
        """Light should be on exactly at the on-time boundary."""
        assert (
            LightController.should_light_be_on(
                "07:00", "19:00", now=datetime.time(7, 0)
            )
            is True
        )

    def test_normal_schedule_at_off_time(self):
        """Light should be off exactly at the off-time boundary."""
        assert (
            LightController.should_light_be_on(
                "07:00", "19:00", now=datetime.time(19, 0)
            )
            is False
        )

    def test_midnight_crossing_during_night(self):
        """Light should be on at 23:00 for a 22:00-06:00 schedule."""
        assert (
            LightController.should_light_be_on(
                "22:00", "06:00", now=datetime.time(23, 0)
            )
            is True
        )

    def test_midnight_crossing_during_day(self):
        """Light should be off at noon for a 22:00-06:00 schedule."""
        assert (
            LightController.should_light_be_on(
                "22:00", "06:00", now=datetime.time(12, 0)
            )
            is False
        )

    def test_midnight_crossing_early_morning(self):
        """Light should be on at 03:00 for a 22:00-06:00 schedule."""
        assert (
            LightController.should_light_be_on(
                "22:00", "06:00", now=datetime.time(3, 0)
            )
            is True
        )

    def test_equal_times_always_on(self):
        """Equal on/off times means 24h light."""
        assert (
            LightController.should_light_be_on(
                "07:00", "07:00", now=datetime.time(12, 0)
            )
            is True
        )
        assert (
            LightController.should_light_be_on(
                "07:00", "07:00", now=datetime.time(3, 0)
            )
            is True
        )

    def test_short_photoperiod(self):
        """8:16 LD cycle (08:00-16:00)."""
        assert (
            LightController.should_light_be_on(
                "08:00", "16:00", now=datetime.time(12, 0)
            )
            is True
        )
        assert (
            LightController.should_light_be_on(
                "08:00", "16:00", now=datetime.time(17, 0)
            )
            is False
        )

    def test_long_photoperiod(self):
        """16:8 LD cycle (04:00-20:00)."""
        assert (
            LightController.should_light_be_on(
                "04:00", "20:00", now=datetime.time(19, 0)
            )
            is True
        )
        assert (
            LightController.should_light_be_on(
                "04:00", "20:00", now=datetime.time(21, 0)
            )
            is False
        )

    def test_invalid_on_time(self):
        """Invalid on time should return False."""
        assert (
            LightController.should_light_be_on(
                "invalid", "19:00", now=datetime.time(12, 0)
            )
            is False
        )

    def test_invalid_off_time(self):
        """Invalid off time should return False."""
        assert (
            LightController.should_light_be_on("07:00", "bad", now=datetime.time(12, 0))
            is False
        )

    def test_empty_strings(self):
        """Empty strings should return False."""
        assert (
            LightController.should_light_be_on("", "", now=datetime.time(12, 0))
            is False
        )


class TestParseTime:
    """Tests for time string parsing."""

    def test_valid_time(self):
        assert LightController.parse_time("07:00") == datetime.time(7, 0)
        assert LightController.parse_time("19:30") == datetime.time(19, 30)
        assert LightController.parse_time("00:00") == datetime.time(0, 0)
        assert LightController.parse_time("23:59") == datetime.time(23, 59)

    def test_invalid_time(self):
        assert LightController.parse_time("") is None
        assert LightController.parse_time("invalid") is None
        assert LightController.parse_time("25:00") is None
        assert LightController.parse_time("12:60") is None


class TestReadSchedule:
    """Tests for config file reading."""

    def test_missing_file(self):
        """Missing config file should return inactive."""
        controller = LightController(config_file="/nonexistent/path.json")
        lights_on, lights_off, active = controller.read_schedule()
        assert active is False

    def test_valid_config(self, tmp_path):
        """Valid config file should return correct schedule."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": True,
                    "updated_at": 1713100800.0,
                }
            )
        )
        controller = LightController(config_file=str(config_file))
        lights_on, lights_off, active = controller.read_schedule()
        assert lights_on == "07:00"
        assert lights_off == "19:00"
        assert active is True

    def test_inactive_config(self, tmp_path):
        """Config with active=False should return inactive."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": False,
                }
            )
        )
        controller = LightController(config_file=str(config_file))
        _, _, active = controller.read_schedule()
        assert active is False

    def test_malformed_json(self, tmp_path):
        """Malformed JSON should return inactive."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text("{bad json")
        controller = LightController(config_file=str(config_file))
        _, _, active = controller.read_schedule()
        assert active is False

    def test_missing_times(self, tmp_path):
        """Config missing time fields should return inactive."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(json.dumps({"active": True}))
        controller = LightController(config_file=str(config_file))
        _, _, active = controller.read_schedule()
        assert active is False

    def test_empty_times(self, tmp_path):
        """Config with empty time strings should return inactive."""
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "",
                    "lights_off": "",
                    "active": True,
                }
            )
        )
        controller = LightController(config_file=str(config_file))
        _, _, active = controller.read_schedule()
        assert active is False


class TestSetLed:
    """Tests for GPIO control."""

    @patch("subprocess.run")
    def test_led_on_drives_high(self, mock_run):
        """LED on should drive GPIO HIGH (dh)."""
        controller = LightController(gpio_pin=17)
        controller.set_led(True)
        mock_run.assert_called_once_with(
            ["pinctrl", "set", "17", "op", "dh"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        assert controller._current_state is True

    @patch("subprocess.run")
    def test_led_off_drives_low(self, mock_run):
        """LED off should drive GPIO LOW (dl)."""
        controller = LightController(gpio_pin=17)
        controller.set_led(False)
        mock_run.assert_called_once_with(
            ["pinctrl", "set", "17", "op", "dl"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        assert controller._current_state is False

    @patch("subprocess.run")
    def test_no_redundant_calls(self, mock_run):
        """Calling set_led with same state should not invoke pinctrl again."""
        controller = LightController(gpio_pin=17)
        controller.set_led(True)
        controller.set_led(True)  # redundant
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_state_transitions(self, mock_run):
        """Full on-off-on cycle should invoke pinctrl three times."""
        controller = LightController(gpio_pin=17)
        controller.set_led(True)
        controller.set_led(False)
        controller.set_led(True)
        assert mock_run.call_count == 3

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_pinctrl_not_found(self, mock_run):
        """Missing pinctrl should stop the controller."""
        controller = LightController(gpio_pin=17)
        controller.set_led(True)
        assert controller._running is False


class TestShutdown:
    """Tests for signal handling."""

    def test_shutdown_stops_running(self):
        """Shutdown signal should set running to False."""
        controller = LightController()
        assert controller._running is True
        controller.shutdown(signum=15)
        assert controller._running is False
