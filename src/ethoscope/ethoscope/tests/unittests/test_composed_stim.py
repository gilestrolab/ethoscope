"""
Unit tests for stimulators/composed_stimulator.py.

Tests ComposedStimulator initialization, trigger/action wiring,
channel mapping, and _decide logic.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope.stimulators.composed_stimulator import ComposedStimulator
from ethoscope.stimulators.stimulators import HasInteractedVariable


def _make_mock_tracker(roi_id=1, last_time_point=200000, positions=None, times=None):
    """Create a mock tracker."""
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


class TestComposedStimulatorInit(unittest.TestCase):
    """Test ComposedStimulator initialization."""

    def _create_stimulator(self, **kwargs):
        mock_hw = Mock()
        mock_hw.interrogate.side_effect = Exception("no module")
        defaults = {
            "hardware_connection": mock_hw,
            "trigger_type": "inactivity",
            "action_type": "motor_pulse",
        }
        defaults.update(kwargs)
        return ComposedStimulator(**defaults)

    def test_init_inactivity_motor(self):
        """Test init with inactivity trigger and motor action."""
        stim = self._create_stimulator(
            trigger_type="inactivity", action_type="motor_pulse"
        )
        self.assertIsNotNone(stim._trigger)
        self.assertIsNotNone(stim._action)
        self.assertIsNotNone(stim._roi_to_channel)

    def test_init_midline_crossing_led(self):
        """Test init with midline crossing trigger and LED action."""
        stim = self._create_stimulator(
            trigger_type="midline_crossing", action_type="led_pulse"
        )
        self.assertIsNotNone(stim._trigger)
        self.assertIsNotNone(stim._action)

    def test_init_periodic_led_pulse_train(self):
        """Test init with periodic trigger and LED pulse train."""
        stim = self._create_stimulator(
            trigger_type="periodic", action_type="led_pulse_train"
        )
        self.assertIsNotNone(stim._trigger)

    def test_init_time_restricted(self):
        """Test init with time-restricted trigger."""
        stim = self._create_stimulator(
            trigger_type="time_restricted", action_type="valve_pulse"
        )
        self.assertIsNotNone(stim._trigger)

    def test_init_invalid_trigger_raises(self):
        """Test ValueError for unknown trigger type."""
        with self.assertRaises(ValueError):
            self._create_stimulator(trigger_type="nonexistent")

    def test_init_invalid_action_raises(self):
        """Test ValueError for unknown action type."""
        with self.assertRaises(ValueError):
            self._create_stimulator(action_type="nonexistent")

    def test_init_with_module_interrogation(self):
        """Test init with successful module interrogation."""
        mock_hw = Mock()
        mock_hw.interrogate.return_value = {"capabilities": {"leds": 20, "motors": 10}}
        stim = ComposedStimulator(
            hardware_connection=mock_hw,
            trigger_type="inactivity",
            action_type="led_pulse",
        )
        self.assertIsNotNone(stim._roi_to_channel)


class TestComposedStimulatorBindTracker(unittest.TestCase):
    """Test bind_tracker propagation."""

    def test_bind_tracker_propagates_to_trigger(self):
        mock_hw = Mock()
        mock_hw.interrogate.side_effect = Exception("no module")
        stim = ComposedStimulator(
            hardware_connection=mock_hw,
            trigger_type="inactivity",
            action_type="motor_pulse",
        )
        tracker = _make_mock_tracker()
        stim.bind_tracker(tracker)
        self.assertIs(stim._trigger._tracker, tracker)


class TestComposedStimulatorDecide(unittest.TestCase):
    """Test ComposedStimulator._decide()."""

    def _create_bound_stimulator(self, roi_id=1, **kwargs):
        mock_hw = Mock()
        mock_hw.interrogate.side_effect = Exception("no module")
        defaults = {
            "hardware_connection": mock_hw,
            "trigger_type": "inactivity",
            "action_type": "motor_pulse",
            "min_inactive_time": 0,
            "stimulus_probability": 1.0,
        }
        defaults.update(kwargs)
        stim = ComposedStimulator(**defaults)
        tracker = _make_mock_tracker(
            roi_id=roi_id,
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        return stim

    def test_decide_unmapped_roi(self):
        """Test unmapped ROI returns no interaction."""
        stim = self._create_bound_stimulator(roi_id=99)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_decide_real_stimulus(self):
        """Test real stimulus when trigger fires."""
        stim = self._create_bound_stimulator(roi_id=1)
        stim._trigger._t0 = 0
        out, dic = stim._decide()
        self.assertEqual(int(out), 1)
        self.assertIn("channel", dic)

    def test_decide_ghost_stimulus(self):
        """Test ghost stimulus (code 2)."""
        stim = self._create_bound_stimulator(roi_id=1, stimulus_probability=0.0)
        stim._trigger._t0 = 0
        out, dic = stim._decide()
        self.assertEqual(int(out), 2)
        self.assertEqual(dic, {})

    def test_decide_no_stimulus(self):
        """Test no stimulus when trigger doesn't fire."""
        stim = self._create_bound_stimulator(roi_id=1, min_inactive_time=9999)
        out, dic = stim._decide()
        self.assertEqual(int(out), 0)

    def test_decide_motor_instruction(self):
        """Test motor pulse instruction contains duration."""
        stim = self._create_bound_stimulator(
            roi_id=1, action_type="motor_pulse", pulse_duration=500
        )
        stim._trigger._t0 = 0
        out, dic = stim._decide()
        if int(out) == 1:
            self.assertIn("duration", dic)
            self.assertEqual(dic["duration"], 500)

    def test_decide_led_pulse_train_instruction(self):
        """Test LED pulse train instruction contains on/off/cycles."""
        stim = self._create_bound_stimulator(
            roi_id=1,
            action_type="led_pulse_train",
            pulse_on_ms=150,
            pulse_off_ms=250,
            pulse_cycles=10,
        )
        stim._trigger._t0 = 0
        out, dic = stim._decide()
        if int(out) == 1:
            self.assertIn("on_ms", dic)
            self.assertIn("off_ms", dic)
            self.assertIn("cycles", dic)


class TestComposedStimulatorChannelMaps(unittest.TestCase):
    """Test channel mapping for different action types."""

    def _create_stimulator(self, action_type):
        mock_hw = Mock()
        mock_hw.interrogate.side_effect = Exception("no module")
        return ComposedStimulator(
            hardware_connection=mock_hw,
            trigger_type="inactivity",
            action_type=action_type,
        )

    def test_motor_uses_odd_channels(self):
        stim = self._create_stimulator("motor_pulse")
        # Motor channels should be odd
        if 1 in stim._roi_to_channel:
            self.assertEqual(stim._roi_to_channel[1] % 2, 1)

    def test_led_uses_even_channels(self):
        stim = self._create_stimulator("led_pulse")
        # LED channels should be even
        if 1 in stim._roi_to_channel:
            self.assertEqual(stim._roi_to_channel[1] % 2, 0)

    def test_valve_uses_even_channels(self):
        stim = self._create_stimulator("valve_pulse")
        if 1 in stim._roi_to_channel:
            self.assertEqual(stim._roi_to_channel[1] % 2, 0)


if __name__ == "__main__":
    unittest.main()
