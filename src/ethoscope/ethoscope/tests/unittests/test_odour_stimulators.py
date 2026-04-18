"""
Unit tests for stimulators/odour_stimulators.py.

Tests HasChangedSideStimulator, DynamicOdourDeliverer,
DynamicOdourSleepDepriver, MiddleCrossingOdourStimulator,
and MiddleCrossingOdourStimulatorFlushed.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope.hardware.interfaces.odour_delivery_device import (
    OdourDelivererFlushedInterface,
    OdourDelivererInterface,
    OdourDepriverInterface,
)
from ethoscope.stimulators.odour_stimulators import (
    DynamicOdourDeliverer,
    DynamicOdourSleepDepriver,
    HasChangedSideStimulator,
    MiddleCrossingOdourStimulator,
    MiddleCrossingOdourStimulatorFlushed,
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
# HasChangedSideStimulator
# ===========================================================================


class TestHasChangedSideStimulator(unittest.TestCase):
    """Test HasChangedSideStimulator side-change detection."""

    def _create_stimulator(self, middle_line=0.5):
        return HasChangedSideStimulator(
            hardware_connection=None, middle_line=middle_line
        )

    def test_insufficient_positions(self):
        """Test returns False with < 2 positions."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"x": 50}]]
        stim.bind_tracker(tracker)
        self.assertFalse(stim._has_changed_side())

    def test_no_side_change(self):
        """Test returns 0 when animal stays on same side."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        # Both on right side: x/w = 70/100 = 0.7 > 0.5 and 60/100 = 0.6 > 0.5
        tracker.positions = [[{"x": 70}], [{"x": 60}]]
        stim.bind_tracker(tracker)
        self.assertEqual(stim._has_changed_side(), 0)

    def test_changed_side_left_to_right(self):
        """Test returns region number when animal crosses sides."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        # positions[-1] is current, positions[-2] is previous
        # Current on right (70/100=0.7 > 0.5), previous on left (30/100=0.3 < 0.5)
        tracker.positions = [[{"x": 30}], [{"x": 70}]]
        stim.bind_tracker(tracker)
        result = stim._has_changed_side()
        self.assertEqual(result, 2)  # Current region is right = 2

    def test_changed_side_right_to_left(self):
        """Test returns 1 when animal crosses from right to left."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        # Current on left, previous on right
        tracker.positions = [[{"x": 70}], [{"x": 30}]]
        stim.bind_tracker(tracker)
        result = stim._has_changed_side()
        self.assertEqual(result, 1)  # Current region is left = 1

    def test_custom_middle_line(self):
        """Test detection with non-default middle line."""
        stim = self._create_stimulator(middle_line=0.3)
        tracker = _make_mock_tracker()
        # With middle_line=0.3: current x=40/100=0.4 is right, previous x=20/100=0.2 is left
        tracker.positions = [[{"x": 20}], [{"x": 40}]]
        stim.bind_tracker(tracker)
        result = stim._has_changed_side()
        self.assertEqual(result, 2)  # Crossed to right

    def test_decide_no_change(self):
        """Test _decide returns not interacted when no side change."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"x": 70}], [{"x": 60}]]
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_decide_with_change(self):
        """Test _decide returns interacted when side changed."""
        stim = self._create_stimulator()
        tracker = _make_mock_tracker()
        tracker.positions = [[{"x": 70}], [{"x": 30}]]
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), True)


# ===========================================================================
# DynamicOdourDeliverer
# ===========================================================================


class TestDynamicOdourDeliverer(unittest.TestCase):
    """Test DynamicOdourDeliverer."""

    def test_hardware_interface(self):
        """Test uses OdourDelivererInterface."""
        self.assertEqual(
            DynamicOdourDeliverer._HardwareInterfaceClass, OdourDelivererInterface
        )

    def test_roi_to_channel_mapping(self):
        """Test 1:1 ROI to channel mapping."""
        expected = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10}
        self.assertEqual(DynamicOdourDeliverer._roi_to_channel, expected)

    def test_decide_no_change(self):
        """Test no interaction when animal doesn't change side."""
        mock_hw = Mock()
        stim = DynamicOdourDeliverer(hardware_connection=mock_hw)
        tracker = _make_mock_tracker(roi_id=1)
        tracker.positions = [[{"x": 70}], [{"x": 60}]]
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_decide_with_change(self):
        """Test interaction when animal changes side."""
        mock_hw = Mock()
        stim = DynamicOdourDeliverer(hardware_connection=mock_hw)
        tracker = _make_mock_tracker(roi_id=1)
        tracker.positions = [[{"x": 70}], [{"x": 30}]]
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertIn("channel", dic)
        self.assertIn("pos", dic)

    def test_decide_unmapped_roi(self):
        """Test unmapped ROI returns no interaction."""
        mock_hw = Mock()
        stim = DynamicOdourDeliverer(hardware_connection=mock_hw)
        tracker = _make_mock_tracker(roi_id=99)
        stim.bind_tracker(tracker)
        out, dic = stim._decide()
        self.assertEqual(bool(out), False)


