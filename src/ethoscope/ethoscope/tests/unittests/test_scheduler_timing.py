"""
Tests for scheduler timing logic and stimulator scheduling behavior.
These tests are designed to prevent double scheduling issues and ensure
correct timing behavior for both single and multi-stimulator configurations.
"""

import os
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.stimulators import DefaultStimulator, HasInteractedVariable
from ethoscope.utils.scheduler import DateRangeError, Scheduler

# Optional imports for specific stimulator tests
try:
    from ethoscope.stimulators.sleep_depriver_stimulators import mAGO

    HAS_MAGO = True
except ImportError:
    HAS_MAGO = False


class TestSchedulerTiming(unittest.TestCase):
    """Test scheduler date range parsing and timing logic."""

    def test_scheduler_basic_range(self):
        """Test basic date range parsing and timing."""
        # Create a range from 1 hour ago to 1 hour from now
        now = time.time()
        start_time = now - 3600
        end_time = now + 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        scheduler = Scheduler(date_range)

        # Should be active now
        self.assertTrue(scheduler.check_time_range())

        # Should not be active in the past (before start)
        self.assertFalse(scheduler.check_time_range(start_time - 1800))

        # Should not be active in the future (after end)
        self.assertFalse(scheduler.check_time_range(end_time + 1800))

    def test_scheduler_edge_cases(self):
        """Test scheduler edge cases and boundary conditions."""
        now = time.time()

        # Test exact boundary times - use times that align with second precision to avoid parsing issues
        start_time = int(now - 60)  # 1 minute ago, rounded to seconds
        end_time = int(now + 60)  # 1 minute from now, rounded to seconds

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        scheduler = Scheduler(date_range)

        # Test boundary conditions (should be exclusive of boundaries)
        self.assertFalse(scheduler.check_time_range(start_time))  # Exactly at start
        self.assertFalse(scheduler.check_time_range(end_time))  # Exactly at end
        self.assertTrue(scheduler.check_time_range(start_time + 1))  # Just after start
        self.assertTrue(scheduler.check_time_range(end_time - 1))  # Just before end

        # Test with fractional seconds (should still be exclusive)
        self.assertTrue(
            scheduler.check_time_range(start_time + 0.1)
        )  # Just after start
        self.assertTrue(scheduler.check_time_range(end_time - 0.1))  # Just before end

    def test_scheduler_invalid_ranges(self):
        """Test scheduler with invalid date ranges."""
        now = time.time()

        # Test end time before start time
        start_time = now + 3600  # 1 hour from now
        end_time = now - 3600  # 1 hour ago (invalid!)

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        with self.assertRaises(DateRangeError):
            Scheduler(date_range)

    def test_scheduler_malformed_dates(self):
        """Test scheduler with malformed date strings."""
        invalid_ranges = [
            "2025-13-45 25:70:99 > 2025-01-01 00:00:00",  # Invalid date components
            "not-a-date > 2025-01-01 00:00:00",  # Non-date string
            "2025-01-01 00:00:00 > not-a-date",  # Non-date string
            "2025-01-01 00:00:00 > 2024-01-01 00:00:00",  # End date in past
            "invalid > invalid > invalid",  # Multiple > symbols
        ]

        for invalid_range in invalid_ranges:
            with self.subTest(date_range=invalid_range):
                with self.assertRaises(DateRangeError):
                    Scheduler(invalid_range)

    def test_scheduler_valid_edge_cases(self):
        """Test scheduler with valid edge cases that should not raise errors."""
        valid_ranges = [
            "2025-01-01 00:00:00 >",  # Missing end date (valid: active from date forever)
            "> 2025-01-01 00:00:00",  # Missing start date (valid: active until date)
            "",  # Empty string (valid: always active)
        ]

        for valid_range in valid_ranges:
            with self.subTest(date_range=valid_range):
                try:
                    scheduler = Scheduler(valid_range)
                    # Should not raise an exception
                    self.assertIsNotNone(scheduler)
                except DateRangeError:
                    self.fail(
                        f"Valid range {valid_range} should not raise DateRangeError"
                    )


