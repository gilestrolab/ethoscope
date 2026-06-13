"""Parity tests for the schedule algorithm.

Many of these mirror the device-side test suite in
``src/ethoscope/ethoscope/tests/unittests/test_light_daemon.py``: when both
suites agree, the firmware can be ported verbatim against this same table.
"""

from __future__ import annotations

import datetime

import pytest

from ethoscope_node.incubators import schedule


class TestParseHHMM:
    def test_valid(self):
        assert schedule._parse_hhmm("09:30") == datetime.time(9, 30)
        assert schedule._parse_hhmm("00:00") == datetime.time(0, 0)
        assert schedule._parse_hhmm("23:59") == datetime.time(23, 59)

    @pytest.mark.parametrize("bad", ["", "9", "9:", "9:99", "not_a_time", None])
    def test_invalid_returns_none(self, bad):
        assert schedule._parse_hhmm(bad) is None


class TestIsLightOnWallClock:
    """``period_minutes=None|1440`` and ``anchor=None`` selects wall-clock mode."""

    def test_within_window(self):
        assert schedule.is_light_on("09:00", "21:00", now=datetime.time(12, 0)) is True

    def test_before_window(self):
        assert schedule.is_light_on("09:00", "21:00", now=datetime.time(7, 0)) is False

    def test_after_window(self):
        assert schedule.is_light_on("09:00", "21:00", now=datetime.time(22, 0)) is False

    def test_at_lights_on_boundary(self):
        assert schedule.is_light_on("09:00", "21:00", now=datetime.time(9, 0)) is True

    def test_at_lights_off_boundary_is_off(self):
        # The off-boundary is exclusive — same as the device-side daemon.
        assert schedule.is_light_on("09:00", "21:00", now=datetime.time(21, 0)) is False

    def test_overnight_window_in_dark(self):
        # 22:00 -> 06:00: 03:00 should be ON (still inside the wrap).
        assert schedule.is_light_on("22:00", "06:00", now=datetime.time(3, 0)) is True

    def test_overnight_window_in_light(self):
        # 22:00 -> 06:00: 12:00 is well outside.
        assert schedule.is_light_on("22:00", "06:00", now=datetime.time(12, 0)) is False

    def test_equal_on_off_means_always_on(self):
        assert schedule.is_light_on("12:00", "12:00", now=datetime.time(0, 0)) is True
        assert schedule.is_light_on("12:00", "12:00", now=datetime.time(23, 59)) is True

    def test_explicit_24h_period_is_wall_clock(self):
        # period=1440 with no anchor should be exactly wall-clock mode.
        assert (
            schedule.is_light_on(
                "09:00",
                "21:00",
                now=datetime.time(12, 0),
                period_minutes=1440,
                anchor=None,
            )
            is True
        )

    def test_invalid_strings_return_false(self):
        assert schedule.is_light_on("oops", "21:00") is False
        assert schedule.is_light_on("09:00", "") is False


