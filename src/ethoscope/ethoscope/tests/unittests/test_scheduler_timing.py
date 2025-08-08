"""
Tests for scheduler timing logic and stimulator scheduling behavior.
These tests are designed to prevent double scheduling issues and ensure
correct timing behavior for both single and multi-stimulator configurations.
"""

import unittest
import time
from unittest.mock import Mock, patch
from datetime import datetime, timedelta

from ethoscope.utils.scheduler import Scheduler, DateRangeError
from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.stimulators import DefaultStimulator, HasInteractedVariable

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
        
        start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
        end_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))
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
        end_time = int(now + 60)    # 1 minute from now, rounded to seconds
        
        start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
        end_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"
        
        scheduler = Scheduler(date_range)
        
        # Test boundary conditions (should be exclusive of boundaries)
        self.assertFalse(scheduler.check_time_range(start_time))  # Exactly at start
        self.assertFalse(scheduler.check_time_range(end_time))    # Exactly at end
        self.assertTrue(scheduler.check_time_range(start_time + 1))  # Just after start
        self.assertTrue(scheduler.check_time_range(end_time - 1))    # Just before end
        
        # Test with fractional seconds (should still be exclusive)
        self.assertTrue(scheduler.check_time_range(start_time + 0.1))  # Just after start
        self.assertTrue(scheduler.check_time_range(end_time - 0.1))    # Just before end

    def test_scheduler_invalid_ranges(self):
        """Test scheduler with invalid date ranges."""
        now = time.time()
        
        # Test end time before start time
        start_time = now + 3600  # 1 hour from now
        end_time = now - 3600    # 1 hour ago (invalid!)
        
        start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
        end_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"
        
        with self.assertRaises(DateRangeError):
            Scheduler(date_range)

    def test_scheduler_malformed_dates(self):
        """Test scheduler with malformed date strings."""
        invalid_ranges = [
            "2025-13-45 25:70:99 > 2025-01-01 00:00:00",  # Invalid date components
            "not-a-date > 2025-01-01 00:00:00",           # Non-date string
            "2025-01-01 00:00:00 > not-a-date",           # Non-date string
            "2025-01-01 00:00:00 > 2024-01-01 00:00:00",  # End date in past
            "invalid > invalid > invalid",                # Multiple > symbols
        ]
        
        for invalid_range in invalid_ranges:
            with self.subTest(date_range=invalid_range):
                with self.assertRaises(DateRangeError):
                    Scheduler(invalid_range)
                    
    def test_scheduler_valid_edge_cases(self):
        """Test scheduler with valid edge cases that should not raise errors."""
        valid_ranges = [
            "2025-01-01 00:00:00 >",    # Missing end date (valid: active from date forever)
            "> 2025-01-01 00:00:00",    # Missing start date (valid: active until date)
            "",                         # Empty string (valid: always active)
        ]
        
        for valid_range in valid_ranges:
            with self.subTest(date_range=valid_range):
                try:
                    scheduler = Scheduler(valid_range)
                    # Should not raise an exception
                    self.assertIsNotNone(scheduler)
                except DateRangeError:
                    self.fail(f"Valid range {valid_range} should not raise DateRangeError")


