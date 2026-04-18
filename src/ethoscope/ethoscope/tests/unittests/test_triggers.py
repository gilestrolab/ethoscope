"""
Unit tests for stimulators/triggers.py.

Tests all trigger conditions: InactivityTrigger, MidlineCrossingTrigger,
PeriodicTrigger, TimeRestrictedInactivityTrigger, and TRIGGER_REGISTRY.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope.stimulators.triggers import (
    TRIGGER_REGISTRY,
    BaseTrigger,
    InactivityTrigger,
    MidlineCrossingTrigger,
    PeriodicTrigger,
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
        self.assertEqual(trigger._inactivity_time_threshold_ms, 120000)
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
        self.assertIsNotNone(trigger._inactivity_trigger)
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
        self.assertIs(trigger._inactivity_trigger._tracker, tracker)

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
        trigger._inactivity_trigger._t0 = 0

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
        expected = {"inactivity", "midline_crossing", "periodic", "time_restricted"}
        self.assertEqual(set(TRIGGER_REGISTRY.keys()), expected)

    def test_registry_values(self):
        self.assertIs(TRIGGER_REGISTRY["inactivity"], InactivityTrigger)
        self.assertIs(TRIGGER_REGISTRY["midline_crossing"], MidlineCrossingTrigger)
        self.assertIs(TRIGGER_REGISTRY["periodic"], PeriodicTrigger)
        self.assertIs(
            TRIGGER_REGISTRY["time_restricted"], TimeRestrictedInactivityTrigger
        )


if __name__ == "__main__":
    unittest.main()
