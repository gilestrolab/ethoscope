"""
Unit tests for base stimulator classes.

Tests BaseStimulator, DefaultStimulator, and related functionality including:
- Stimulator initialization and binding
- Scheduler integration
- Hardware interaction
- Template overrides for ROI mappings
- State tracking and reporting
"""

import time
import unittest
from unittest.mock import Mock, patch

from ethoscope.stimulators.stimulators import (
    BaseStimulator,
    DefaultStimulator,
    HasInteractedVariable,
)


class TestHasInteractedVariable(unittest.TestCase):
    """Test suite for HasInteractedVariable."""

    def test_functional_type(self):
        """Test HasInteractedVariable has correct functional_type."""
        self.assertEqual(HasInteractedVariable.functional_type, "interaction")

    def test_header_name(self):
        """Test HasInteractedVariable has correct header_name."""
        self.assertEqual(HasInteractedVariable.header_name, "has_interacted")

    def test_initialization(self):
        """Test HasInteractedVariable can be initialized."""
        var = HasInteractedVariable(True)
        self.assertIsNotNone(var)

        var_false = HasInteractedVariable(False)
        self.assertIsNotNone(var_false)


class TestDefaultStimulator(unittest.TestCase):
    """Test suite for DefaultStimulator."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware = Mock()
        self.mock_tracker = Mock()

    def test_init_without_date_range(self):
        """Test DefaultStimulator initialization without date range."""
        stimulator = DefaultStimulator(self.mock_hardware)
        self.assertIsNotNone(stimulator)
        self.assertEqual(stimulator._hardware_connection, self.mock_hardware)

    def test_init_with_date_range(self):
        """Test DefaultStimulator initialization with date range."""
        now = time.time()
        start_time = now - 3600
        end_time = now + 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        stimulator = DefaultStimulator(self.mock_hardware, date_range=date_range)
        self.assertIsNotNone(stimulator)

    def test_bind_tracker(self):
        """Test bind_tracker method."""
        stimulator = DefaultStimulator(self.mock_hardware)
        stimulator.bind_tracker(self.mock_tracker)

        self.assertEqual(stimulator._tracker, self.mock_tracker)

    def test_apply_without_tracker_raises(self):
        """Test apply() raises ValueError when no tracker is bound."""
        stimulator = DefaultStimulator(self.mock_hardware)

        with self.assertRaises(ValueError) as context:
            stimulator.apply()
        self.assertIn("No tracker bound", str(context.exception))

    def test_apply_with_tracker(self):
        """Test apply() works when tracker is bound."""
        stimulator = DefaultStimulator(self.mock_hardware)
        stimulator.bind_tracker(self.mock_tracker)

        interact, result = stimulator.apply()

        self.assertIsInstance(interact, HasInteractedVariable)
        self.assertEqual(bool(interact), False)
        self.assertEqual(result, {})

    def test_apply_outside_schedule(self):
        """Test apply() returns False when outside scheduled range."""
        # Create date range in the past
        now = time.time()
        past_start = now - 7200
        past_end = now - 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(past_start))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(past_end))
        date_range = f"{start_str} > {end_str}"

        stimulator = DefaultStimulator(self.mock_hardware, date_range=date_range)
        stimulator.bind_tracker(self.mock_tracker)

        interact, result = stimulator.apply()

        self.assertEqual(bool(interact), False)
        self.assertEqual(result, {})

    def test_decide_method(self):
        """Test _decide() method returns correct values."""
        stimulator = DefaultStimulator(self.mock_hardware)

        interact, result = stimulator._decide()

        self.assertIsInstance(interact, HasInteractedVariable)
        self.assertEqual(bool(interact), False)
        self.assertEqual(result, {})


class TestBaseStimulator(unittest.TestCase):
    """Test suite for BaseStimulator functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware = Mock()
        self.mock_tracker = Mock()

    def test_deliver_with_hardware(self):
        """Test _deliver() sends instruction to hardware."""

        class TestStimulator(BaseStimulator):
            def _decide(self):
                return HasInteractedVariable(True), {"channel": 1, "duration": 1000}

        stimulator = TestStimulator(self.mock_hardware)
        stimulator.bind_tracker(self.mock_tracker)

        # Call apply which will trigger _deliver
        interact, result = stimulator.apply()

        # Verify hardware was called
        self.mock_hardware.send_instruction.assert_called_once()
        call_args = self.mock_hardware.send_instruction.call_args[0][0]
        self.assertIn("channel", call_args)
        self.assertIn("duration", call_args)

    def test_deliver_without_hardware(self):
        """Test _deliver() works without hardware connection."""

        class TestStimulator(BaseStimulator):
            def _decide(self):
                return HasInteractedVariable(True), {"channel": 1}

        stimulator = TestStimulator(None)  # No hardware
        stimulator.bind_tracker(self.mock_tracker)

        # Should not raise exception
        interact, result = stimulator.apply()
        self.assertEqual(bool(interact), True)

    def test_get_stimulator_state_inactive(self):
        """Test get_stimulator_state returns 'inactive' outside schedule."""
        # Create date range in the past
        now = time.time()
        past_start = now - 7200
        past_end = now - 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(past_start))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(past_end))
        date_range = f"{start_str} > {end_str}"

        stimulator = DefaultStimulator(self.mock_hardware, date_range=date_range)

        state = stimulator.get_stimulator_state()
        self.assertEqual(state, "inactive")

    def test_get_stimulator_state_scheduled(self):
        """Test get_stimulator_state returns 'scheduled' when in range but not stimulating."""
        # Create date range covering now
        now = time.time()
        start_time = now - 3600
        end_time = now + 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        stimulator = DefaultStimulator(self.mock_hardware, date_range=date_range)

        state = stimulator.get_stimulator_state()
        self.assertEqual(state, "scheduled")

    def test_get_stimulator_state_stimulating(self):
        """Test get_stimulator_state returns 'stimulating' during recent interaction."""

        class TestStimulator(BaseStimulator):
            def _decide(self):
                return HasInteractedVariable(True), {"test": "value"}

        # Create date range covering now
        now = time.time()
        start_time = now - 3600
        end_time = now + 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
        date_range = f"{start_str} > {end_str}"

        stimulator = TestStimulator(self.mock_hardware, date_range=date_range)
        stimulator.bind_tracker(self.mock_tracker)

        # Trigger an interaction
        stimulator.apply()

        # Check state immediately after interaction
        state = stimulator.get_stimulator_state()
        self.assertEqual(state, "stimulating")

    def test_track_interaction_state(self):
        """Test _track_interaction_state updates internal tracking."""
        stimulator = DefaultStimulator(self.mock_hardware)
        stimulator.bind_tracker(self.mock_tracker)

        current_time = time.time() * 1000
        stimulator._track_interaction_state(True, current_time)

        self.assertEqual(stimulator._last_interaction_time, current_time)
        self.assertEqual(stimulator._last_interaction_value, 1)

        # Test with False
        stimulator._track_interaction_state(False, current_time + 1000)
        self.assertEqual(stimulator._last_interaction_time, current_time + 1000)
        self.assertEqual(stimulator._last_interaction_value, 0)