class TestStimulatorSchedulingBehavior(unittest.TestCase):
    """Test stimulator scheduling behavior to prevent double scheduling issues."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware_connection = Mock()
        self.mock_tracker = Mock()

        # Create time ranges for testing
        self.now = time.time()
        self.past_time = self.now - 7200  # 2 hours ago
        self.current_start = self.now - 1800  # 30 minutes ago
        self.future_end = self.now + 1800  # 30 minutes from now
        self.future_time = self.now + 7200  # 2 hours from now

    def _format_time_range(self, start_time, end_time):
        """Helper to format time range strings."""
        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        return f"{start_str} > {end_str}"

    @unittest.skipUnless(HAS_MAGO, "mAGO stimulator not available")
    def test_single_stimulator_timing(self):
        """Test that single stimulator respects its own date range."""
        # Create active date range
        date_range = self._format_time_range(self.current_start, self.future_end)

        # Test with mAGO stimulator
        stimulator = mAGO(
            hardware_connection=self.mock_hardware_connection,
            date_range=date_range,
            min_inactive_time=120,
            pulse_duration=1000,
            stimulus_type=1,
            stimulus_probability=1.0,
        )

        stimulator.bind_tracker(self.mock_tracker)

        # Mock tracker data for mAGO decision logic
        self.mock_tracker.positions = []
        self.mock_tracker.times = []
        self.mock_tracker.last_time_point = self.now * 1000  # mAGO expects milliseconds

        # Test within active range
        with patch("time.time", return_value=self.now):
            interaction, result = stimulator.apply()
            # Should be able to make decisions (not blocked by scheduler)
            self.assertIsInstance(interaction, HasInteractedVariable)

        # Test outside active range (in the past)
        past_date_range = self._format_time_range(self.past_time, self.past_time + 1800)
        past_stimulator = mAGO(
            hardware_connection=self.mock_hardware_connection,
            date_range=past_date_range,
            min_inactive_time=120,
            pulse_duration=1000,
            stimulus_type=1,
            stimulus_probability=1.0,
        )
        past_stimulator.bind_tracker(self.mock_tracker)

        with patch("time.time", return_value=self.now):
            interaction, result = past_stimulator.apply()
            # Should be blocked by scheduler
            self.assertEqual(bool(interaction), False)
            self.assertEqual(result, {})

    @unittest.skipUnless(HAS_MAGO, "mAGO stimulator not available")
    def test_multistimulator_double_scheduling_prevention(self):
        """Test that MultiStimulator doesn't cause double scheduling."""
        # Create active date range
        date_range = self._format_time_range(self.current_start, self.future_end)

        sequence = [
            {
                "class_name": "mAGO",
                "arguments": {
                    "velocity_correction_coef": 0.003,
                    "min_inactive_time": 120,
                    "pulse_duration": 1000,
                    "stimulus_type": 1,
                    "stimulus_probability": 1.0,
                },
                "date_range": date_range,
            }
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        multi_stim.bind_tracker(self.mock_tracker)

        # Mock tracker data
        self.mock_tracker.positions = []
        self.mock_tracker.times = []
        self.mock_tracker.last_time_point = self.now * 1000

        # Patch the individual stimulator's apply method to track calls
        original_apply = multi_stim._stimulators[0]["instance"].apply
        apply_call_count = {"count": 0}

        def mock_apply():
            apply_call_count["count"] += 1
            return original_apply()

        multi_stim._stimulators[0]["instance"].apply = mock_apply

        # Test decision making
        with patch("time.time", return_value=self.now):
            interaction, result = multi_stim._decide()

        # Check if apply() is called appropriately based on interaction result
        if bool(interaction):  # If there was an interaction
            self.assertEqual(
                apply_call_count["count"],
                1,
                "apply() should be called exactly once when there's an interaction",
            )
        else:  # No interaction, so apply() shouldn't be called
            # However, the stimulator should still be making decisions and be active
            self.assertEqual(
                apply_call_count["count"],
                0,
                "apply() shouldn't be called when there's no interaction",
            )
            self.assertIn(
                "active_stimulator",
                result,
                "Result should contain active stimulator info",
            )
            self.assertEqual(
                result["active_stimulator"],
                "mAGO",
                "mAGO should be the active stimulator",
            )

    def test_multistimulator_inactive_period(self):
        """Test MultiStimulator behavior during inactive periods."""
        # Create inactive date range (in the future)
        date_range = self._format_time_range(self.future_time, self.future_time + 1800)

        sequence = [
            {
                "class_name": "DefaultStimulator",
                "arguments": {},
                "date_range": date_range,
            }
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        multi_stim.bind_tracker(self.mock_tracker)

        with patch("time.time", return_value=self.now):
            interaction, result = multi_stim._decide()

        # Should return no interaction during inactive period
        self.assertEqual(bool(interaction), False)
        self.assertEqual(result, {})

    @unittest.skipUnless(HAS_MAGO, "mAGO stimulator not available")
    def test_multistimulator_vs_single_stimulator_equivalence(self):
        """Test that single stimulator and MultiStimulator with one stimulator behave equivalently."""
        date_range = self._format_time_range(self.current_start, self.future_end)

        # Single stimulator
        single_stim = mAGO(
            hardware_connection=self.mock_hardware_connection,
            date_range=date_range,
            min_inactive_time=120,
            pulse_duration=1000,
            stimulus_type=1,
            stimulus_probability=1.0,
        )
        single_stim.bind_tracker(self.mock_tracker)

        # MultiStimulator with same configuration
        sequence = [
            {
                "class_name": "mAGO",
                "arguments": {
                    "velocity_correction_coef": 0.003,
                    "min_inactive_time": 120,
                    "pulse_duration": 1000,
                    "stimulus_type": 1,
                    "stimulus_probability": 1.0,
                },
                "date_range": date_range,
            }
        ]
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )
        multi_stim.bind_tracker(self.mock_tracker)

        # Mock consistent tracker state
        self.mock_tracker.positions = []
        self.mock_tracker.times = []
        self.mock_tracker.last_time_point = self.now * 1000

        # Test during active period
        with patch("time.time", return_value=self.now):
            single_interaction, single_result = single_stim.apply()
            multi_interaction, multi_result = multi_stim._decide()

        # Both should have same interaction behavior (both active or both inactive)
        self.assertEqual(bool(single_interaction), bool(multi_interaction))

        # Test during inactive period
        with patch("time.time", return_value=self.past_time):
            single_interaction, single_result = single_stim.apply()
            multi_interaction, multi_result = multi_stim._decide()

        # Both should be inactive
        self.assertEqual(bool(single_interaction), False)
        self.assertEqual(bool(multi_interaction), False)

    def test_scheduler_time_precision(self):
        """Test scheduler timing precision to ensure consistent behavior."""
        # Test with precise second boundaries to avoid fractional second issues
        now = time.time()

        # Create 6-second window with proper integer boundaries
        start_time = int(now) - 3  # 3 seconds ago (integer)
        end_time = int(now) + 3  # 3 seconds from now (integer)

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        scheduler = Scheduler(date_range)

        # Test multiple time points within the window (using integer boundaries)
        test_times = [
            start_time + 1,
            start_time + 2,
            int(now),
            end_time - 2,
            end_time - 1,
        ]
        expected_results = [True, True, True, True, True]

        # Test boundary conditions (should be exclusive)
        boundary_tests = [(start_time, False), (end_time, False)]

        # Test interior points
        for test_time, expected in zip(test_times, expected_results):
            with self.subTest(test_time=test_time):
                result = scheduler.check_time_range(test_time)
                self.assertEqual(
                    result,
                    expected,
                    f"Time {test_time} should be {expected} for range {date_range}",
                )

        # Test boundary exclusion
        for test_time, expected in boundary_tests:
            with self.subTest(test_time=test_time):
                result = scheduler.check_time_range(test_time)
                self.assertEqual(
                    result,
                    expected,
                    f"Boundary time {test_time} should be {expected} for range {date_range}",
                )


if __name__ == "__main__":
    # Run with verbose output to see individual test results
    unittest.main(verbosity=2)


class TestSchedulerAdditional(unittest.TestCase):
    """Additional tests for Scheduler class methods."""

    def test_get_schedule_state_scheduled(self):
        """Test get_schedule_state returns 'scheduled' when in range."""
        now = time.time()
        start_time = now - 3600
        end_time = now + 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        scheduler = Scheduler(date_range)
        self.assertEqual(scheduler.get_schedule_state(), "scheduled")
        self.assertEqual(scheduler.get_schedule_state(now), "scheduled")

    def test_get_schedule_state_inactive(self):
        """Test get_schedule_state returns 'inactive' when out of range."""
        now = time.time()
        future_start = now + 7200
        future_end = now + 10800

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(future_start))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(future_end))
        date_range = f"{start_str} > {end_str}"

        scheduler = Scheduler(date_range)
        self.assertEqual(scheduler.get_schedule_state(), "inactive")
        self.assertEqual(scheduler.get_schedule_state(now), "inactive")

    def test_multiple_date_ranges(self):
        """Test scheduler with multiple comma-separated date ranges."""
        now = time.time()

        # Create two separate ranges: one past, one future
        past_start = now - 7200
        past_end = now - 3600
        future_start = now + 3600
        future_end = now + 7200

        past_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_start))} > "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_end))}"
        )
        future_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_start))} > "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_end))}"
        )

        scheduler = Scheduler(f"{past_range},{future_range}")

        # Should not be active now (between the two ranges)
        self.assertFalse(scheduler.check_time_range())

        # Should be active during past range
        self.assertTrue(scheduler.check_time_range(past_start + 1800))

        # Should be active during future range
        self.assertTrue(scheduler.check_time_range(future_start + 1800))

    def test_overlapping_date_ranges_raises_error(self):
        """Test that overlapping date ranges raise DateRangeError."""
        now = time.time()

        range1_start = now
        range1_end = now + 7200
        range2_start = now + 3600  # Overlaps with range1
        range2_end = now + 10800

        range1 = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(range1_start))} > "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(range1_end))}"
        )
        range2 = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(range2_start))} > "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(range2_end))}"
        )

        with self.assertRaises(DateRangeError) as context:
            Scheduler(f"{range1},{range2}")
        self.assertIn("overlap", str(context.exception))