class TestIsLightOnAnchored:
    """T-cycle / anchored mode is selected by anchor or non-1440 period."""

    ANCHOR = 1_700_000_000.0  # arbitrary fixed unix ts

    def test_t21_inside_window(self):
        # 21h cycle, lights_on=00:00 lights_off=12:00 means first 12h of each cycle is light.
        now = self.ANCHOR + 3 * 3600  # 3h after anchor, in the 21h cycle
        assert (
            schedule.is_light_on(
                "00:00", "12:00", now=now, period_minutes=21 * 60, anchor=self.ANCHOR
            )
            is True
        )

    def test_t21_outside_window(self):
        # Same schedule, 15h after anchor — 15 % 21 == 15, outside [0, 12).
        now = self.ANCHOR + 15 * 3600
        assert (
            schedule.is_light_on(
                "00:00", "12:00", now=now, period_minutes=21 * 60, anchor=self.ANCHOR
            )
            is False
        )

    def test_t21_wraps_around_period(self):
        # 25h after anchor: phase = 25 % 21 = 4h, inside the [0, 12) window.
        now = self.ANCHOR + 25 * 3600
        assert (
            schedule.is_light_on(
                "00:00", "12:00", now=now, period_minutes=21 * 60, anchor=self.ANCHOR
            )
            is True
        )

    def test_t12_overnight_phase_wrap(self):
        # 12h period, lights_on=10:00 lights_off=02:00: covers [10h-12h] and [0-2h].
        # 1h after anchor → phase 1h → inside the wrap-around half.
        now = self.ANCHOR + 1 * 3600
        assert (
            schedule.is_light_on(
                "10:00", "02:00", now=now, period_minutes=12 * 60, anchor=self.ANCHOR
            )
            is True
        )
        # 5h after anchor → phase 5h → outside.
        now2 = self.ANCHOR + 5 * 3600
        assert (
            schedule.is_light_on(
                "10:00", "02:00", now=now2, period_minutes=12 * 60, anchor=self.ANCHOR
            )
            is False
        )

    def test_missing_anchor_with_non24_period_is_off(self):
        # We refuse to guess a phase without an anchor.
        assert (
            schedule.is_light_on(
                "00:00", "12:00", now=self.ANCHOR, period_minutes=21 * 60, anchor=None
            )
            is False
        )

    def test_anchor_with_24h_period_phase_locks(self):
        # period=1440 + anchor set → still anchored mode (the anchor is meaningful).
        # Anchor at unix 0; 9h into the day should be ON for 09:00-21:00.
        now = 9 * 3600
        assert (
            schedule.is_light_on(
                "09:00",
                "21:00",
                now=now,
                period_minutes=1440,
                anchor=0.0,
            )
            is True
        )

    def test_accepts_datetime_as_now(self):
        now = datetime.datetime.fromtimestamp(self.ANCHOR + 3 * 3600)
        assert (
            schedule.is_light_on(
                "00:00", "12:00", now=now, period_minutes=21 * 60, anchor=self.ANCHOR
            )
            is True
        )


class TestBuildFirmwarePayload:
    def test_happy_path(self):
        record = {
            "name": "Inc1",
            "lights_on": "09:00",
            "lights_off": "21:00",
            "light_period_minutes": 1440,
            "light_cycle_anchor": None,
            "fade_in_seconds": 5,
            "fade_out_seconds": 10,
            "max_light": 80,
        }
        payload = schedule.build_firmware_payload(record)
        assert payload == {
            "lights_on": "09:00",
            "lights_off": "21:00",
            "light_period_minutes": 1440,
            "light_cycle_anchor": 0,
            "fade_in_ms": 5000,
            "fade_out_ms": 10000,
            "max_light": 80,
        }

    def test_anchor_float_is_truncated_to_int_seconds(self):
        record = {"light_cycle_anchor": 1_700_000_123.456}
        payload = schedule.build_firmware_payload(record)
        assert payload["light_cycle_anchor"] == 1_700_000_123

    def test_defaults_when_fields_missing(self):
        payload = schedule.build_firmware_payload({"name": "Inc1"})
        assert payload["lights_on"] == "00:00"
        assert payload["lights_off"] == "00:00"
        assert payload["light_period_minutes"] == 1440
        assert payload["light_cycle_anchor"] == 0
        assert payload["fade_in_ms"] == 1000
        assert payload["fade_out_ms"] == 1000
        assert payload["max_light"] == 100

    def test_clamps_max_light_to_100(self):
        payload = schedule.build_firmware_payload({"max_light": 9999})
        assert payload["max_light"] == 100

    def test_negative_fade_falls_to_zero(self):
        payload = schedule.build_firmware_payload({"fade_in_seconds": -5})
        assert payload["fade_in_ms"] == 0


class TestScheduleDrifted:
    def _record(self):
        return {
            "lights_on": "09:00",
            "lights_off": "21:00",
            "light_period_minutes": 1440,
            "light_cycle_anchor": None,
            "fade_in_seconds": 1,
            "fade_out_seconds": 1,
            "max_light": 100,
        }

    def test_no_drift_when_matching(self):
        rec = self._record()
        telemetry = schedule.build_firmware_payload(rec)
        assert schedule.schedule_drifted(rec, telemetry) is False

    def test_drift_when_telemetry_missing_field(self):
        rec = self._record()
        telemetry = schedule.build_firmware_payload(rec)
        del telemetry["max_light"]
        assert schedule.schedule_drifted(rec, telemetry) is True

    def test_drift_when_value_differs(self):
        rec = self._record()
        telemetry = schedule.build_firmware_payload(rec)
        telemetry["lights_on"] = "10:00"
        assert schedule.schedule_drifted(rec, telemetry) is True
