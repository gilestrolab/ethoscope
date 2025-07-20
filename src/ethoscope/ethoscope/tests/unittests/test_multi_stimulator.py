import unittest
import time
from unittest.mock import Mock, MagicMock

from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.stimulators import DefaultStimulator, HasInteractedVariable


class TestMultiStimulator(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hardware_connection = Mock()
        
    def test_init_empty_sequence(self):
        """Test initialization with empty stimulator sequence."""
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=[]
        )
        
        self.assertEqual(len(multi_stim._stimulators), 0)
        self.assertEqual(multi_stim.get_active_stimulators(), [])
        
    def test_init_with_default_stimulator(self):
        """Test initialization with DefaultStimulator."""
        current_time = time.time()
        future_time = current_time + 3600  # 1 hour from now
        
        # Create date range that is currently active
        date_range = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>" \
                     f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        
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
        
        self.assertEqual(len(multi_stim._stimulators), 1)
        self.assertEqual(multi_stim._stimulators[0]['class_name'], 'DefaultStimulator')
        
    def test_decide_no_active_stimulators(self):
        """Test _decide when no stimulators are active."""
        # Create stimulator with date range in the past
        past_time = time.time() - 7200  # 2 hours ago
        past_end = past_time + 3600     # 1 hour ago
        
        date_range = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_time))}>" \
                     f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(past_end))}"
        
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
        date_range = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>" \
                     f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        
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
        
        # Mock tracker
        mock_tracker = Mock()
        multi_stim.bind_tracker(mock_tracker)
        
        interaction, result = multi_stim._decide()
        
        self.assertIsInstance(interaction, HasInteractedVariable)
        # DefaultStimulator should return False for interaction
        self.assertEqual(bool(interaction), False)
        self.assertIn('active_stimulator', result)
        self.assertEqual(result['active_stimulator'], 'DefaultStimulator')
        
    def test_get_stimulator_info(self):
        """Test get_stimulator_info method."""
        current_time = time.time()
        future_time = current_time + 3600
        
        date_range = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time - 60))}>" \
                     f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(future_time))}"
        
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
        
        info = multi_stim.get_stimulator_info()
        
        self.assertEqual(len(info), 1)
        self.assertEqual(info[0]['class_name'], 'DefaultStimulator')
        self.assertEqual(info[0]['date_range'], date_range)
        self.assertTrue(info[0]['is_active'])
        
    def test_bind_tracker(self):
        """Test that bind_tracker calls bind_tracker on all sub-stimulators."""
        sequence = [
            {
                "class_name": "DefaultStimulator",
                "arguments": {},
                "date_range": ""
            }
        ]
        
        multi_stim = MultiStimulator(
            hardware_connection=self.mock_hardware_connection,
            stimulator_sequence=sequence
        )
        
        # Mock the individual stimulator's bind_tracker method
        mock_tracker = Mock()
        multi_stim._stimulators[0]['instance'].bind_tracker = Mock()
        
        multi_stim.bind_tracker(mock_tracker)
        
        # Verify bind_tracker was called on the sub-stimulator
        multi_stim._stimulators[0]['instance'].bind_tracker.assert_called_once_with(mock_tracker)


if __name__ == '__main__':
    unittest.main()