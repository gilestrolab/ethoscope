"""
Tests for the LED daylight controller daemon.
"""

import datetime
import json
import os
import tempfile
import threading
import time
from unittest.mock import call, patch

import pytest

from ethoscope.hardware.interfaces.light_daemon import (
    LightController,
    LightDaemonClient,
    LightDaemonUnavailable,
)


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


class TestAnchoredCycle:
    """Tests for the T-cycle (period+anchor) mode of should_light_be_on."""

    def _now(self, anchor_ts, hours_after):
        """Helper: return a datetime ``hours_after`` past the anchor timestamp."""
        return datetime.datetime.fromtimestamp(anchor_ts + hours_after * 3600)

    def test_t21_in_light_phase(self):
        """T=21h with 12L:9D — at +3h of cycle the light is on."""
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 3),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )

    def test_t21_in_dark_phase(self):
        """T=21h with 12L:9D — at +15h the light is off."""
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 15),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is False
        )

    def test_t21_wraps_into_next_cycle(self):
        """T=21h: at +22h we've wrapped 1h into a new cycle → light on."""
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 22),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )

    def test_t21_cycle_end_wrap_window(self):
        """T=21h, lights_on=18:00 lights_off=03:00 — crosses cycle wrap.
        Within the cycle phase axis (mod 21h), the window 18:00→21:00 ∪ 00:00→03:00 is 'on'.
        """
        anchor = 1_700_000_000.0
        # +19h since anchor → phase = 19h:00 → on (in 18-21 part)
        assert (
            LightController.should_light_be_on(
                "18:00",
                "03:00",
                now=self._now(anchor, 19),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )
        # +2h → phase = 2h:00 → on (in 0-3 part)
        assert (
            LightController.should_light_be_on(
                "18:00",
                "03:00",
                now=self._now(anchor, 2),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )
        # +10h → phase = 10h:00 → off
        assert (
            LightController.should_light_be_on(
                "18:00",
                "03:00",
                now=self._now(anchor, 10),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is False
        )

    def test_t24_anchored_matches_wallclock(self):
        """T=24h with anchor = midnight of a wallclock date should agree
        with wall-clock mode at the same moment."""
        # Pick an anchor at midnight local time on a known date.
        midnight = datetime.datetime(2026, 5, 1, 0, 0, 0)
        anchor_ts = midnight.timestamp()
        # 14:00 the same day, both modes
        t = datetime.datetime(2026, 5, 1, 14, 0, 0)
        anchored = LightController.should_light_be_on(
            "07:00",
            "19:00",
            now=t,
            period_minutes=1440,
            anchor=anchor_ts,
        )
        wallclock = LightController.should_light_be_on(
            "07:00",
            "19:00",
            now=t.time(),
        )
        assert anchored is True
        assert wallclock is True

    def test_anchored_requires_anchor(self):
        """Asking for a non-24h period without an anchor → False (refuse)."""
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=datetime.datetime(2026, 5, 1, 12),
                period_minutes=21 * 60,
                anchor=None,
            )
            is False
        )

    def test_anchored_equal_times_always_on(self):
        """In anchored mode, equal on==off means 24h light on (any phase)."""
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "06:00",
                "06:00",
                now=self._now(anchor, 13),
                period_minutes=21 * 60,
                anchor=anchor,
            )
            is True
        )

    def test_anchored_rejects_negative_period(self):
        anchor = 1_700_000_000.0
        assert (
            LightController.should_light_be_on(
                "00:00",
                "12:00",
                now=self._now(anchor, 1),
                period_minutes=-60,
                anchor=anchor,
            )
            is False
        )


class TestReadScheduleFull:
    """Tests for the dict-returning read_schedule_full()."""

    def test_missing_file_returns_inactive(self):
        controller = LightController(config_file="/nonexistent/path.json")
        assert controller.read_schedule_full() == {"active": False}

    def test_legacy_config_no_tcycle_fields(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "07:00",
                    "lights_off": "19:00",
                    "active": True,
                }
            )
        )
        controller = LightController(config_file=str(config_file))
        sched = controller.read_schedule_full()
        assert sched["active"] is True
        assert sched["lights_on"] == "07:00"
        assert sched["period_minutes"] == 1440
        assert sched["anchor"] is None

    def test_tcycle_config(self, tmp_path):
        config_file = tmp_path / "light_schedule.json"
        config_file.write_text(
            json.dumps(
                {
                    "lights_on": "00:00",
                    "lights_off": "12:00",
                    "active": True,
                    "period_minutes": 1260,
                    "anchor": 1715000000.0,
                }
            )
        )
        controller = LightController(config_file=str(config_file))
        sched = controller.read_schedule_full()
        assert sched["active"] is True
        assert sched["period_minutes"] == 1260
        assert sched["anchor"] == 1715000000.0


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


