"""
Unit tests for sleep restriction functionality.

Tests for DailyScheduler and mAGOSleepRestriction stimulator classes.
"""

import unittest
import tempfile
import os
import time
import json
from unittest.mock import Mock, patch, MagicMock

# Import the classes we're testing
from ethoscope.utils.scheduler import DailyScheduler, DailyScheduleError
from ethoscope.stimulators.sleep_restriction_stimulators import (
    mAGOSleepRestriction, 
    SimpleTimeRestrictedStimulator
)
from ethoscope.stimulators.stimulators import HasInteractedVariable


class TestDailyScheduler(unittest.TestCase):
    """Test cases for DailyScheduler class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.temp_dir, "test_state.json")
    
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.state_file):
            os.remove(self.state_file)
        os.rmdir(self.temp_dir)
    
    def test_init_valid_parameters(self):
        """Test initialization with valid parameters."""
        scheduler = DailyScheduler(
            daily_duration_hours=8,
            interval_hours=24,
            daily_start_time="09:00:00"
        )
        
        self.assertEqual(scheduler._daily_duration_hours, 8)
        self.assertEqual(scheduler._interval_hours, 24)
        self.assertEqual(scheduler._daily_start_time, "09:00:00")
        self.assertEqual(scheduler._start_time_seconds, 9 * 3600)  # 9 AM in seconds
    
    def test_init_invalid_duration(self):
        """Test initialization with invalid duration hours."""
        with self.assertRaises(DailyScheduleError):
            DailyScheduler(daily_duration_hours=25)  # > 24 hours
            
        with self.assertRaises(DailyScheduleError):
            DailyScheduler(daily_duration_hours=0)   # <= 0 hours
    
    def test_init_invalid_interval(self):
        """Test initialization with invalid interval hours."""
        with self.assertRaises(DailyScheduleError):
            DailyScheduler(daily_duration_hours=8, interval_hours=200)  # > 168 hours
            
        with self.assertRaises(DailyScheduleError):
            DailyScheduler(daily_duration_hours=12, interval_hours=8)  # duration > interval
    
    def test_parse_time_string(self):
        """Test time string parsing."""
        scheduler = DailyScheduler(8, 24, "00:00:00")
        
        # Test valid times
        self.assertEqual(scheduler._parse_time_string("00:00:00"), 0)
        self.assertEqual(scheduler._parse_time_string("12:30:45"), 12*3600 + 30*60 + 45)
        self.assertEqual(scheduler._parse_time_string("23:59:59"), 23*3600 + 59*60 + 59)
        
        # Test invalid times
        with self.assertRaises(DailyScheduleError):
            scheduler._parse_time_string("25:00:00")  # Invalid hour
        with self.assertRaises(DailyScheduleError):
            scheduler._parse_time_string("12:60:00")  # Invalid minute
        with self.assertRaises(DailyScheduleError):
            scheduler._parse_time_string("invalid")   # Invalid format
    
    def test_is_active_period_daily_schedule(self):
        """Test daily schedule (24-hour intervals)."""
        # 8 hours active starting at 9 AM
        scheduler = DailyScheduler(8, 24, "09:00:00")
        
        # Create test timestamps for a specific day
        # Using January 1, 2024 (Monday) as reference
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        
        # Test times
        test_8am = base_date + 8 * 3600   # 8:00 AM - should be inactive
        test_9am = base_date + 9 * 3600   # 9:00 AM - should be active (start)
        test_12pm = base_date + 12 * 3600 # 12:00 PM - should be active (middle)
        test_5pm = base_date + 17 * 3600  # 5:00 PM - should be active (end-1)
        test_6pm = base_date + 18 * 3600  # 6:00 PM - should be inactive (after end)
        
        self.assertFalse(scheduler.is_active_period(test_8am))
        self.assertTrue(scheduler.is_active_period(test_9am))
        self.assertTrue(scheduler.is_active_period(test_12pm))
        self.assertFalse(scheduler.is_active_period(test_5pm))  # 5 PM = 17:00, end is at 17:00 (exclusive)
        self.assertFalse(scheduler.is_active_period(test_6pm))
    
    def test_is_active_period_twice_daily(self):
        """Test twice-daily schedule (12-hour intervals)."""
        # 4 hours active every 12 hours starting at 6 AM
        scheduler = DailyScheduler(4, 12, "06:00:00")
        
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        
        # First period: 6 AM - 10 AM
        test_6am = base_date + 6 * 3600   # Should be active
        test_8am = base_date + 8 * 3600   # Should be active  
        test_10am = base_date + 10 * 3600 # Should be inactive (end)
        test_12pm = base_date + 12 * 3600 # Should be inactive
        
        # Second period: 6 PM - 10 PM (18:00 - 22:00)
        test_6pm = base_date + 18 * 3600  # Should be active
        test_8pm = base_date + 20 * 3600  # Should be active
        test_10pm = base_date + 22 * 3600 # Should be inactive (end)
        
        self.assertTrue(scheduler.is_active_period(test_6am))
        self.assertTrue(scheduler.is_active_period(test_8am))
        self.assertFalse(scheduler.is_active_period(test_10am))
        self.assertFalse(scheduler.is_active_period(test_12pm))
        self.assertTrue(scheduler.is_active_period(test_6pm))
        self.assertTrue(scheduler.is_active_period(test_8pm))
        self.assertFalse(scheduler.is_active_period(test_10pm))
    
    def test_get_next_active_period(self):
        """Test getting next active period."""
        scheduler = DailyScheduler(8, 24, "09:00:00")
        
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        test_8am = base_date + 8 * 3600   # Before active period
        
        next_start, next_end = scheduler.get_next_active_period(test_8am)
        
        expected_start = base_date + 9 * 3600   # 9 AM same day
        expected_end = base_date + 17 * 3600    # 5 PM same day
        
        self.assertEqual(next_start, expected_start)
        self.assertEqual(next_end, expected_end)
    
    def test_get_time_until_next_period(self):
        """Test getting time until next active period."""
        scheduler = DailyScheduler(8, 24, "09:00:00")
        
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        test_8am = base_date + 8 * 3600   # 1 hour before active period
        
        time_until = scheduler.get_time_until_next_period(test_8am)
        self.assertEqual(time_until, 3600)  # 1 hour in seconds
    
    def test_get_remaining_active_time(self):
        """Test getting remaining time in active period."""
        scheduler = DailyScheduler(8, 24, "09:00:00")
        
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        test_12pm = base_date + 12 * 3600 # Middle of active period (9 AM - 5 PM)
        
        remaining = scheduler.get_remaining_active_time(test_12pm)
        self.assertEqual(remaining, 5 * 3600)  # 5 hours remaining until 5 PM
        
        # Test inactive period
        test_8pm = base_date + 20 * 3600  # Outside active period
        remaining = scheduler.get_remaining_active_time(test_8pm)
        self.assertEqual(remaining, 0)
    
    def test_state_persistence(self):
        """Test state file persistence."""
        scheduler = DailyScheduler(
            daily_duration_hours=8,
            interval_hours=24,
            daily_start_time="09:00:00",
            state_file_path=self.state_file
        )
        
        # Trigger state creation by checking active period
        base_date = 1704067200 + 9 * 3600  # 2024-01-01 09:00:00 UTC (active)
        scheduler.is_active_period(base_date)
        
        # Check that state file was created
        self.assertTrue(os.path.exists(self.state_file))
        
        # Load and verify state content
        with open(self.state_file, 'r') as f:
            state = json.load(f)
        
        self.assertIsInstance(state, dict)
        # Should have at least one period entry
        period_keys = [k for k in state.keys() if k.startswith('period_')]
        self.assertGreater(len(period_keys), 0)
    
    def test_get_schedule_info(self):
        """Test getting comprehensive schedule information."""
        scheduler = DailyScheduler(8, 24, "09:00:00")
        
        info = scheduler.get_schedule_info()
        
        # Check required fields
        required_fields = [
            'daily_duration_hours', 'interval_hours', 'daily_start_time',
            'currently_active', 'next_period_start', 'next_period_end'
        ]
        
        for field in required_fields:
            self.assertIn(field, info)
        
        self.assertEqual(info['daily_duration_hours'], 8)
        self.assertEqual(info['interval_hours'], 24)
        self.assertEqual(info['daily_start_time'], "09:00:00")


class TestmAGOSleepRestriction(unittest.TestCase):        
    """Test cases for mAGOSleepRestriction stimulator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Mock hardware connection
        self.mock_hardware = Mock()
        
        # Mock tracker
        self.mock_tracker = Mock()
        self.mock_tracker._roi = Mock()
        self.mock_tracker._roi.idx = 1
        self.mock_tracker.positions = [[{"xy_dist_log10x1000": 1000, "x": 50, "y": 50}]]
        self.mock_tracker.times = [time.time() * 1000]
        self.mock_tracker.last_time_point = time.time() * 1000
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temp directory
        for file in os.listdir(self.temp_dir):
            os.remove(os.path.join(self.temp_dir, file))
        os.rmdir(self.temp_dir)
    
    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            state_dir=self.temp_dir
        )
        
        self.assertEqual(stimulator._daily_duration_hours, 8)
        self.assertEqual(stimulator._interval_hours, 24)
        self.assertEqual(stimulator._daily_start_time, "09:00:00")
        self.assertIsNotNone(stimulator._daily_scheduler)
    
    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters."""
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            daily_duration_hours=6,
            interval_hours=12,
            daily_start_time="06:00:00",
            stimulus_type=2,  # valves
            state_dir=self.temp_dir
        )
        
        self.assertEqual(stimulator._daily_duration_hours, 6)
        self.assertEqual(stimulator._interval_hours, 12)
        self.assertEqual(stimulator._daily_start_time, "06:00:00")
    
    def test_bind_tracker_creates_state_file(self):
        """Test that binding tracker creates ROI-specific state file."""
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            state_dir=self.temp_dir
        )
        
        stimulator.bind_tracker(self.mock_tracker)
        
        expected_state_file = os.path.join(self.temp_dir, "sleep_restriction_roi_1.json")
        self.assertEqual(stimulator._state_file_path, expected_state_file)
        self.assertEqual(stimulator._daily_scheduler._state_file_path, expected_state_file)
    
    @patch('ethoscope.utils.scheduler.time.time')
    def test_apply_during_active_period(self, mock_time):
        """Test apply() method during active period."""
        # Set up time to be in active period (9 AM on test day)
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        active_time = base_date + 9 * 3600  # 9 AM
        mock_time.return_value = active_time
        
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            state_dir=self.temp_dir
        )
        stimulator.bind_tracker(self.mock_tracker)
        
        # Mock parent apply method
        with patch.object(stimulator.__class__.__bases__[0], 'apply') as mock_parent_apply:
            mock_parent_apply.return_value = (HasInteractedVariable(1), {"channel": 1})
            
            result = stimulator.apply()
            
            # Should call parent apply during active period
            mock_parent_apply.assert_called_once()
            self.assertEqual(result[0], 1)  # Should return parent result
    
    @patch('ethoscope.utils.scheduler.time.time')
    def test_apply_during_inactive_period(self, mock_time):
        """Test apply() method during inactive period."""
        # Set up time to be in inactive period (6 AM on test day)
        base_date = 1704067200  # 2024-01-01 00:00:00 UTC
        inactive_time = base_date + 6 * 3600  # 6 AM (before 9 AM start)
        mock_time.return_value = inactive_time
        
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            state_dir=self.temp_dir
        )
        stimulator.bind_tracker(self.mock_tracker)
        
        # Mock parent apply method
        with patch.object(stimulator.__class__.__bases__[0], 'apply') as mock_parent_apply:
            result = stimulator.apply()
            
            # Should NOT call parent apply during inactive period
            mock_parent_apply.assert_not_called()
            self.assertEqual(result[0], 0)  # Should return inactive (False = 0)
    
    def test_get_schedule_status(self):
        """Test getting schedule status information."""
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            state_dir=self.temp_dir
        )
        
        status = stimulator.get_schedule_status()
        
        # Check required fields
        required_fields = ['overall_experiment_active', 'daily_schedule', 'fully_active', 'status']
        for field in required_fields:
            self.assertIn(field, status)
        
        self.assertIsInstance(status['daily_schedule'], dict)
    
    def test_get_daily_activity_log(self):
        """Test getting daily activity log."""
        stimulator = mAGOSleepRestriction(
            hardware_connection=self.mock_hardware,
            state_dir=self.temp_dir
        )
        stimulator.bind_tracker(self.mock_tracker)
        
        log = stimulator.get_daily_activity_log()
        
        self.assertIn('state_file', log)
        self.assertIn('activity_periods', log)
        self.assertIsInstance(log['activity_periods'], dict)


class TestSimpleTimeRestrictedStimulator(unittest.TestCase):
    """Test cases for SimpleTimeRestrictedStimulator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.mock_hardware = Mock()
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temp directory
        for file in os.listdir(self.temp_dir):
            os.remove(os.path.join(self.temp_dir, file))
        os.rmdir(self.temp_dir)
    
    def test_preset_patterns(self):
        """Test preset restriction patterns."""
        test_cases = [
            (1, 8, 24),   # 8h/day
            (2, 12, 24),  # 12h/day  
            (3, 6, 12),   # 6h twice/day
            (4, 4, 8),    # 4h three times/day
        ]
        
        for pattern, expected_duration, expected_interval in test_cases:
            stimulator = SimpleTimeRestrictedStimulator(
                hardware_connection=self.mock_hardware,
                restriction_pattern=pattern,
                state_dir=self.temp_dir
            )
            
            self.assertEqual(stimulator._daily_duration_hours, expected_duration)
            self.assertEqual(stimulator._interval_hours, expected_interval)
    
    def test_custom_pattern(self):
        """Test custom pattern (pattern 5)."""
        stimulator = SimpleTimeRestrictedStimulator(
            hardware_connection=self.mock_hardware,
            restriction_pattern=5,
            custom_duration_hours=10,
            custom_interval_hours=16,
            state_dir=self.temp_dir
        )
        
        self.assertEqual(stimulator._daily_duration_hours, 10)
        self.assertEqual(stimulator._interval_hours, 16)
    
    def test_invalid_pattern(self):
        """Test invalid restriction pattern."""
        with self.assertRaises(ValueError):
            SimpleTimeRestrictedStimulator(
                hardware_connection=self.mock_hardware,
                restriction_pattern=6,  # Invalid pattern
                state_dir=self.temp_dir
            )
    
    def test_get_pattern_info(self):
        """Test getting pattern information."""
        stimulator = SimpleTimeRestrictedStimulator(
            hardware_connection=self.mock_hardware,
            restriction_pattern=1,
            state_dir=self.temp_dir
        )
        
        info = stimulator.get_pattern_info()
        
        required_fields = ['pattern_description', 'daily_duration_hours', 'interval_hours', 'daily_start_time']
        for field in required_fields:
            self.assertIn(field, info)
        
        self.assertIn("8 hours active per day", info['pattern_description'])


if __name__ == '__main__':
    unittest.main()