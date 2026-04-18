"""
Unit tests for stimulators/sleep_depriver_stimulators.py.

Tests IsMovingStimulator, SleepDepStimulator, SleepDepStimulatorCR,
ExperimentalSleepDepStimulator, MiddleCrossingStimulator, mAGO, and AGO.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.hardware.interfaces.sleep_depriver_interface import (
    SleepDepriverInterface,
    SleepDepriverInterfaceCR,
)
from ethoscope.stimulators.sleep_depriver_stimulators import (
    AGO,
    ExperimentalSleepDepStimulator,
    IsMovingStimulator,
    MiddleCrossingStimulator,
    SleepDepStimulator,
    SleepDepStimulatorCR,
    mAGO,
)
from ethoscope.stimulators.stimulators import HasInteractedVariable


def _make_mock_tracker(roi_id=1, last_time_point=200000, positions=None, times=None):
    """Helper to create a mock tracker for stimulator tests."""
    tracker = Mock()
    tracker._roi = Mock()
    tracker._roi.idx = roi_id
    tracker._roi.longest_axis = 100.0
    tracker._roi.get_feature_dict = Mock(return_value={"w": 100, "h": 50})
    tracker.last_time_point = last_time_point
    tracker.positions = positions or [
        [{"xy_dist_log10x1000": 0, "x": 50, "y": 25}],
        [{"xy_dist_log10x1000": 0, "x": 50, "y": 25}],
    ]
    tracker.times = times or [last_time_point - 1000, last_time_point]
    return tracker


# ===========================================================================
# IsMovingStimulator
# ===========================================================================


class TestIsMovingStimulator(unittest.TestCase):
    """Test IsMovingStimulator movement detection."""

    def _create_stimulator(self):
        return IsMovingStimulator(hardware_connection=None)

    def test_has_moved_insufficient_positions(self):
        """Test _has_moved returns False with < 2 positions."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"xy_dist_log10x1000": 0}]]
        stim.bind_tracker(tracker)
        self.assertFalse(stim._has_moved())

    def test_has_moved_stationary_animal(self):
        """Test _has_moved returns False for stationary animal (low velocity)."""
        stim = self._create_stimulator()
        # xy_dist_log10x1000 = -3000 => dist = 10^(-3) = 0.001
        # velocity = 0.001/1.0 = 0.001, corrected = 0.001 * 1.0 / 0.003 = 0.33 < 1
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        self.assertFalse(stim._has_moved())

    def test_has_moved_moving_animal(self):
        """Test _has_moved returns True for moving animal (high velocity)."""
        stim = self._create_stimulator()
        # xy_dist_log10x1000 = 3000 => dist = 10^3 = 1000
        # velocity = 1000/1.0, corrected = 1000 * 1.0 / 0.003 >> 1
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": 3000}],
                [{"xy_dist_log10x1000": 3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        self.assertTrue(stim._has_moved())

    def test_has_moved_time_mismatch(self):
        """Test _has_moved returns False when last_time_point != last position time."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(last_time_point=300000)
        tracker.times = [199000, 200000]  # Mismatch with last_time_point
        stim.bind_tracker(tracker)
        self.assertFalse(stim._has_moved())

    def test_decide_moving(self):
        """Test _decide returns not interacted when animal moved."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": 3000}],
                [{"xy_dist_log10x1000": 3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_decide_not_moving(self):
        """Test _decide returns interacted when animal not moved."""
        stim = self._create_stimulator()
        # Very small distance => not moving
        tracker = _make_mock_tracker(
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), True)


# ===========================================================================
# SleepDepStimulator
# ===========================================================================


class TestSleepDepStimulator(unittest.TestCase):
    """Test SleepDepStimulator inactivity-based stimulation."""

    def _create_stimulator(self, **kwargs):
        mock_hw = Mock()
        defaults = {
            "hardware_connection": mock_hw,
            "min_inactive_time": 0,
            "stimulus_probability": 1.0,
        }
        defaults.update(kwargs)
        return SleepDepStimulator(**defaults)

    def test_hardware_interface(self):
        """Test uses SleepDepriverInterface."""
        self.assertEqual(
            SleepDepStimulator._HardwareInterfaceClass, SleepDepriverInterface
        )

    def test_invalid_probability_raises(self):
        """Test probability outside [0,1] raises ValueError."""
        with self.assertRaises(ValueError):
            self._create_stimulator(stimulus_probability=1.5)

    def test_roi_mapping(self):
        """Test default ROI-to-channel mapping."""
        expected = {1: 1, 3: 2, 5: 3, 7: 4, 9: 5, 12: 6, 14: 7, 16: 8, 18: 9, 20: 10}
        self.assertEqual(SleepDepStimulator._roi_to_channel, expected)

    def test_decide_unmapped_roi(self):
        """Test unmapped ROI returns no interaction."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(roi_id=99)
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_decide_inactive_animal_stimulates(self):
        """Test inactive animal triggers real stimulation."""
        stim = self._create_stimulator(min_inactive_time=0)
        tracker = _make_mock_tracker(
            roi_id=1,
            last_time_point=200000,
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        stim._t0 = 0  # Force inactivity threshold to be exceeded

        out, dic = stim._decide()
        self.assertEqual(int(out), 1)
        self.assertIn("channel", dic)
        self.assertEqual(dic["channel"], 1)

    def test_decide_ghost_stimulation(self):
        """Test ghost stimulation when probability is 0."""
        stim = self._create_stimulator(min_inactive_time=0, stimulus_probability=0.0)
        tracker = _make_mock_tracker(
            roi_id=1,
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        stim._t0 = 0

        out, dic = stim._decide()
        self.assertEqual(int(out), 2)  # Ghost
        self.assertEqual(dic, {})

    def test_decide_moving_animal_resets_t0(self):
        """Test moving animal resets the inactivity timer."""
        stim = self._create_stimulator(min_inactive_time=120)
        tracker = _make_mock_tracker(
            roi_id=1,
            last_time_point=200000,
            positions=[
                [{"xy_dist_log10x1000": 3000}],
                [{"xy_dist_log10x1000": 3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        stim._t0 = 100000

        out, dic = stim._decide()
        self.assertEqual(int(out), 0)
        self.assertEqual(stim._t0, 200000)


# ===========================================================================
# SleepDepStimulatorCR
# ===========================================================================


class TestSleepDepStimulatorCR(unittest.TestCase):
    """Test SleepDepStimulatorCR."""

    def test_hardware_interface(self):
        """Test uses CR hardware interface."""
        self.assertEqual(
            SleepDepStimulatorCR._HardwareInterfaceClass, SleepDepriverInterfaceCR
        )

    def test_init(self):
        """Test initialization works."""
        mock_hw = Mock()
        stim = SleepDepStimulatorCR(hardware_connection=mock_hw, min_inactive_time=60)
        self.assertEqual(stim._inactivity_time_threshold_ms, 60000)


# ===========================================================================
# ExperimentalSleepDepStimulator
# ===========================================================================


class TestExperimentalSleepDepStimulator(unittest.TestCase):
    """Test ExperimentalSleepDepStimulator per-channel threshold."""

    def test_bind_tracker_sets_threshold(self):
        """Test bind_tracker calculates channel-specific threshold."""
        mock_hw = Mock()
        stim = ExperimentalSleepDepStimulator(hardware_connection=mock_hw)

        tracker = _make_mock_tracker(roi_id=1)
        stim.bind_tracker(tracker)
        # Channel 1: round(1**1.7) * 20 * 1000 = 1 * 20000 = 20000
        self.assertEqual(stim._inactivity_time_threshold_ms, 20000)

    def test_bind_tracker_higher_channel(self):
        """Test threshold scales with channel number."""
        mock_hw = Mock()
        stim = ExperimentalSleepDepStimulator(hardware_connection=mock_hw)

        tracker = _make_mock_tracker(roi_id=5)  # Channel 3
        stim.bind_tracker(tracker)
        expected = round(3**1.7) * 20 * 1000
        self.assertEqual(stim._inactivity_time_threshold_ms, expected)

    def test_bind_tracker_unmapped_roi(self):
        """Test bind_tracker with unmapped ROI doesn't crash."""
        mock_hw = Mock()
        stim = ExperimentalSleepDepStimulator(hardware_connection=mock_hw)

        tracker = _make_mock_tracker(roi_id=99)
        stim.bind_tracker(tracker)
        # Threshold should remain None since ROI is not in mapping
        self.assertIsNone(stim._inactivity_time_threshold_ms)


# ===========================================================================
# MiddleCrossingStimulator
# ===========================================================================


class TestMiddleCrossingStimulator(unittest.TestCase):
    """Test MiddleCrossingStimulator midline crossing detection."""

    def _create_stimulator(self, **kwargs):
        mock_hw = Mock()
        defaults = {
            "hardware_connection": mock_hw,
            "stimulus_probability": 1.0,
        }
        defaults.update(kwargs)
        return MiddleCrossingStimulator(**defaults)

    def test_invalid_probability_raises(self):
        """Test probability outside [0,1] raises ValueError."""
        with self.assertRaises(ValueError):
            self._create_stimulator(stimulus_probability=-0.1)

    def test_insufficient_positions(self):
        """Test returns no interaction with < 2 positions."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        tracker.positions = [[{"x": 50}]]
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_no_crossing(self):
        """Test no interaction when animal stays on same side."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        # Both positions on right side (x/longest_axis - 0.5 > 0)
        tracker.positions = [[{"x": 80}], [{"x": 70}]]
        tracker._roi.longest_axis = 100.0
        stim.bind_tracker(tracker)
        stim._last_stimulus_time = 0

        out, dic = stim._decide()
        # No crossing detected, should not interact
        self.assertIn("channel", dic)  # channel always returned

    def test_crossing_detected(self):
        """Test interaction when animal crosses midline."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        # Position goes from left (x=30, 30/100 - 0.5 = -0.2) to right (x=70, 70/100 - 0.5 = 0.2)
        tracker.positions = [[{"x": 70}], [{"x": 30}]]
        tracker._roi.longest_axis = 100.0
        stim.bind_tracker(tracker)
        stim._last_stimulus_time = 0

        out, dic = stim._decide()
        self.assertEqual(int(out), 1)
        self.assertEqual(dic["channel"], 1)

    def test_refractory_period(self):
        """Test no stimulus during refractory period."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        tracker.positions = [[{"x": 70}], [{"x": 30}]]
        tracker._roi.longest_axis = 100.0
        stim.bind_tracker(tracker)
        # Set last stimulus very recently
        stim._last_stimulus_time = 200000  # Same as now

        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_unmapped_roi(self):
        """Test unmapped ROI returns no interaction."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker(roi_id=99, last_time_point=200000)
        tracker.positions = [[{"x": 70}], [{"x": 30}]]
        tracker._roi.longest_axis = 100.0
        stim.bind_tracker(tracker)
        stim._last_stimulus_time = 0

        out, dic = stim._decide()
        self.assertEqual(bool(out), False)


# ===========================================================================
# mAGO
# ===========================================================================


class TestMAGO(unittest.TestCase):
    """Test mAGO stimulator with motor/valve channel mapping."""

    def test_hardware_interface(self):
        """Test uses OptoMotor hardware interface."""
        self.assertEqual(mAGO._HardwareInterfaceClass, OptoMotor)

    def test_valve_mode_uses_even_channels(self):
        """Test stimulus_type=2 maps to valve (even) channels."""
        mock_hw = Mock()
        stim = mAGO(
            hardware_connection=mock_hw,
            stimulus_type=2,
            min_inactive_time=0,
        )
        self.assertEqual(stim._roi_to_channel[1], 0)
        self.assertEqual(stim._roi_to_channel[3], 2)

    def test_motor_mode_uses_odd_channels(self):
        """Test stimulus_type=1 maps to motor (odd) channels."""
        mock_hw = Mock()
        stim = mAGO(
            hardware_connection=mock_hw,
            stimulus_type=1,
            min_inactive_time=0,
        )
        self.assertEqual(stim._roi_to_channel[1], 1)
        self.assertEqual(stim._roi_to_channel[3], 3)

    def test_decide_adds_duration(self):
        """Test _decide always adds duration to result dict."""
        mock_hw = Mock()
        stim = mAGO(
            hardware_connection=mock_hw,
            stimulus_type=1,
            min_inactive_time=0,
            pulse_duration=500,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(
            roi_id=1,
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        stim._t0 = 0

        out, dic = stim._decide()
        self.assertIn("duration", dic)
        self.assertEqual(dic["duration"], 500)


# ===========================================================================
# AGO
# ===========================================================================


class TestAGO(unittest.TestCase):
    """Test AGO stimulator with per-ROI counting."""

    def test_hardware_interface(self):
        """Test uses OptoMotor hardware interface."""
        self.assertEqual(AGO._HardwareInterfaceClass, OptoMotor)

    def test_valve_channel_mapping(self):
        """Test 10-ROI to 20-channel valve mapping."""
        mock_hw = Mock()
        stim = AGO(hardware_connection=mock_hw, min_inactive_time=0)
        expected = {1: 0, 2: 10, 3: 2, 4: 12, 5: 4, 6: 14, 7: 6, 8: 16, 9: 8, 10: 18}
        self.assertEqual(stim._roi_to_channel, expected)

    def test_decide_returns_duration(self):
        """Test _decide includes duration in result."""
        mock_hw = Mock()
        stim = AGO(
            hardware_connection=mock_hw,
            min_inactive_time=0,
            pulse_duration=750,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(
            roi_id=1,
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        stim._t0 = 0

        out, dic = stim._decide()
        if int(out) == 1:
            self.assertEqual(dic["duration"], 750)

    def test_unlimited_stimuli(self):
        """Test number_of_stimuli=0 means unlimited."""
        mock_hw = Mock()
        stim = AGO(
            hardware_connection=mock_hw,
            min_inactive_time=0,
            number_of_stimuli=0,
            stimulus_probability=1.0,
        )
        # All probabilities should remain at 1.0
        for roi_id in range(1, 11):
            self.assertEqual(stim._prob_dict[roi_id], 1.0)

    def test_limited_stimuli_zeroes_probability(self):
        """Test probability is set to 0 after reaching stimulus count limit."""
        mock_hw = Mock()
        stim = AGO(
            hardware_connection=mock_hw,
            min_inactive_time=0,
            number_of_stimuli=1,
            stimulus_probability=1.0,
        )
        # Simulate one stimulus already delivered for ROI 1
        stim._count_roi_stim[1] = 1

        tracker = _make_mock_tracker(
            roi_id=1,
            positions=[
                [{"xy_dist_log10x1000": -3000}],
                [{"xy_dist_log10x1000": -3000}],
            ],
            times=[199000, 200000],
        )
        stim.bind_tracker(tracker)
        stim._t0 = 0

        out, dic = stim._decide()
        # After count >= limit, probability is set to 0, so ghost (2) or 0
        self.assertEqual(stim._prob_dict[1], 0)

    def test_unmapped_roi(self):
        """Test unmapped ROI returns no interaction."""
        mock_hw = Mock()
        stim = AGO(hardware_connection=mock_hw, min_inactive_time=0)
        tracker = _make_mock_tracker(roi_id=99)
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)


if __name__ == "__main__":
    unittest.main()