class TestForceOverride:
    """Tests for the force-override state machine."""

    @patch("subprocess.run")
    def test_set_force_on_drives_led_immediately(self, mock_run):
        controller = LightController(gpio_pin=17)
        controller.set_force(True)
        assert controller._force is True
        # Apply-immediately path: pinctrl was called with dh.
        mock_run.assert_called_once_with(
            ["pinctrl", "set", "17", "op", "dh"],
            check=True,
            capture_output=True,
            timeout=5,
        )

    @patch("subprocess.run")
    def test_set_force_off_drives_led_immediately(self, mock_run):
        controller = LightController(gpio_pin=17)
        controller.set_force(False)
        assert controller._force is False
        mock_run.assert_called_once_with(
            ["pinctrl", "set", "17", "op", "dl"],
            check=True,
            capture_output=True,
            timeout=5,
        )

    @patch("subprocess.run")
    def test_release_clears_force_without_pinctrl_call(self, mock_run):
        controller = LightController(gpio_pin=17)
        controller.set_force(True)
        mock_run.reset_mock()
        controller.set_force(None)
        assert controller._force is None
        # Release does not itself drive the LED; the next loop tick chooses the desired state.
        mock_run.assert_not_called()


class TestHandleCommand:
    """Tests for the wire-protocol parser."""

    def _make_controller(self):
        return LightController(gpio_pin=17, socket_path=None)

    @patch("subprocess.run")
    def test_force_on(self, _mock_run):
        controller = self._make_controller()
        assert controller._handle_command("FORCE ON") == "OK"
        assert controller._force is True

    @patch("subprocess.run")
    def test_force_off(self, _mock_run):
        controller = self._make_controller()
        assert controller._handle_command("force off") == "OK"
        assert controller._force is False

    @patch("subprocess.run")
    def test_release(self, _mock_run):
        controller = self._make_controller()
        controller._force = True
        assert controller._handle_command("release") == "OK"
        assert controller._force is None

    @patch("subprocess.run")
    def test_status_returns_json(self, _mock_run):
        controller = self._make_controller()
        controller._current_state = True
        controller._force = True
        payload = json.loads(controller._handle_command("STATUS"))
        assert payload["led"] == "on"
        assert payload["mode"] == "forced"
        assert payload["force"] == "on"

    def test_unknown_command_returns_error(self):
        controller = self._make_controller()
        response = controller._handle_command("BLINK")
        assert response.startswith("ERR")


class TestSocketRoundTrip:
    """End-to-end tests against a real listener thread on a tmp socket."""

    @pytest.fixture
    def running_controller(self, tmp_path):
        socket_path = str(tmp_path / "light_daemon.sock")
        controller = LightController(gpio_pin=17, socket_path=socket_path)
        with patch("subprocess.run"):
            controller._start_socket_listener()
            # Wait briefly for the listener thread to be ready to accept.
            time.sleep(0.05)
            try:
                yield controller, socket_path
            finally:
                controller._running = False
                controller._stop_socket_listener()

    def test_force_on_round_trip(self, running_controller):
        controller, socket_path = running_controller
        with patch("subprocess.run"):
            client = LightDaemonClient(socket_path=socket_path)
            client.force_on()
        assert controller._force is True

    def test_release_round_trip(self, running_controller):
        controller, socket_path = running_controller
        with patch("subprocess.run"):
            controller.set_force(True)
            client = LightDaemonClient(socket_path=socket_path)
            client.release()
        assert controller._force is None

    def test_status_round_trip(self, running_controller):
        _, socket_path = running_controller
        with patch("subprocess.run"):
            client = LightDaemonClient(socket_path=socket_path)
            payload = client.status()
        assert "mode" in payload
        assert payload["mode"] in {"forced", "schedule"}


class TestClientUnavailable:
    """The client must raise LightDaemonUnavailable on connection failure."""

    def test_missing_socket_raises(self, tmp_path):
        client = LightDaemonClient(socket_path=str(tmp_path / "does_not_exist.sock"))
        with pytest.raises(LightDaemonUnavailable):
            client.force_on()

    def test_status_on_missing_socket_raises(self, tmp_path):
        client = LightDaemonClient(socket_path=str(tmp_path / "does_not_exist.sock"))
        with pytest.raises(LightDaemonUnavailable):
            client.status()
