"""
Unit tests for the automatic stop shared by tracking and video recording.

Covers ``TimedStop`` (parsing and resolving what the user asked for) and the
supervisor harness on ``ControlThread`` (arming, cancelling, and firing against a
controlled clock). The harness is exercised through a minimal stand-in rather than a
real ``ControlThread``, whose constructor needs a camera, a database and a Pi.
"""

import os
import tempfile
import threading
import time

import pytest

try:
    from ethoscope.control.tracking import ControlThread
    from ethoscope.utils.scheduler import (
        TimedStop,
        TimedStopError,
        format_countdown,
        timedStop,
    )
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.control.tracking import ControlThread
    from ethoscope.utils.scheduler import (
        TimedStop,
        TimedStopError,
        format_countdown,
        timedStop,
    )


# A fixed reference so tests never depend on the wall clock: 2001-09-09 01:46:40 UTC.
T0 = 1_000_000_000.0


class TestFormatCountdown:
    def test_splits_into_days_hours_minutes(self):
        assert format_countdown(3 * 86400 + 5 * 3600 + 7 * 60) == "03:05:07"

    def test_truncates_rather_than_rounds(self):
        # 59 seconds is not a minute yet, and a "time left" readout must not claim it.
        assert format_countdown(59) == "00:00:00"

    def test_clamps_negative_to_zero(self):
        assert format_countdown(-500) == "00:00:00"


class TestTimedStopDuration:
    def test_default_is_no_automatic_stop(self):
        stop = TimedStop()
        assert stop.autostop is False
        assert stop.resolve(T0) is None
        assert stop.describe(T0) is False

    def test_duration_resolves_relative_to_start(self):
        stop = TimedStop(duration="01:02:30")
        assert stop.autostop is True
        assert stop.resolve(T0) == T0 + 86400 + 2 * 3600 + 30 * 60

    def test_describe_returns_the_run_length(self):
        assert TimedStop(duration="02:03:04").describe(T0) == "02:03:04"

    def test_legacy_timer_field_still_starts(self):
        # Configurations saved before this class was shared name the field "timer".
        assert TimedStop(timer="00:00:30").resolve(T0) == T0 + 1800

    def test_legacy_class_name_still_resolves(self):
        # The control threads resolve option classes by name from the saved JSON.
        assert timedStop is TimedStop

    @pytest.mark.parametrize(
        "bad", ["1:2", "aa:bb:cc", "00:25:00", "00:00:99", "-1:00:00", "1:2:3:4"]
    )
    def test_malformed_duration_is_refused(self, bad):
        with pytest.raises(TimedStopError):
            TimedStop(duration=bad)


class TestTimedStopAbsolute:
    def test_date_string_resolves(self):
        stop = TimedStop(stop_at="2030-01-01 09:00:00")
        assert stop.autostop is True
        assert stop.resolve(T0) == time.mktime((2030, 1, 1, 9, 0, 0, 0, 1, -1))

    def test_unix_timestamp_resolves_verbatim(self):
        # This is what the web interface sends: only the browser knows the timezone.
        assert TimedStop(stop_at=str(T0 + 500)).resolve(T0) == T0 + 500

    def test_absolute_beats_duration(self):
        stop = TimedStop(duration="10:00:00", stop_at=str(T0 + 60))
        assert stop.resolve(T0) == T0 + 60

    def test_describe_measures_from_the_start(self):
        assert TimedStop(stop_at=str(T0 + 86400 + 3600)).describe(T0) == "01:01:00"

    def test_a_stop_time_in_the_past_is_refused(self):
        # Resolving, not constructing: the run would otherwise end the moment it began.
        stop = TimedStop(stop_at="2000-01-01 09:00:00")
        with pytest.raises(TimedStopError):
            stop.resolve(T0)

    @pytest.mark.parametrize("bad", ["tomorrow", "2030-13-45 09:00:00", "3600"])
    def test_malformed_stop_time_is_refused(self, bad):
        # "3600" reads as a duration someone typed into the wrong box, not as a
        # timestamp in 1970.
        with pytest.raises(TimedStopError):
            TimedStop(stop_at=bad)


class TestOptionExposure:
    """The stop must reach the web form, and configurations must survive a round trip."""

    @pytest.mark.parametrize("cls_name", ["tracking", "recording"])
    def test_the_stop_is_offered_for_both_tracking_and_recording(self, cls_name):
        from ethoscope.control.record import ControlThreadVideoRecording

        cls = ControlThread if cls_name == "tracking" else ControlThreadVideoRecording
        offered = cls.user_options()["time_control"]

        assert [o["name"] for o in offered] == ["TimedStop"]
        # Both modals render every one of these types today, so neither form breaks.
        assert {a["type"] for a in offered[0]["arguments"]} == {"str"}

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"name": "TimedStop", "arguments": {"duration": "01:00:00"}}, 86400),
            # Saved by earlier versions, which named both the class and the field
            # differently. These configurations must still start.
            ({"name": "timedStop", "arguments": {"timer": "00:06:00"}}, 21600),
        ],
    )
    def test_a_saved_configuration_still_resolves(self, payload, expected):
        Class, kwargs = ControlThread._parse_one_user_option(
            ControlThread, "time_control", {"time_control": payload}
        )
        assert Class is TimedStop
        assert Class(**kwargs).resolve(0) == expected


