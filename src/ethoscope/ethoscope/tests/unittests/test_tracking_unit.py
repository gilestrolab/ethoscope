"""
Unit tests for core/tracking_unit.py.

Tests TrackingUnit class including initialization, tracker/stimulator binding,
position retrieval, and the track pipeline.
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np

from ethoscope.core.data_point import DataPoint
from ethoscope.core.roi import ROI
from ethoscope.core.tracking_unit import TrackingUnit
from ethoscope.core.variables import BaseRelativeVariable
from ethoscope.stimulators.stimulators import DefaultStimulator, HasInteractedVariable


class MockTracker:
    """Minimal tracker class for testing TrackingUnit."""

    def __init__(self, roi, *args, **kwargs):
        self._roi = roi
        self.positions = []
        self.times = []
        self.last_time_point = 0

    def track(self, t, img):
        return []


class TestTrackingUnitInit(unittest.TestCase):
    """Test TrackingUnit initialization."""

    def setUp(self):
        self.roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)

    def test_init_without_stimulator(self):
        """Test init creates DefaultStimulator when none provided."""
        tu = TrackingUnit(MockTracker, self.roi)
        self.assertIsInstance(tu.stimulator, DefaultStimulator)

    def test_init_with_stimulator(self):
        """Test init uses provided stimulator."""
        mock_stim = Mock()
        mock_stim.bind_tracker = Mock()
        tu = TrackingUnit(MockTracker, self.roi, stimulator=mock_stim)
        self.assertIs(tu.stimulator, mock_stim)
        mock_stim.bind_tracker.assert_called_once()

    def test_roi_property(self):
        """Test roi property returns the ROI."""
        tu = TrackingUnit(MockTracker, self.roi)
        self.assertIs(tu.roi, self.roi)

    def test_stimulator_property(self):
        """Test stimulator property returns the stimulator."""
        tu = TrackingUnit(MockTracker, self.roi)
        self.assertIsNotNone(tu.stimulator)


class TestTrackingUnitGetLastPositions(unittest.TestCase):
    """Test TrackingUnit.get_last_positions()."""

    def setUp(self):
        self.roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)
        self.tu = TrackingUnit(MockTracker, self.roi)

    def test_empty_positions(self):
        """Test returns empty list when no positions recorded."""
        result = self.tu.get_last_positions()
        self.assertEqual(result, [])

    def test_relative_positions(self):
        """Test returns last positions in relative mode (default)."""
        mock_pos = [{"x": Mock(spec=[]), "y": Mock(spec=[])}]
        self.tu._tracker.positions = [mock_pos]
        result = self.tu.get_last_positions(absolute=False)
        self.assertEqual(result, mock_pos)

    def test_absolute_positions_with_relative_variables(self):
        """Test converts BaseRelativeVariable to absolute when absolute=True."""
        mock_var = Mock(spec=BaseRelativeVariable)
        mock_var.to_absolute = Mock(return_value=Mock())
        mock_pos = [{"x": mock_var}]
        self.tu._tracker.positions = [mock_pos]

        result = self.tu.get_last_positions(absolute=True)
        self.assertEqual(len(result), 1)
        mock_var.to_absolute.assert_called_once_with(self.roi)


class TestTrackingUnitTrack(unittest.TestCase):
    """Test TrackingUnit.track()."""

    def setUp(self):
        self.roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)
        self.img = np.zeros((200, 300, 3), dtype=np.uint8)

    def test_track_returns_empty_when_no_data(self):
        """Test track returns empty list when tracker returns no data."""
        tu = TrackingUnit(MockTracker, self.roi)
        result = tu.track(1000, self.img)
        self.assertEqual(result, [])

    def test_track_calls_stimulator_apply(self):
        """Test track calls stimulator.apply()."""
        tu = TrackingUnit(MockTracker, self.roi)
        tu._stimulator = Mock()
        tu._stimulator.apply.return_value = (HasInteractedVariable(False), {})
        tu._tracker.track = Mock(return_value=[])

        tu.track(1000, self.img)
        tu._stimulator.apply.assert_called_once()

    def test_track_appends_interact_to_data_rows(self):
        """Test track appends interaction variable to each data row."""
        tu = TrackingUnit(MockTracker, self.roi)

        # Create mock data rows with append method
        mock_dr = Mock()
        mock_dr.append = Mock()
        tu._tracker.track = Mock(return_value=[mock_dr])

        interact = HasInteractedVariable(True)
        tu._stimulator = Mock()
        tu._stimulator.apply.return_value = (interact, {})

        result = tu.track(1000, self.img)
        self.assertEqual(len(result), 1)
        mock_dr.append.assert_called_once_with(interact)


if __name__ == "__main__":
    unittest.main()
