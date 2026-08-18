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

    def test_the_fields_add_up(self):
        stop = TimedStop(days=5, hours=6, minutes=30)
        assert stop.autostop is True
        assert stop.resolve(T0) == T0 + 5 * 86400 + 6 * 3600 + 30 * 60

    def test_the_form_sends_the_parts_as_one_value(self):
        # The duration widget binds one object with three named parts.
        stop = TimedStop(run_for={"days": 5, "hours": 6, "minutes": 30})
        assert stop.resolve(T0) == T0 + 5 * 86400 + 6 * 3600 + 30 * 60

    def test_a_partial_run_for_falls_back_to_the_flat_arguments(self):
        stop = TimedStop(run_for={"hours": 2}, days=1)
        assert stop.resolve(T0) == T0 + 86400 + 2 * 3600

    def test_minutes_alone_work(self):
        # Short video recordings are a real case; this is how a two-minute one is said.
        assert TimedStop(minutes=2).resolve(T0) == T0 + 120

    def test_out_of_range_fields_are_summed_not_refused(self):
        # Three labelled boxes cannot be misread the way a packed string can, so "36
        # hours" means 36 hours rather than being an error.
        assert TimedStop(hours=36).resolve(T0) == T0 + 36 * 3600

    def test_numbers_arriving_as_strings_are_read(self):
        assert (
            TimedStop(days="2", hours="3", minutes="0").resolve(T0)
            == T0 + 2 * 86400 + 3 * 3600
        )

    def test_describe_returns_the_run_length(self):
        assert TimedStop(days=2, hours=3, minutes=4).describe(T0) == "02:03:04"

    @pytest.mark.parametrize(
        "bad", [{"days": "x"}, {"hours": -1}, {"minutes": "later"}]
    )
    def test_malformed_fields_are_refused(self, bad):
        with pytest.raises(TimedStopError):
            TimedStop(**bad)


class TestTimedStopLegacyDuration:
    """Configurations saved before the duration became three numeric fields."""

    def test_legacy_duration_string_still_starts(self):
        assert (
            TimedStop(duration="01:02:30").resolve(T0)
            == T0 + 86400 + 2 * 3600 + 30 * 60
        )

    def test_legacy_timer_field_still_starts(self):
        # Older still: the field was called "timer" before it was called "duration".
        assert TimedStop(timer="00:00:30").resolve(T0) == T0 + 1800

    def test_legacy_class_name_still_resolves(self):
        # The control threads resolve option classes by name from the saved JSON.
        assert timedStop is TimedStop

    @pytest.mark.parametrize(
        "bad", ["1:2", "aa:bb:cc", "00:25:00", "00:00:99", "-1:00:00", "1:2:3:4"]
    )
    def test_the_packed_string_keeps_its_stricter_parse(self, bad):
        # Out of range is genuinely ambiguous in DD:HH:MM, unlike in labelled fields.
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
        stop = TimedStop(days=10, stop_at=str(T0 + 60))
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
        assert [a["name"] for a in offered[0]["arguments"]] == ["run_for", "stop_at"]
        # Both modals render both of these, through the shared partial.
        assert [a["type"] for a in offered[0]["arguments"]] == ["duration", "datetime"]

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"name": "TimedStop", "arguments": {"run_for": {"days": 1}}}, 86400),
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
        ct = FakeControlThread(days=1)
        ct._arm_autostop(time.time())

        assert ct._info["autostop_at"] == pytest.approx(time.time() + 86400, abs=5)
        assert ct._info["autostop"] == "01:00:00"
        assert ct._autostop_thread.daemon is True

    def test_a_malformed_stop_time_raises_at_arm(self):
        ct = FakeControlThread(days="not a number")
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