class TestTemplateOverrides(unittest.TestCase):
    """Test suite for ROI template override functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware = Mock()

    def test_no_template_config(self):
        """Test stimulator works without template config."""
        stimulator = DefaultStimulator(self.mock_hardware, roi_template_config=None)
        self.assertIsNotNone(stimulator)

    def test_empty_template_config(self):
        """Test stimulator works with empty template config."""
        template_config = {}
        stimulator = DefaultStimulator(
            self.mock_hardware, roi_template_config=template_config
        )
        self.assertIsNotNone(stimulator)

    def test_template_config_no_stimulator_compatibility(self):
        """Test template config without stimulator_compatibility section."""
        template_config = {"other_data": "value"}
        stimulator = DefaultStimulator(
            self.mock_hardware, roi_template_config=template_config
        )
        self.assertIsNotNone(stimulator)

    def test_simple_roi_mapping(self):
        """Test simple ROI to channel mapping."""
        template_config = {
            "stimulator_compatibility": {
                "roi_mappings": {"DefaultStimulator": {"1": 10, "2": 20, "3": 30}}
            }
        }

        stimulator = DefaultStimulator(
            self.mock_hardware, roi_template_config=template_config
        )

        # Check mapping was applied (keys converted to int)
        self.assertTrue(hasattr(stimulator, "_roi_to_channel"))
        self.assertEqual(stimulator._roi_to_channel[1], 10)
        self.assertEqual(stimulator._roi_to_channel[2], 20)
        self.assertEqual(stimulator._roi_to_channel[3], 30)

    def test_default_roi_mapping(self):
        """Test default ROI mapping when stimulator not specified."""
        template_config = {
            "stimulator_compatibility": {"roi_mappings": {"default": {"1": 5, "2": 15}}}
        }

        stimulator = DefaultStimulator(
            self.mock_hardware, roi_template_config=template_config
        )

        # Should use default mapping
        self.assertTrue(hasattr(stimulator, "_roi_to_channel"))
        self.assertEqual(stimulator._roi_to_channel[1], 5)
        self.assertEqual(stimulator._roi_to_channel[2], 15)

    def test_motor_valve_channels_mapping(self):
        """Test complex mapping with motor and valve channels."""

        class ComplexStimulator(BaseStimulator):
            def _decide(self):
                return HasInteractedVariable(False), {}

        template_config = {
            "stimulator_compatibility": {
                "roi_mappings": {
                    "ComplexStimulator": {
                        "motor_channels": {"1": 10, "2": 11},
                        "valve_channels": {"1": 20, "2": 21},
                    }
                }
            }
        }

        stimulator = ComplexStimulator(
            self.mock_hardware, roi_template_config=template_config
        )

        # Check both mappings were applied
        self.assertTrue(hasattr(stimulator, "_roi_to_channel_motor"))
        self.assertTrue(hasattr(stimulator, "_roi_to_channel_valves"))
        self.assertEqual(stimulator._roi_to_channel_motor[1], 10)
        self.assertEqual(stimulator._roi_to_channel_motor[2], 11)
        self.assertEqual(stimulator._roi_to_channel_valves[1], 20)
        self.assertEqual(stimulator._roi_to_channel_valves[2], 21)

    def test_roi_mapping_string_key_conversion(self):
        """Test that string keys in mappings are converted to integers."""
        template_config = {
            "stimulator_compatibility": {
                "roi_mappings": {"DefaultStimulator": {"1": 100, "10": 200, "100": 300}}
            }
        }

        stimulator = DefaultStimulator(
            self.mock_hardware, roi_template_config=template_config
        )

        # All keys should be integers
        self.assertIn(1, stimulator._roi_to_channel)
        self.assertIn(10, stimulator._roi_to_channel)
        self.assertIn(100, stimulator._roi_to_channel)
        self.assertNotIn("1", stimulator._roi_to_channel)


if __name__ == "__main__":
    unittest.main()
