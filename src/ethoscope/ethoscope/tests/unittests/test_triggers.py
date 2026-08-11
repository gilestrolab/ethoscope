"""
Unit tests for stimulators/triggers.py.

Tests all trigger conditions: InactivityTrigger, MidlineCrossingTrigger,
PeriodicTrigger, TimeRestrictedInactivityTrigger, and TRIGGER_REGISTRY.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope.stimulators.triggers import (
    TRIGGER_REGISTRY,
    ActivityTrigger,
    BaseTrigger,
    InactivityTrigger,
    MidlineCrossingTrigger,
    PeriodicTrigger,
    ScheduledTrigger,
    TimeRestrictedInactivityTrigger,
)


def _make_mock_tracker(roi_id=1, last_time_point=200000, positions=None, times=None):
    """Create a mock tracker for trigger tests."""
    tracker = Mock()
    tracker._roi = Mock()
    tracker._roi.idx = roi_id
    tracker._roi.longest_axis = 100.0
    tracker.last_time_point = last_time_point
    tracker.positions = positions or [
        [{"xy_dist_log10x1000": -3000, "x": 50}],
        [{"xy_dist_log10x1000": -3000, "x": 50}],
    ]
    tracker.times = times or [last_time_point - 1000, last_time_point]
    return tracker


# ===========================================================================
# BaseTrigger
# ===========================================================================


class TestBaseTrigger(unittest.TestCase):
    """Test BaseTrigger abstract class."""

    def test_init(self):
        trigger = BaseTrigger()
        self.assertIsNone(trigger._tracker)

    def test_bind_tracker(self):
        trigger = BaseTrigger()
        tracker = Mock()
        trigger.bind_tracker(tracker)
        self.assertIs(trigger._tracker, tracker)

    def test_check_raises(self):
        trigger = BaseTrigger()
        with self.assertRaises(NotImplementedError):
            trigger.check()


# ===========================================================================
# InactivityTrigger
# ===========================================================================


class TestInactivityTrigger(unittest.TestCase):
    """Test InactivityTrigger."""

    def test_init_valid(self):
        trigger = InactivityTrigger(
            velocity_correction_coef=3.0e-3,
            min_inactive_time=120,
            stimulus_probability=0.5,
        )
        self.assertEqual(trigger._bout_threshold_ms, 120000)
        self.assertEqual(trigger._p, 0.5)

    def test_init_invalid_probability(self):
        with self.assertRaises(ValueError):
            InactivityTrigger(stimulus_probability=1.5)
        with self.assertRaises(ValueError):
            InactivityTrigger(stimulus_probability=-0.1)

    def test_has_moved_insufficient_positions(self):
        trigger = InactivityTrigger()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"xy_dist_log10x1000": 0}]]
        trigger.bind_tracker(tracker)
        self.assertFalse(trigger._has_moved())

    def test_has_moved_stationary(self):
        """Stationary animal: low velocity."""
        trigger = InactivityTrigger()
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        self.assertFalse(trigger._has_moved())

    def test_has_moved_moving(self):
        """Moving animal: high velocity."""
        trigger = InactivityTrigger()
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": 3000}],
                [{"xy_dist_log10x1000": 3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        self.assertTrue(trigger._has_moved())

    def test_has_moved_time_mismatch(self):
        """Returns False when last_time_point != last position time."""
        trigger = InactivityTrigger()
        tracker = _make_mock_tracker(last_time_point=300000)
        tracker.times = [199000, 200000]
        trigger.bind_tracker(tracker)
        self.assertFalse(trigger._has_moved())

    def test_check_no_trigger(self):
        """No trigger when animal is moving."""
        trigger = InactivityTrigger(min_inactive_time=0)
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": 3000}],
                [{"xy_dist_log10x1000": 3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 0)

    def test_check_real_trigger(self):
        """Code 1 when inactive beyond threshold and probability passes."""
        trigger = InactivityTrigger(min_inactive_time=0, stimulus_probability=1.0)
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        trigger._t0 = 0
        code, meta = trigger.check()
        self.assertEqual(code, 1)

    def test_check_ghost_trigger(self):
        """Code 2 when inactive beyond threshold but probability fails."""
        trigger = InactivityTrigger(min_inactive_time=0, stimulus_probability=0.0)
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        trigger._t0 = 0
        code, meta = trigger.check()
        self.assertEqual(code, 2)

    def test_check_resets_t0_on_movement(self):
        """t0 resets when animal moves."""
        trigger = InactivityTrigger(min_inactive_time=120)
        tracker = _make_mock_tracker(
            last_time_point=200000,
            positions=[
                [{"xy_dist_log10x1000": 3000}],
                [{"xy_dist_log10x1000": 3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        trigger._t0 = 100000
        trigger.check()
        self.assertEqual(trigger._t0, 200000)


# ===========================================================================
# ActivityTrigger
# ===========================================================================


def _moving_tracker(last_time_point=200000, times=None):
    """Tracker whose animal registers as moving on the latest frame."""
    return _make_mock_tracker(
        last_time_point=last_time_point,
        positions=[
            [{"xy_dist_log10x1000": 3000}],
            [{"xy_dist_log10x1000": 3000}],
        ],
        times=times or [last_time_point - 1000, last_time_point],
    )


def _still_tracker(last_time_point=200000, times=None):
    """Tracker whose animal registers as stationary on the latest frame."""
    return _make_mock_tracker(
        last_time_point=last_time_point,
        positions=[
            [{"xy_dist_log10x1000": -3000}],
            [{"xy_dist_log10x1000": -3000}],
        ],
        times=times or [last_time_point - 1000, last_time_point],
    )


def _drive(trigger, duration_s, fps=5, moving_at=lambda t: True, t0=0):
    """
    Feed `trigger` frames for duration_s of wall clock at `fps`.

    moving_at(t_ms) decides whether the animal registers as moving on that
    frame. Returns the list of interaction codes, one per frame.
    """
    step = max(1, int(round(1000 / fps)))
    codes = []
    for t in range(t0, t0 + int(duration_s * 1000) + 1, step):
        tracker = _moving_tracker(t) if moving_at(t) else _still_tracker(t)
        trigger.bind_tracker(tracker)
        codes.append(trigger.check()[0])
    return codes


class TestActivityTrigger(unittest.TestCase):
    """
    ActivityTrigger scores a window of binned activity, rather than demanding
    an unbroken run of moving frames.
    """

    def test_init_valid(self):
        trigger = ActivityTrigger(
            velocity_correction_coef=3.0e-3,
            min_active_time=120,
            activity_threshold=0.5,
            stimulus_probability=0.5,
        )
        self.assertEqual(trigger._window_ms, 120000)
        self.assertEqual(trigger._threshold, 0.5)
        self.assertEqual(trigger._p, 0.5)

    def test_defaults(self):
        """Defaults mirror the inactivity protocol: a 120 s window, 85% active."""
        trigger = ActivityTrigger()
        self.assertEqual(trigger._window_ms, 120000)
        self.assertEqual(trigger._threshold, 0.85)
        self.assertEqual(trigger._n_bins, 12)

    def test_bins_never_shrink_below_five_seconds(self):
        """A bin must stay wide enough to saturate, or we are counting frames."""
        for window in (10, 30, 60, 120, 300, 3600):
            trigger = ActivityTrigger(min_active_time=window)
            self.assertGreaterEqual(trigger._bin_ms, 5000)
            self.assertGreaterEqual(trigger._n_bins, 2)
            self.assertEqual(trigger._window_ms, window * 1000)

    def test_init_invalid_probability(self):
        with self.assertRaises(ValueError):
            ActivityTrigger(stimulus_probability=1.5)
        with self.assertRaises(ValueError):
            ActivityTrigger(stimulus_probability=-0.1)

    def test_init_invalid_threshold(self):
        with self.assertRaises(ValueError):
            ActivityTrigger(activity_threshold=0.0)
        with self.assertRaises(ValueError):
            ActivityTrigger(activity_threshold=1.5)

    def test_init_invalid_window(self):
        with self.assertRaises(ValueError):
            ActivityTrigger(min_active_time=0)

    def test_no_trigger_while_still(self):
        """A stationary animal never fires, however long it stays so."""
        trigger = ActivityTrigger(min_active_time=60, stimulus_probability=1.0)
        codes = _drive(trigger, duration_s=600, moving_at=lambda t: False)
        self.assertNotIn(1, codes)

    def test_no_trigger_before_a_full_window(self):
        """Nothing fires until a whole window has actually elapsed."""
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
        codes = _drive(trigger, duration_s=110)
        self.assertNotIn(1, codes)

    def test_fires_after_a_fully_active_window(self):
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
        codes = _drive(trigger, duration_s=130)
        self.assertIn(1, codes)

    def test_ghost_trigger(self):
        """Code 2 when the window qualifies but the probability draw fails."""
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=0.0)
        codes = _drive(trigger, duration_s=130)
        self.assertIn(2, codes)
        self.assertNotIn(1, codes)

    def test_a_brief_pause_no_longer_throws_the_bout_away(self):
        """
        The regression this rule exists for. One quiet 10 s bin in 12 leaves the
        window 92% active, which clears 85%. Under the old all-or-nothing rule
        the same pause reset the clock and nothing ever fired.
        """
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
        codes = _drive(
            trigger, duration_s=130, moving_at=lambda t: not (30000 <= t < 40000)
        )
        self.assertIn(1, codes)

    def test_does_not_fire_below_the_threshold(self):
        """Three quiet bins in 12 is 75% active, under the 85% asked for."""
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
        codes = _drive(
            trigger, duration_s=130, moving_at=lambda t: not (30000 <= t < 60000)
        )
        self.assertNotIn(1, codes)

    def test_threshold_is_honoured(self):
        """The same trace fires or not depending only on the threshold."""
        quiet_quarter = lambda t: not (30000 <= t < 60000)  # noqa: E731  75% active
        self.assertNotIn(
            1,
            _drive(
                ActivityTrigger(min_active_time=120, stimulus_probability=1.0),
                duration_s=130,
                moving_at=quiet_quarter,
            ),
        )
        self.assertIn(
            1,
            _drive(
                ActivityTrigger(
                    min_active_time=120,
                    activity_threshold=0.7,
                    stimulus_probability=1.0,
                ),
                duration_s=130,
                moving_at=quiet_quarter,
            ),
        )

    def test_requires_a_fresh_window_after_firing(self):
        """One long bout must not re-fire on every subsequent frame."""
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
        codes = _drive(trigger, duration_s=240)
        self.assertEqual(codes.count(1), 2)  # one per elapsed window, not per frame

    def test_is_frame_rate_independent(self):
        """
        The point of binning. A fraction-of-frames rule concentrates towards the
        mean as the frame rate rises, so the same setting fired far less often
        on a faster camera; 'moved at all in a bin' saturates instead.
        """
        pattern = lambda t: not (30000 <= t < 40000)  # noqa: E731  92% active
        first_fire = {}
        for fps in (2, 5, 10, 25):
            trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
            codes = _drive(trigger, duration_s=130, fps=fps, moving_at=pattern)
            self.assertIn(1, codes, f"failed to fire at {fps} fps")
            step = max(1, int(round(1000 / fps)))
            first_fire[fps] = codes.index(1) * step

        spread = max(first_fire.values()) - min(first_fire.values())
        self.assertLess(spread, 1000, f"fire time drifts with frame rate: {first_fire}")

    def test_tracking_gap_closes_bins_inactive(self):
        """Bins that saw no frame at all are honestly scored as inactive."""
        trigger = ActivityTrigger(min_active_time=120, stimulus_probability=1.0)
        # 120 s of movement, then a 60 s hole, then movement resumes.
        codes = _drive(trigger, duration_s=40, t0=0)
        self.assertNotIn(1, codes)
        codes = _drive(trigger, duration_s=40, t0=100000)
        self.assertNotIn(1, codes)


# ===========================================================================
# MidlineCrossingTrigger
# ===========================================================================


class TestMidlineCrossingTrigger(unittest.TestCase):
    """Test MidlineCrossingTrigger."""

    def test_init_valid(self):
        trigger = MidlineCrossingTrigger(
            stimulus_probability=0.8, refractory_period_s=30
        )
        self.assertEqual(trigger._p, 0.8)
        self.assertEqual(trigger._refractory_period_ms, 30000)

    def test_init_invalid_probability(self):
        with self.assertRaises(ValueError):
            MidlineCrossingTrigger(stimulus_probability=2.0)

    def test_check_insufficient_positions(self):
        trigger = MidlineCrossingTrigger()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"x": 50}]]
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 0)

    def test_check_no_crossing(self):
        """No trigger when animal stays on same side."""
        trigger = MidlineCrossingTrigger()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"x": 70}], [{"x": 80}]]
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 0)

    def test_check_crossing_detected(self):
        """Code 1 when midline crossed with p=1.0."""
        trigger = MidlineCrossingTrigger(stimulus_probability=1.0)
        tracker = _make_mock_tracker()
        # Current: 70/100 - 0.5 = 0.2 (right), Previous: 30/100 - 0.5 = -0.2 (left)
        tracker.positions = [[{"x": 30}], [{"x": 70}]]
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 1)

    def test_check_ghost_crossing(self):
        """Code 2 when midline crossed with p=0.0."""
        trigger = MidlineCrossingTrigger(stimulus_probability=0.0)
        tracker = _make_mock_tracker()
        tracker.positions = [[{"x": 30}], [{"x": 70}]]
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 2)

    def test_check_refractory_period(self):
        """No trigger during refractory period."""
        trigger = MidlineCrossingTrigger(refractory_period_s=60)
        tracker = _make_mock_tracker(last_time_point=200000)
        tracker.positions = [[{"x": 30}], [{"x": 70}]]
        trigger.bind_tracker(tracker)
        trigger._last_stimulus_time = 200000  # Just fired
        code, meta = trigger.check()
        self.assertEqual(code, 0)


# ===========================================================================
# PeriodicTrigger
# ===========================================================================


class TestPeriodicTrigger(unittest.TestCase):
    """Test PeriodicTrigger."""

    def test_init_valid(self):
        trigger = PeriodicTrigger(interval_seconds=30, stimulus_probability=0.5)
        self.assertEqual(trigger._interval_ms, 30000)
        self.assertEqual(trigger._p, 0.5)

    def test_init_invalid_probability(self):
        with self.assertRaises(ValueError):
            PeriodicTrigger(stimulus_probability=-0.5)

    def test_check_fires_on_interval(self):
        """Fires when interval has elapsed."""
        trigger = PeriodicTrigger(interval_seconds=60, stimulus_probability=1.0)
        tracker = _make_mock_tracker(last_time_point=70000)  # 70s > 60s
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 1)

    def test_check_no_fire_before_interval(self):
        """No trigger before interval elapses."""
        trigger = PeriodicTrigger(interval_seconds=60, stimulus_probability=1.0)
        tracker = _make_mock_tracker(last_time_point=50000)  # 50s < 60s
        trigger.bind_tracker(tracker)
        trigger._last_fire_time = 20000  # 30s ago
        code, meta = trigger.check()
        self.assertEqual(code, 0)

    def test_check_ghost_periodic(self):
        """Code 2 when interval elapsed but probability fails."""
        trigger = PeriodicTrigger(interval_seconds=60, stimulus_probability=0.0)
        tracker = _make_mock_tracker(last_time_point=70000)
        trigger.bind_tracker(tracker)
        code, meta = trigger.check()
        self.assertEqual(code, 2)

    def test_check_updates_last_fire_time(self):
        """Last fire time updated after firing."""
        trigger = PeriodicTrigger(interval_seconds=60, stimulus_probability=1.0)
        tracker = _make_mock_tracker(last_time_point=70000)
        trigger.bind_tracker(tracker)
        trigger.check()
        self.assertEqual(trigger._last_fire_time, 70000)


# ===========================================================================
# ScheduledTrigger
# ===========================================================================


class TestScheduledTrigger(unittest.TestCase):
    """ScheduledTrigger gates an arbitrary inner trigger to a daily window."""

    def test_init_invalid_schedule(self):
        from ethoscope.utils.scheduler import DailyScheduleError

        with self.assertRaises(DailyScheduleError):
            ScheduledTrigger(PeriodicTrigger(), daily_duration_hours=30)  # > 24h

    def test_bind_tracker_propagates(self):
        inner = ActivityTrigger()
        trigger = ScheduledTrigger(inner)
        tracker = Mock()
        trigger.bind_tracker(tracker)
        self.assertIs(trigger._tracker, tracker)
        self.assertIs(inner._tracker, tracker)

    def test_suppressed_outside_active_period(self):
        """Even a trigger that would fire is silenced outside the window."""
        trigger = ScheduledTrigger(
            ActivityTrigger(min_active_time=10, stimulus_probability=1.0)
        )
        with patch.object(
            trigger._daily_scheduler, "is_active_period", return_value=False
        ):
            codes = _drive(trigger, duration_s=60)
        self.assertNotIn(1, codes)

    def test_delegates_inside_active_period(self):
        """Wraps any trigger, not just inactivity: here, an activity trigger."""
        trigger = ScheduledTrigger(
            ActivityTrigger(min_active_time=10, stimulus_probability=1.0)
        )
        with patch.object(
            trigger._daily_scheduler, "is_active_period", return_value=True
        ):
            codes = _drive(trigger, duration_s=60)
        self.assertIn(1, codes)


# ===========================================================================
# TimeRestrictedInactivityTrigger
# ===========================================================================


class TestTimeRestrictedInactivityTrigger(unittest.TestCase):
    """Test TimeRestrictedInactivityTrigger."""

    def test_init_valid(self):
        trigger = TimeRestrictedInactivityTrigger(
            min_inactive_time=60,
            daily_duration_hours=8,
            interval_hours=24,
            daily_start_time="09:00:00",
        )
        self.assertIsNotNone(trigger._trigger)
        self.assertIsNotNone(trigger._daily_scheduler)

    def test_init_invalid_schedule(self):
        """Invalid schedule parameters raise DailyScheduleError."""
        from ethoscope.utils.scheduler import DailyScheduleError

        with self.assertRaises(DailyScheduleError):
            TimeRestrictedInactivityTrigger(daily_duration_hours=30)  # > 24h

    def test_bind_tracker_propagates(self):
        """bind_tracker propagates to inner trigger."""
        trigger = TimeRestrictedInactivityTrigger()
        tracker = Mock()
        trigger.bind_tracker(tracker)
        self.assertIs(trigger._tracker, tracker)
        self.assertIs(trigger._trigger._tracker, tracker)

    def test_check_inactive_period(self):
        """Returns 0 when daily scheduler says inactive."""
        trigger = TimeRestrictedInactivityTrigger()
        tracker = _make_mock_tracker()
        trigger.bind_tracker(tracker)

        with patch.object(
            trigger._daily_scheduler, "is_active_period", return_value=False
        ):
            code, meta = trigger.check()
            self.assertEqual(code, 0)

    def test_check_active_period_delegates(self):
        """Delegates to inactivity trigger during active period."""
        trigger = TimeRestrictedInactivityTrigger(
            min_inactive_time=0, stimulus_probability=1.0
        )
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        trigger.bind_tracker(tracker)
        trigger._trigger._t0 = 0

        with patch.object(
            trigger._daily_scheduler, "is_active_period", return_value=True
        ):
            code, meta = trigger.check()
            self.assertEqual(code, 1)


# ===========================================================================
# TRIGGER_REGISTRY
# ===========================================================================


class TestTriggerRegistry(unittest.TestCase):
    """Test the trigger registry mapping."""

    def test_registry_keys(self):
        expected = {
            "inactivity",
            "activity",
            "midline_crossing",
            "periodic",
            "time_restricted",
        }
        self.assertEqual(set(TRIGGER_REGISTRY.keys()), expected)

    def test_registry_values(self):
        self.assertIs(TRIGGER_REGISTRY["inactivity"], InactivityTrigger)
        self.assertIs(TRIGGER_REGISTRY["activity"], ActivityTrigger)
        self.assertIs(TRIGGER_REGISTRY["midline_crossing"], MidlineCrossingTrigger)
        self.assertIs(TRIGGER_REGISTRY["periodic"], PeriodicTrigger)
        self.assertIs(
            TRIGGER_REGISTRY["time_restricted"], TimeRestrictedInactivityTrigger
        )


if __name__ == "__main__":
    unittest.main()