class TestSetAutostop:
    """Changing the stop of an experiment that is already under way."""

    def test_a_duration_is_counted_from_now_not_from_the_start(self, fast_poll):
        ct = FakeControlThread(days=1)
        ct._arm_autostop(time.time() - 3600)  # started an hour ago

        result = ct.set_autostop({"days": 2})

        # Two days from now, not two days from when the experiment began.
        assert result["autostop_at"] == pytest.approx(time.time() + 2 * 86400, abs=5)
        assert result["autostop"] == "02:00:00"

    def test_an_absolute_stop_time_is_honoured(self, fast_poll):
        ct = FakeControlThread()
        target = time.time() + 7200

        result = ct.set_autostop({"stop_at": str(target)})

        assert result["autostop_at"] == target
        assert ct._info["autostop_at"] == target

    def test_empty_data_cancels_the_stop(self, fast_poll):
        ct = FakeControlThread(days=1)
        ct._arm_autostop(time.time())
        assert ct._autostop_thread is not None

        result = ct.set_autostop({})

        assert result["autostop_at"] is None
        assert result["autostop"] is False
        assert ct._autostop_thread is None

    def test_it_does_not_stop_the_experiment(self, fast_poll):
        ct = FakeControlThread()
        ct.set_autostop({"hours": 1})

        assert ct.stop_calls == 0
        assert not ct.stopped.is_set()

    @pytest.mark.parametrize(
        "bad",
        [
            {"days": "not a number"},
            {"stop_at": "yesterday"},
            {"stop_at": "2000-01-01 00:00:00"},
        ],
    )
    def test_a_bad_request_leaves_the_existing_schedule_alone(self, bad, fast_poll):
        # The experiment is running. A typo in a reschedule must not silently drop the
        # stop the user already has, and must not stop the run either.
        ct = FakeControlThread(days=1)
        ct._arm_autostop(time.time())
        original = ct._info["autostop_at"]
        supervisor = ct._autostop_thread

        with pytest.raises(TimedStopError):
            ct.set_autostop(bad)

        assert ct._info["autostop_at"] == original
        assert ct._autostop_thread is supervisor
        assert supervisor.is_alive()
        assert ct.stop_calls == 0

    def test_the_rescheduled_stop_actually_fires(self, fast_poll):
        ct = FakeControlThread(days=9)
        ct._arm_autostop(time.time())

        ct.set_autostop({"stop_at": str(time.time() + 0.05)})

        assert ct.stopped.wait(5), "the rescheduled stop never fired"
        assert ct.stop_calls == 1


class FakeControl:
    """The parts of a control thread the listener's dispatch touches."""

    def __init__(self, status="running", raises=None):
        self.info = {"status": status}
        self.calls = []
        self._raises = raises

    def set_autostop(self, data=None):
        self.calls.append(data)
        if self._raises is not None:
            raise self._raises
        return {"autostop": "01:00:00", "autostop_at": 1234.0}


@pytest.fixture
def listener():
    """A commandingThread with no socket bound, so only its dispatch is exercised."""
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../scripts"))
    from device_listener import commandingThread

    def _build(control):
        thread = commandingThread.__new__(commandingThread)
        thread.control = control
        return thread

    return _build


class TestSetAutostopDispatch:
    @pytest.mark.parametrize("status", ["running", "recording", "streaming"])
    def test_it_reaches_the_control_thread_while_active(self, listener, status):
        control = FakeControl(status=status)
        thread = listener(control)

        result = thread.action("set_autostop", {"days": 1})

        assert control.calls == [{"days": 1}]
        assert result["autostop_at"] == 1234.0

    @pytest.mark.parametrize("status", ["stopped", "initialising"])
    def test_it_is_refused_when_nothing_is_running(self, listener, status):
        control = FakeControl(status=status)
        thread = listener(control)

        result = thread.action("set_autostop", {"days": 1})

        assert isinstance(result, str) and result.startswith("ERROR:")
        assert control.calls == [], "the request reached a device with no experiment"

    def test_an_unreadable_stop_time_is_reported_not_raised(self, listener):
        # handle_client would otherwise turn this into a traceback, and the user would
        # be told nothing about the field they got wrong.
        control = FakeControl(raises=TimedStopError("Use YYYY-MM-DD HH:MM:SS"))
        thread = listener(control)

        result = thread.action("set_autostop", {"stop_at": "tomorrow"})

        assert result == "ERROR: Use YYYY-MM-DD HH:MM:SS"

    def test_no_body_means_cancel(self, listener):
        control = FakeControl()
        thread = listener(control)

        thread.action("set_autostop", None)

        # Not rejected by the "this action requires JSON data" guard, which applies
        # only to start and start_record.
        assert control.calls == [None]
