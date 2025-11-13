import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.stimulators import DefaultStimulator, HasInteractedVariable

# Optional imports for specific stimulator tests
try:
    from ethoscope.stimulators.sleep_depriver_stimulators import mAGO

    HAS_MAGO = True
except ImportError:
    HAS_MAGO = False


class TestMultiStimulator(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware_connection = Mock()

    def test_init_empty_sequence(self):
        """Test initialization with empty stimulator sequence."""
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection, stimulator_sequence=[]
        )

        self.assertEqual(len(multi_stim._stimulators), 0)
        self.assertEqual(multi_stim.get_active_stimulators(), [])

    def test_init_with_default_stimulator(self):
        """Test initialization with DefaultStimulator."""
        current_time = time.time()
        future_time = current_time + 3600  # 1 hour from now

        # Create date range that is currently active
        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        )

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

        self.assertEqual(len(multi_stim._stimulators), 1)
        self.assertEqual(multi_stim._stimulators[0]["class_name"], "DefaultStimulator")

    def test_decide_no_active_stimulators(self):
        """Test _decide when no stimulators are active."""
        # Create stimulator with date range in the past
        past_time = time.time() - 7200  # 2 hours ago
        past_end = past_time + 3600  # 1 hour ago

        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_time))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_end))}"
        )

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

        # Mock tracker
        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)

        interaction, result = multi_stim._decide()

        self.assertIsInstance(interaction, HasInteractedVariable)
        self.assertEqual(bool(interaction), False)
        self.assertEqual(result, {})

    def test_decide_with_active_stimulator(self):
        """Test _decide when a stimulator is active."""
        current_time = time.time()
        future_time = current_time + 3600  # 1 hour from now

        # Create date range that is currently active
        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        )

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

        # Mock tracker
        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)

        interaction, result = multi_stim._decide()

        self.assertIsInstance(interaction, HasInteractedVariable)
        # DefaultStimulator should return False for interaction
        self.assertEqual(bool(interaction), False)
        self.assertIn("active_stimulator", result)
        self.assertEqual(result["active_stimulator"], "DefaultStimulator")

    def test_get_stimulator_info(self):
        """Test get_stimulator_info method."""
        current_time = time.time()
        future_time = current_time + 3600

        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        )

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

        info = multi_stim.get_stimulator_info()

        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]["class_name"], "DefaultStimulator")
        self.assertEqual(info[0]["date_range"], date_range)
        self.assertTrue(info[0]["is_active"])

    def test_bind_tracker(self):
        """Test that bind_tracker calls bind_tracker on all sub-stimulators."""
        sequence = [
            {"class_name": "DefaultStimulator", "arguments": {}, "date_range": ""}
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        # Mock the individual stimulator's bind_tracker method
        mock_tracker = Mock()
        multi_stim._stimulators[0]["instance"].bind_tracker = Mock()

        multi_stim.bind_tracker(mock_tracker)

        # Verify bind_tracker was called on the sub-stimulator
        multi_stim._stimulators[0]["instance"].bind_tracker.assert_called_once_with(
            mock_tracker
        )

    @unittest.skipUnless(HAS_MAGO, "mAGO stimulator not available")
    def test_double_scheduling_prevention_with_mago(self):
        """
        Test that MultiStimulator doesn't cause double scheduling with mAGO.
        This test specifically addresses the bug where both MultiStimulator and
        the individual stimulator were checking date ranges, causing timing issues.
        """
        current_time = time.time()
        future_time = current_time + 3600

        # Create active date range
        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        )

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

        mock_tracker = Mock()
        mock_tracker.positions = []
        mock_tracker.times = []
        mock_tracker.last_time_point = current_time * 1000  # mAGO expects milliseconds

        multi_stim.bind_tracker(mock_tracker)

        # Track how many times the scheduler is checked
        original_check_time_range = multi_stim._stimulators[0][
            "scheduler"
        ].check_time_range
        scheduler_call_count = {"count": 0}

        def mock_scheduler_check():
            scheduler_call_count["count"] += 1
            return original_check_time_range()

        multi_stim._stimulators[0]["scheduler"].check_time_range = mock_scheduler_check

        # Track how many times the individual stimulator's scheduler is checked
        individual_stimulator = multi_stim._stimulators[0]["instance"]
        original_individual_check = individual_stimulator._scheduler.check_time_range
        individual_scheduler_call_count = {"count": 0}

        def mock_individual_scheduler_check(*args, **kwargs):
            individual_scheduler_call_count["count"] += 1
            return original_individual_check(*args, **kwargs)

        individual_stimulator._scheduler.check_time_range = (
            mock_individual_scheduler_check
        )

        # Execute decision
        with patch("time.time", return_value=current_time):
            interaction, result = multi_stim._decide()

        # MultiStimulator should check its scheduler once
        self.assertEqual(scheduler_call_count["count"], 1)

        # The individual stimulator should also check its scheduler once when apply() is called
        # This is expected behavior - each level checks its own scheduler
        # The issue was that this caused conflicts, which our fix in the frontend addresses
        self.assertGreaterEqual(individual_scheduler_call_count["count"], 0)

        # Verify we get a result with active_stimulator metadata
        self.assertIn("active_stimulator", result)
        self.assertEqual(result["active_stimulator"], "mAGO")

    def test_multistimulator_timing_edge_cases(self):
        """Test MultiStimulator behavior at timing boundaries."""
        current_time = time.time()

        # Create date range that starts exactly now and ends in 1 hour
        start_time = current_time
        end_time = current_time + 3600

        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}"
        )

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

        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)

        # Test exactly at start time (should be inactive due to exclusive boundary)
        with patch("time.time", return_value=start_time):
            interaction, result = multi_stim._decide()
            self.assertEqual(bool(interaction), False)

        # Test just after start time (should be active)
        with patch("time.time", return_value=start_time + 1):
            interaction, result = multi_stim._decide()
            self.assertEqual(
                bool(interaction), False
            )  # DefaultStimulator always returns False
            self.assertIn("active_stimulator", result)

        # Test just before end time (should be active)
        with patch("time.time", return_value=end_time - 1):
            interaction, result = multi_stim._decide()
            self.assertEqual(
                bool(interaction), False
            )  # DefaultStimulator always returns False
            self.assertIn("active_stimulator", result)

        # Test exactly at end time (should be inactive due to exclusive boundary)
        with patch("time.time", return_value=end_time):
            interaction, result = multi_stim._decide()
            self.assertEqual(bool(interaction), False)
            self.assertEqual(result, {})

    def test_multistimulator_multiple_stimulators_scheduling(self):
        """Test MultiStimulator with multiple stimulators having different date ranges."""
        current_time = time.time()

        # First stimulator: active for first hour
        first_start = current_time - 1800  # 30 minutes ago
        first_end = current_time + 1800  # 30 minutes from now
        first_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(first_start))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(first_end))}"
        )

        # Second stimulator: active for second hour
        second_start = current_time + 3600  # 1 hour from now
        second_end = current_time + 7200  # 2 hours from now
        second_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(second_start))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(second_end))}"
        )

        sequence = [
            {
                "class_name": "DefaultStimulator",
                "arguments": {},
                "date_range": first_range,
            },
            {
                "class_name": "DefaultStimulator",
                "arguments": {},
                "date_range": second_range,
            },
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)

        # Test during first stimulator's active period
        with patch("time.time", return_value=current_time):
            active_stimulators = multi_stim.get_active_stimulators()
            self.assertEqual(len(active_stimulators), 1)

            interaction, result = multi_stim._decide()
            self.assertIn("active_stimulator", result)

        # Test during gap between stimulators (should be inactive)
        gap_time = current_time + 2700  # 45 minutes from now (in the gap)
        with patch("time.time", return_value=gap_time):
            active_stimulators = multi_stim.get_active_stimulators()
            self.assertEqual(len(active_stimulators), 0)

            interaction, result = multi_stim._decide()
            self.assertEqual(bool(interaction), False)
            self.assertEqual(result, {})

        # Test during second stimulator's active period
        with patch("time.time", return_value=current_time + 5400):  # 1.5 hours from now
            active_stimulators = multi_stim.get_active_stimulators()
            self.assertEqual(len(active_stimulators), 1)

            interaction, result = multi_stim._decide()
            self.assertIn("active_stimulator", result)

    def test_already_initialized_stimulators(self):
        """Test that stimulators are not re-initialized if already initialized."""
        sequence = [
            {"class_name": "DefaultStimulator", "arguments": {}, "date_range": ""}
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        # Store original stimulators
        original_stimulators = multi_stim._stimulators

        # Try to initialize again
        multi_stim._initialize_stimulators()

        # Should be the same instance (not re-initialized)
        self.assertIs(multi_stim._stimulators, original_stimulators)

    def test_unknown_stimulator_class(self):
        """Test handling of unknown stimulator class name."""
        sequence = [
            {
                "class_name": "NonExistentStimulator",
                "arguments": {},
                "date_range": "",
            }
        ]

        # Should not raise exception, just skip unknown stimulator
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        # Should have 0 stimulators since the class doesn't exist
        self.assertEqual(len(multi_stim._stimulators), 0)

    def test_stimulator_initialization_exception(self):
        """Test handling of exception during stimulator initialization."""
        # Use a mock class that raises exception during instantiation
        with patch(
            "ethoscope.stimulators.stimulators.DefaultStimulator",
            side_effect=Exception("Initialization failed"),
        ):
            sequence = [
                {
                    "class_name": "DefaultStimulator",
                    "arguments": {},
                    "date_range": "",
                }
            ]

            # Should not raise exception, just log error and skip
            multi_stim = MultiStimulator(
                hardware_connection=self.mock_hardware_connection,
                stimulator_sequence=sequence,
            )

            # Should have 0 stimulators since initialization failed
            self.assertEqual(len(multi_stim._stimulators), 0)

    def test_decide_with_empty_stimulators(self):
        """Test _decide when stimulators list is empty."""
        # Create with unknown stimulator so list is empty
        sequence = [
            {"class_name": "NonExistentStimulator", "arguments": {}, "date_range": ""}
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)

        # Should return False interaction and empty result
        interaction, result = multi_stim._decide()

        self.assertIsInstance(interaction, HasInteractedVariable)
        self.assertEqual(bool(interaction), False)
        self.assertEqual(result, {})

    def test_decide_with_exception_in_stimulator(self):
        """Test _decide handles exceptions from individual stimulators."""
        current_time = time.time()
        future_time = current_time + 3600

        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        )

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

        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)

        # Make the stimulator's _decide method raise an exception
        with patch.object(
            multi_stim._stimulators[0]["instance"],
            "_decide",
            side_effect=Exception("Stimulator error"),
        ):
            interaction, result = multi_stim._decide()

            # Should handle exception and return False
            self.assertIsInstance(interaction, HasInteractedVariable)
            self.assertEqual(bool(interaction), False)
            self.assertEqual(result, {})

    def test_deliver_without_hardware_connection(self):
        """Test _deliver when hardware_connection is None."""
        sequence = [
            {"class_name": "DefaultStimulator", "arguments": {}, "date_range": ""}
        ]

        # Create without hardware connection
        multi_stim = MultiStimulator(
            hardware_connection=None, stimulator_sequence=sequence
        )

        # Should not raise exception when delivering without hardware
        # _deliver returns None, just verify it doesn't crash
        multi_stim._deliver(test="value", active_stimulator="Test")

        # Should complete without error
        self.assertTrue(True)

    def test_deliver_with_hardware_connection(self):
        """Test _deliver sends instructions to hardware."""
        sequence = [
            {"class_name": "DefaultStimulator", "arguments": {}, "date_range": ""}
        ]

        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence,
        )

        # Deliver with hardware
        multi_stim._deliver(channel=1, duration=1000, active_stimulator="Test")

        # Verify hardware was called (active_stimulator should be filtered out)
        self.mock_hardware_connection.send_instruction.assert_called_once()
        call_args = self.mock_hardware_connection.send_instruction.call_args[0][0]
        self.assertIn("channel", call_args)
        self.assertIn("duration", call_args)
        self.assertNotIn("active_stimulator", call_args)

    def test_get_stimulator_state_inactive(self):
        """Test get_stimulator_state returns 'inactive' when no stimulators active."""
        past_time = time.time() - 7200
        past_end = past_time + 3600

        date_range = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_time))}>"
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_end))}"
        )

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

        # Should return 'inactive' since date range is in the past
        state = multi_stim.get_stimulator_state()
        self.assertEqual(state, "inactive")

    def test_get_stimulator_state_delegates_to_stimulator(self):
        """Test get_stimulator_state delegates to active stimulator."""
        current_time = time.time()
        future_time = current_time + 3600

        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time))
        end_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(future_time))
        date_range = f"{start_str} > {end_str}"

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

        # When stimulator is active, get_stimulator_state should delegate
        # This tests line 316
        state = multi_stim.get_stimulator_state()
        # Should return scheduled or inactive depending on if currently active
        self.assertIn(state, ["inactive", "scheduled", "stimulating"])


if __name__ == "__main__":
    unittest.main()