class TestDailyScheduler(unittest.TestCase):
    """Test suite for DailyScheduler class."""

    def test_init_valid_params(self):
        """Test DailyScheduler initialization with valid parameters."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(
            daily_duration_hours=8, interval_hours=24, daily_start_time="09:00:00"
        )

        self.assertEqual(scheduler._daily_duration_hours, 8)
        self.assertEqual(scheduler._interval_hours, 24)
        self.assertEqual(scheduler._daily_start_time, "09:00:00")

    def test_init_invalid_daily_duration_zero(self):
        """Test initialization fails with zero daily_duration_hours."""
        from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler

        with self.assertRaises(DailyScheduleError) as context:
            DailyScheduler(daily_duration_hours=0, interval_hours=24)
        self.assertIn("between 0 and 24", str(context.exception))

    def test_init_invalid_daily_duration_too_large(self):
        """Test initialization fails with daily_duration_hours > 24."""
        from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler

        with self.assertRaises(DailyScheduleError) as context:
            DailyScheduler(daily_duration_hours=25, interval_hours=24)
        self.assertIn("between 0 and 24", str(context.exception))

    def test_init_invalid_interval_zero(self):
        """Test initialization fails with zero interval_hours."""
        from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler

        with self.assertRaises(DailyScheduleError) as context:
            DailyScheduler(daily_duration_hours=8, interval_hours=0)
        self.assertIn("between 0 and 168", str(context.exception))

    def test_init_invalid_interval_too_large(self):
        """Test initialization fails with interval_hours > 168."""
        from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler

        with self.assertRaises(DailyScheduleError) as context:
            DailyScheduler(daily_duration_hours=8, interval_hours=200)
        self.assertIn("between 0 and 168", str(context.exception))

    def test_init_duration_exceeds_interval(self):
        """Test initialization fails when duration exceeds interval."""
        from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler

        with self.assertRaises(DailyScheduleError) as context:
            DailyScheduler(daily_duration_hours=10, interval_hours=8)
        self.assertIn("cannot exceed interval", str(context.exception))

    def test_parse_time_string_valid(self):
        """Test _parse_time_string with valid time strings."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(8, 24, "09:30:45")

        # 9 hours * 3600 + 30 minutes * 60 + 45 seconds
        expected = 9 * 3600 + 30 * 60 + 45
        self.assertEqual(scheduler._start_time_seconds, expected)

    def test_parse_time_string_midnight(self):
        """Test _parse_time_string with midnight."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(8, 24, "00:00:00")
        self.assertEqual(scheduler._start_time_seconds, 0)

    def test_parse_time_string_invalid_format(self):
        """Test _parse_time_string raises error for invalid format."""
        from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler

        with self.assertRaises(DailyScheduleError) as context:
            DailyScheduler(8, 24, "25:00:00")  # Invalid hour
        self.assertIn("Invalid time format", str(context.exception))

    def test_is_active_period_during_active_time(self):
        """Test is_active_period returns True during active period."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Test at 1 hour after midnight (should be active)
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 3600  # 1 hour after midnight

        self.assertTrue(scheduler.is_active_period(test_time))

    def test_is_active_period_outside_active_time(self):
        """Test is_active_period returns False outside active period."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Test at 3 hours after midnight (should be inactive)
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 10800  # 3 hours after midnight

        self.assertFalse(scheduler.is_active_period(test_time))

    def test_get_next_active_period(self):
        """Test get_next_active_period returns correct timestamps."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Test from a time well past midnight
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 43200  # Noon

        next_start, next_end = scheduler.get_next_active_period(test_time)

        # Next period should start tomorrow at midnight
        expected_start = (days_since_epoch + 1) * 86400
        expected_end = expected_start + 7200  # 2 hours later

        self.assertEqual(next_start, expected_start)
        self.assertEqual(next_end, expected_end)

    def test_get_time_until_next_period(self):
        """Test get_time_until_next_period returns correct seconds."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Test from noon
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 43200  # Noon

        time_until = scheduler.get_time_until_next_period(test_time)

        # Should be 12 hours until midnight
        self.assertEqual(time_until, 43200)

    def test_get_remaining_active_time_during_active(self):
        """Test get_remaining_active_time during active period."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Test at 1 hour after midnight (1 hour remaining)
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 3600  # 1 hour after midnight

        remaining = scheduler.get_remaining_active_time(test_time)
        self.assertEqual(remaining, 3600)  # 1 hour remaining

    def test_get_remaining_active_time_when_inactive(self):
        """Test get_remaining_active_time returns 0 when inactive."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Test at 3 hours after midnight (inactive)
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 10800  # 3 hours after midnight

        remaining = scheduler.get_remaining_active_time(test_time)
        self.assertEqual(remaining, 0)

    def test_get_schedule_info_active(self):
        """Test get_schedule_info returns correct info during active period."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Mock time to 1 hour after midnight
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 3600  # 1 hour after midnight

        with patch("time.time", return_value=test_time):
            info = scheduler.get_schedule_info()

        self.assertEqual(info["daily_duration_hours"], 2)
        self.assertEqual(info["interval_hours"], 24)
        self.assertEqual(info["daily_start_time"], "00:00:00")
        self.assertTrue(info["currently_active"])
        self.assertIn("remaining_active_seconds", info)
        self.assertEqual(info["remaining_active_seconds"], 3600)

    def test_get_schedule_info_inactive(self):
        """Test get_schedule_info returns correct info when inactive."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 2 hours active every 24 hours starting at midnight
        scheduler = DailyScheduler(2, 24, "00:00:00")

        # Mock time to noon (inactive)
        now = time.time()
        days_since_epoch = int(now // 86400)
        test_time = days_since_epoch * 86400 + 43200  # Noon

        with patch("time.time", return_value=test_time):
            info = scheduler.get_schedule_info()

        self.assertFalse(info["currently_active"])
        self.assertIn("seconds_until_next_period", info)
        self.assertEqual(info["seconds_until_next_period"], 43200)

    def test_state_persistence_without_file(self):
        """Test scheduler works without state file."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(8, 24, state_file_path=None)
        self.assertEqual(scheduler._state, {})

        # Should still work normally
        self.assertIsInstance(scheduler.is_active_period(), bool)

    def test_state_load_nonexistent_file(self):
        """Test _load_state handles nonexistent file gracefully."""
        import tempfile

        from ethoscope.utils.scheduler import DailyScheduler

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "nonexistent.json")
            scheduler = DailyScheduler(8, 24, state_file_path=state_file)

            # Should return empty dict for nonexistent file
            self.assertEqual(scheduler._state, {})

    def test_date_range_single_start_date_with_value(self):
        """Test date range parsing with single non-None start date (line 93)."""
        # Use a date string WITHOUT ">" to get len(date_strs) == 1
        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

        scheduler = Scheduler(start_str)
        # Should be active from start_str to infinity
        self.assertTrue(scheduler.check_time_range(time.time() + 3600))

    def test_date_range_two_none_dates_error(self):
        """Test that two None dates raise DateRangeError (line 99)."""
        # Empty string on both sides of ">" gives two None dates
        with self.assertRaises(DateRangeError):
            Scheduler(" > ")

    def test_date_range_unexpected_format_error(self):
        """Test that unexpected date formats raise Exception (line 106)."""
        # Line 106 is unreachable in normal usage (line 82-83 catches > 2 dates)
        # Test the precondition at line 82-83 instead
        with self.assertRaises(DateRangeError):
            Scheduler("2025-01-01 > 2025-02-01 > 2025-03-01")

    def test_state_file_io_error_on_load(self):
        """Test _load_state handles file I/O errors gracefully (lines 210-215)."""
        import tempfile

        from ethoscope.utils.scheduler import DailyScheduler

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "corrupted.json")
            # Create corrupted JSON file
            with open(state_file, "w") as f:
                f.write("{invalid json content")

            scheduler = DailyScheduler(8, 24, state_file_path=state_file)
            # Should handle corrupted file and return empty dict
            self.assertEqual(scheduler._state, {})

    def test_state_file_io_error_on_save(self):
        """Test _save_state handles file I/O errors gracefully (lines 219-227)."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Use invalid path to trigger OSError
        state_file = "/nonexistent_dir/cannot_write/state.json"
        scheduler = DailyScheduler(8, 24, state_file_path=state_file)

        # Force a save attempt (should handle error gracefully)
        scheduler._state["test"] = "value"
        scheduler._save_state()  # Should not raise exception

    def test_is_active_period_before_start_time(self):
        """Test is_active_period when t < start_timestamp (line 257)."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create scheduler: 8 hours active starting at 10:00
        scheduler = DailyScheduler(8, 24, daily_start_time="10:00:00")

        # Test at 08:00 (before start time)
        days_since_epoch = int(time.time() // 86400)
        test_time = days_since_epoch * 86400 + (8 * 3600)  # 08:00 today

        is_active = scheduler.is_active_period(test_time)
        # Should be inactive before start time
        self.assertFalse(is_active)

    def test_state_tracking_during_active_period(self):
        """Test state file updates during active period (lines 269-276)."""
        import tempfile

        from ethoscope.utils.scheduler import DailyScheduler

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")

            # Create scheduler: 30-min duration, 1-hour intervals, starting at midnight
            scheduler = DailyScheduler(
                0.5,
                interval_hours=1,
                daily_start_time="00:00:00",
                state_file_path=state_file,
            )

            # Check during an active period
            current_time = time.time()
            is_active = scheduler.is_active_period(current_time)

            if is_active:
                # State file should be updated
                self.assertTrue(os.path.exists(state_file))
                # State should contain period information
                self.assertGreater(len(scheduler._state), 0)

    def test_get_next_active_period_with_none(self):
        """Test get_next_active_period with t=None (line 291)."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(8, 24, daily_start_time="10:00:00")

        # Call with t=None (should use current time)
        next_start, next_end = scheduler.get_next_active_period(t=None)

        self.assertIsInstance(next_start, (int, float))
        self.assertIsInstance(next_end, (int, float))
        self.assertGreater(next_end, next_start)

    def test_get_next_active_period_before_start(self):
        """Test get_next_active_period when t < start_timestamp (line 305)."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(8, 24, daily_start_time="12:00:00")

        # Test at 08:00 (before start time)
        days_since_epoch = int(time.time() // 86400)
        test_time = days_since_epoch * 86400 + (8 * 3600)  # 08:00 today

        next_start, next_end = scheduler.get_next_active_period(test_time)

        # Next period should be at 12:00 today
        expected_start = days_since_epoch * 86400 + (12 * 3600)
        self.assertEqual(next_start, expected_start)

    def test_get_time_until_next_period_with_none(self):
        """Test get_time_until_next_period with t=None (line 322)."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(8, 24, daily_start_time="10:00:00")

        # Call with t=None (should use current time)
        time_until = scheduler.get_time_until_next_period(t=None)

        self.assertIsInstance(time_until, (int, float))
        self.assertGreaterEqual(time_until, 0)

    def test_get_remaining_active_time_with_none(self):
        """Test get_remaining_active_time with t=None (line 341)."""
        from ethoscope.utils.scheduler import DailyScheduler

        scheduler = DailyScheduler(24, 24, daily_start_time="00:00:00")

        # Call with t=None during active period
        remaining = scheduler.get_remaining_active_time(t=None)

        self.assertIsInstance(remaining, (int, float))
        self.assertGreaterEqual(remaining, 0)

    def test_save_state_without_file_path(self):
        """Test _save_state returns early when no file path set (line 220)."""
        from ethoscope.utils.scheduler import DailyScheduler

        # Create without state file
        scheduler = DailyScheduler(8, 24, state_file_path=None)
        scheduler._state["test"] = "value"

        # Should return early, no exception
        scheduler._save_state()
        # No assertion needed, just verifying it doesn't crash

    def test_save_state_successful_write(self):
        """Test _save_state successfully writes to file (lines 224-225)."""
        import json
        import tempfile

        from ethoscope.utils.scheduler import DailyScheduler

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "subdir", "state.json")
            scheduler = DailyScheduler(8, 24, state_file_path=state_file)

            # Add some state
            scheduler._state["test_key"] = "test_value"

            # Save state
            scheduler._save_state()

            # Verify file was created and contains correct data
            self.assertTrue(os.path.exists(state_file))

            with open(state_file) as f:
                saved_state = json.load(f)

            self.assertEqual(saved_state["test_key"], "test_value")

    def test_state_tracking_with_new_period(self):
        """Test state tracking creates new period entry (lines 269-276)."""
        import tempfile

        from ethoscope.utils.scheduler import DailyScheduler

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")

            # Create scheduler that's currently active
            scheduler = DailyScheduler(
                24, 24, daily_start_time="00:00:00", state_file_path=state_file
            )

            # Clear any existing state to force new period creation
            scheduler._state = {}

            # Get current time and check if active
            current_time = time.time()
            is_active = scheduler.is_active_period(current_time)

            if is_active:
                # State should have been updated with new period
                self.assertGreater(len(scheduler._state), 0)

                # Verify state file was created
                self.assertTrue(os.path.exists(state_file))

                # Check that period info was saved
                period_keys = [
                    k for k in scheduler._state.keys() if k.startswith("period_")
                ]
                self.assertGreater(len(period_keys), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