class FakeControlThread(ControlThread):
    """
    The autostop harness with none of the tracking.

    Inherits the methods under test and replaces everything they touch, so the
    supervisor can be driven without a camera, a database or a Pi.
    """

    def __init__(self, **time_control_kwargs):
        self._info = {"autostop": False, "autostop_at": None}
        # ControlThread.__del__ stops the thread and removes this directory; without
        # it, garbage collecting the fake raises an ignored AttributeError.
        self._tmp_dir = tempfile.mkdtemp(prefix="test_timed_stop_")
        self._init_autostop_state()
        self.stop_calls = 0
        self.stopped = threading.Event()
        # Per-instance, so a test cannot leak its option choice into the class-level
        # _option_dict every ControlThread shares.
        self._option_dict = dict(self._option_dict)
        self._option_dict["time_control"] = {
            "class": TimedStop,
            "kwargs": time_control_kwargs,
        }

    def stop(self, error=None):
        self.stop_calls += 1
        self._cancel_autostop()
        self.stopped.set()


@pytest.fixture
def fast_poll(monkeypatch):
    """Shrink the poll interval so the supervisor can be observed in a test."""
    monkeypatch.setattr(ControlThread, "_AUTOSTOP_POLL_SECONDS", 0.01)


class TestAutostopHarness:
    def test_arming_without_a_stop_time_starts_no_supervisor(self):
        ct = FakeControlThread()
        ct._arm_autostop(T0)

        assert ct._autostop_thread is None
        assert ct._info["autostop_at"] is None
        assert ct._info["autostop"] is False

    def test_arming_reports_the_scheduled_stop(self):
        ct = FakeControlThread(duration="01:00:00")
        ct._arm_autostop(time.time())

        assert ct._info["autostop_at"] == pytest.approx(time.time() + 86400, abs=5)
        assert ct._info["autostop"] == "01:00:00"
        assert ct._autostop_thread.daemon is True

    def test_a_malformed_stop_time_raises_at_arm(self):
        ct = FakeControlThread(duration="not a duration")
        with pytest.raises(TimedStopError):
            ct._arm_autostop(T0)

    def test_the_supervisor_fires_when_the_time_arrives(self, fast_poll):
        ct = FakeControlThread()
        ct._set_autostop(time.time() + 0.05)

        assert ct.stopped.wait(5), "the autostop never fired"
        assert ct.stop_calls == 1
        assert ct._autostop_fired is True

    def test_a_cancelled_supervisor_never_fires(self, fast_poll):
        ct = FakeControlThread()
        ct._set_autostop(time.time() + 0.05)
        supervisor = ct._autostop_thread
        ct._cancel_autostop()

        supervisor.join(5)
        assert not supervisor.is_alive(), "the supervisor outlived its cancellation"
        assert ct.stop_calls == 0
        assert ct._info["autostop_at"] is None

    def test_rearming_supersedes_the_previous_supervisor(self, fast_poll):
        ct = FakeControlThread()
        ct._set_autostop(time.time() + 0.05)
        first = ct._autostop_thread

        ct._set_autostop(time.time() + 3600)
        first.join(5)

        assert not first.is_alive(), "the superseded supervisor is still running"
        assert ct.stop_calls == 0, "the superseded supervisor stopped the experiment"
        assert ct._autostop_thread is not first

    def test_a_target_already_past_fires_immediately(self, fast_poll):
        # Reachable only by re-arming a running experiment, but it must stop rather
        # than wait out a negative interval.
        ct = FakeControlThread()
        ct._set_autostop(time.time() - 10)

        assert ct.stopped.wait(5), "a past stop time did not stop the experiment"
        assert ct.stop_calls == 1

    def test_it_stops_once_even_if_the_clock_keeps_running(self, fast_poll):
        ct = FakeControlThread()
        ct._set_autostop(time.time() + 0.05)

        assert ct.stopped.wait(5)
        time.sleep(0.2)
        assert ct.stop_calls == 1

    def test_cancelling_when_nothing_is_armed_is_harmless(self):
        ct = FakeControlThread()
        ct._cancel_autostop()
        ct._cancel_autostop()

        assert ct._autostop_at is None
