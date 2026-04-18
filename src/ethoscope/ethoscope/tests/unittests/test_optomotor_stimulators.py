"""
Unit tests for stimulators/optomotor_stimulators.py.

Tests OptoMidlineCrossStimulator class.
"""

import unittest
from unittest.mock import Mock

from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator
from ethoscope.stimulators.stimulators import HasInteractedVariable


class TestOptoMidlineCrossStimulator(unittest.TestCase):
    """Test OptoMidlineCrossStimulator."""

    def test_uses_optomotor_hardware(self):
        """Test it uses OptoMotor hardware interface."""
        self.assertEqual(OptoMidlineCrossStimulator._HardwareInterfaceClass, OptoMotor)

    def test_even_channel_mapping(self):
        """Test ROIs map to even LED channels."""
        expected = {
            1: 0,
            3: 2,
            5: 4,
            7: 6,
            9: 8,
            12: 10,
            14: 12,
            16: 14,
            18: 16,
            20: 18,
        }
        self.assertEqual(OptoMidlineCrossStimulator._roi_to_channel, expected)

    def test_all_channels_are_even(self):
        """Test all mapped channels are even numbers."""
        for roi_id, channel in OptoMidlineCrossStimulator._roi_to_channel.items():
            self.assertEqual(
                channel % 2, 0, f"ROI {roi_id} maps to odd channel {channel}"
            )

    def test_description_structure(self):
        """Test _description has correct structure."""
        desc = OptoMidlineCrossStimulator._description
        self.assertIn("overview", desc)
        self.assertIn("arguments", desc)
        arg_names = [a["name"] for a in desc["arguments"]]
        self.assertIn("stimulus_probability", arg_names)

    def test_init_and_decide(self):
        """Test initialization and basic _decide behavior."""
        mock_hw = Mock()
        stim = OptoMidlineCrossStimulator(
            hardware_connection=mock_hw,
            stimulus_probability=1.0,
        )

        # Set up tracker mock with insufficient positions
        tracker = Mock()
        tracker._roi = Mock()
        tracker._roi.idx = 1
        tracker.last_time_point = 100000
        tracker.positions = []  # Not enough positions

        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_unmapped_roi(self):
        """Test unmapped ROI returns no interaction."""
        mock_hw = Mock()
        stim = OptoMidlineCrossStimulator(
            hardware_connection=mock_hw,
            stimulus_probability=1.0,
        )

        tracker = Mock()
        tracker._roi = Mock()
        tracker._roi.idx = 99  # Not in mapping
        tracker.last_time_point = 100000
        tracker.positions = [[{"x": 50}], [{"x": 60}]]
        tracker._roi.longest_axis = 100.0

        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)


if __name__ == "__main__":
    unittest.main()