class TestStimulatorSchedulingBehavior(unittest.TestCase):
    """Test stimulator scheduling behavior to prevent double scheduling issues."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware_connection = Mock()
        self.mock_tracker = Mock()
        
        # Create time ranges for testing
        self.now = time.time()
        self.past_time = self.now - 7200      # 2 hours ago
        self.current_start = self.now - 1800  # 30 minutes ago
        self.future_end = self.now + 1800     # 30 minutes from now
        self.future_time = self.now + 7200    # 2 hours from now

    def _format_time_range(self, start_time, end_time):
        """Helper to format time range strings."""
        start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
        end_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))
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
            stimulus_probability=1.0
        )
        
        stimulator.bind_tracker(self.mock_tracker)
        
        # Mock tracker data for mAGO decision logic
        self.mock_tracker.positions = []
        self.mock_tracker.times = []
        self.mock_tracker.last_time_point = self.now * 1000  # mAGO expects milliseconds
        
        # Test within active range
        with patch('time.time', return_value=self.now):
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
            stimulus_probability=1.0
        )
        past_stimulator.bind_tracker(self.mock_tracker)
        
        with patch('time.time', return_value=self.now):
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
                    "stimulus_probability": 1.0
                },
                "date_range": date_range
            }
        ]
        
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence
        )
        
        multi_stim.bind_tracker(self.mock_tracker)
        
        # Mock tracker data
        self.mock_tracker.positions = []
        self.mock_tracker.times = []
        self.mock_tracker.last_time_point = self.now * 1000
        
        # Patch the individual stimulator's apply method to track calls
        original_apply = multi_stim._stimulators[0]['instance'].apply
        apply_call_count = {'count': 0}
        
        def mock_apply():
            apply_call_count['count'] += 1
            return original_apply()
        
        multi_stim._stimulators[0]['instance'].apply = mock_apply
        
        # Test decision making
        with patch('time.time', return_value=self.now):
            interaction, result = multi_stim._decide()
        
        # Check if apply() is called appropriately based on interaction result
        if bool(interaction):  # If there was an interaction
            self.assertEqual(apply_call_count['count'], 1, "apply() should be called exactly once when there's an interaction")
        else:  # No interaction, so apply() shouldn't be called
            # However, the stimulator should still be making decisions and be active
            self.assertEqual(apply_call_count['count'], 0, "apply() shouldn't be called when there's no interaction")
            self.assertIn('active_stimulator', result, "Result should contain active stimulator info")
            self.assertEqual(result['active_stimulator'], 'mAGO', "mAGO should be the active stimulator")

    def test_multistimulator_inactive_period(self):
        """Test MultiStimulator behavior during inactive periods."""
        # Create inactive date range (in the future)
        date_range = self._format_time_range(self.future_time, self.future_time + 1800)
        
        sequence = [
            {
                "class_name": "DefaultStimulator",
                "arguments": {},
                "date_range": date_range
            }
        ]
        
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence
        )
        
        multi_stim.bind_tracker(self.mock_tracker)
        
        with patch('time.time', return_value=self.now):
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
            stimulus_probability=1.0
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
                    "stimulus_probability": 1.0
                },
                "date_range": date_range
            }
        ]
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence
        )
        multi_stim.bind_tracker(self.mock_tracker)
        
        # Mock consistent tracker state
        self.mock_tracker.positions = []
        self.mock_tracker.times = []
        self.mock_tracker.last_time_point = self.now * 1000
        
        # Test during active period
        with patch('time.time', return_value=self.now):
            single_interaction, single_result = single_stim.apply()
            multi_interaction, multi_result = multi_stim._decide()
        
        # Both should have same interaction behavior (both active or both inactive)
        self.assertEqual(bool(single_interaction), bool(multi_interaction))
        
        # Test during inactive period
        with patch('time.time', return_value=self.past_time):
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
        end_time = int(now) + 3    # 3 seconds from now (integer)
        
        start_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
        end_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"
        
        scheduler = Scheduler(date_range)
        
        # Test multiple time points within the window (using integer boundaries)
        test_times = [start_time + 1, start_time + 2, int(now), end_time - 2, end_time - 1]
        expected_results = [True, True, True, True, True]
        
        # Test boundary conditions (should be exclusive)
        boundary_tests = [(start_time, False), (end_time, False)]
        
        # Test interior points
        for test_time, expected in zip(test_times, expected_results):
            with self.subTest(test_time=test_time):
                result = scheduler.check_time_range(test_time)
                self.assertEqual(result, expected, 
                               f"Time {test_time} should be {expected} for range {date_range}")
        
        # Test boundary exclusion
        for test_time, expected in boundary_tests:
            with self.subTest(test_time=test_time):
                result = scheduler.check_time_range(test_time)
                self.assertEqual(result, expected,
                               f"Boundary time {test_time} should be {expected} for range {date_range}")


if __name__ == '__main__':
    # Run with verbose output to see individual test results
    unittest.main(verbosity=2)