# ===========================================================================
# DynamicOdourSleepDepriver
# ===========================================================================


class TestDynamicOdourSleepDepriver(unittest.TestCase):
    """Test DynamicOdourSleepDepriver adds stimulus_duration."""

    def test_hardware_interface(self):
        self.assertEqual(
            DynamicOdourSleepDepriver._HardwareInterfaceClass, OdourDepriverInterface
        )

    def test_decide_includes_stimulus_duration(self):
        """Test _decide always adds stimulus_duration to dict."""
        mock_hw = Mock()
        stim = DynamicOdourSleepDepriver(
            hardware_connection=mock_hw,
            min_inactive_time=0,
            stimulus_duration=5.0,
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
        self.assertIn("stimulus_duration", dic)
        self.assertEqual(dic["stimulus_duration"], 5.0)


# ===========================================================================
# MiddleCrossingOdourStimulator
# ===========================================================================


class TestMiddleCrossingOdourStimulator(unittest.TestCase):
    """Test MiddleCrossingOdourStimulator."""

    def test_hardware_interface(self):
        self.assertEqual(
            MiddleCrossingOdourStimulator._HardwareInterfaceClass,
            OdourDepriverInterface,
        )

    def test_roi_mapping(self):
        expected = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10}
        self.assertEqual(MiddleCrossingOdourStimulator._roi_to_channel, expected)

    def test_decide_includes_stimulus_duration(self):
        """Test _decide adds stimulus_duration when crossing detected."""
        mock_hw = Mock()
        stim = MiddleCrossingOdourStimulator(
            hardware_connection=mock_hw,
            stimulus_probability=1.0,
            refractory_period=0,
            stimulus_duration=7.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        # positions[-1] is current, [-2] is previous — need crossing
        tracker.positions = [[{"x": 30}], [{"x": 70}]]
        tracker._roi.longest_axis = 100.0
        stim.bind_tracker(tracker)
        stim._last_stimulus_time = 0

        out, dic = stim._decide()
        self.assertIn("stimulus_duration", dic)
        self.assertEqual(dic["stimulus_duration"], 7.0)


# ===========================================================================
# MiddleCrossingOdourStimulatorFlushed
# ===========================================================================


class TestMiddleCrossingOdourStimulatorFlushed(unittest.TestCase):
    """Test MiddleCrossingOdourStimulatorFlushed."""

    def test_hardware_interface(self):
        self.assertEqual(
            MiddleCrossingOdourStimulatorFlushed._HardwareInterfaceClass,
            OdourDelivererFlushedInterface,
        )

    def test_decide_includes_flush_duration(self):
        """Test flush_duration attribute is properly set.

        Note: MiddleCrossingOdourStimulatorFlushed has a pre-existing bug passing
        p= to parent which expects stimulus_probability=. We test attributes directly.
        """
        mock_hw = Mock()
        stim = MiddleCrossingOdourStimulatorFlushed(
            hardware_connection=mock_hw,
            stimulus_probability=1.0,
            refractory_period=0,
            stimulus_duration=5.0,
            flush_duration=10.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        tracker.positions = [[{"x": 30}], [{"x": 70}]]
        tracker._roi.longest_axis = 100.0
        stim.bind_tracker(tracker)
        stim._last_stimulus_time = 0

        out, dic = stim._decide()
        self.assertIn("stimulus_duration", dic)
        self.assertIn("flush_duration", dic)
        self.assertEqual(dic["stimulus_duration"], 5.0)
        self.assertEqual(dic["flush_duration"], 10.0)


if __name__ == "__main__":
    unittest.main()
