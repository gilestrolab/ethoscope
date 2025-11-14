"""
Unit tests for BaseTracker class.

Tests core tracking functionality including position tracking, inference,
and error handling.
"""

import unittest
from unittest.mock import Mock

import numpy as np

from ethoscope.core.data_point import DataPoint
from ethoscope.core.roi import ROI
from ethoscope.core.variables import XPosVariable, YPosVariable
from ethoscope.trackers.trackers import BaseTracker, NoPositionError


class ConcreteTracker(BaseTracker):
    """Concrete implementation of BaseTracker for testing."""

    def __init__(self, roi, data=None, fail_tracking=False, return_dict=False):
        super().__init__(roi, data)
        self.fail_tracking = fail_tracking
        self.return_dict = return_dict

    def _find_position(self, img, mask, t):
        if self.fail_tracking:
            raise NoPositionError()

        if self.return_dict:
            # Return dict instead of list to trigger error (line 61)
            return {"x": 100, "y": 100}

        # Return valid DataPoint list
        data_point = DataPoint([XPosVariable(100), YPosVariable(100)])
        return [data_point]


class TestBaseTracker(unittest.TestCase):
    """Test suite for BaseTracker class."""

    def setUp(self):
        """Create test fixtures."""
        # Create a simple ROI
        contour = np.array([[10, 10], [10, 110], [110, 110], [110, 10]])
        self.roi = ROI(contour, idx=1)

        # Create test image
        self.test_img = np.zeros((200, 200), dtype=np.uint8)

    def test_track_returns_non_list_raises_exception(self):
        """Test that _find_position returning non-list raises exception (line 61)."""
        tracker = ConcreteTracker(self.roi, return_dict=True)

        with self.assertRaises(Exception) as context:
            tracker.track(1000, self.test_img)

        self.assertIn("LIST of DataPoints", str(context.exception))

    def test_track_empty_points_returns_empty_list(self):
        """Test that empty points list returns empty list (line 66)."""

        class EmptyTracker(BaseTracker):
            def _find_position(self, img, mask, t):
                return []  # Return empty list

        tracker = EmptyTracker(self.roi)
        result = tracker.track(1000, self.test_img)

        self.assertEqual(result, [])

    def test_infer_position_empty_list_when_no_positions(self):
        """Test _infer_position returns empty when no positions (line 99)."""
        tracker = ConcreteTracker(self.roi)

        # Call _infer_position without any tracking
        result = tracker._infer_position(1000)

        self.assertEqual(result, [])

    def test_infer_position_empty_list_when_too_old(self):
        """Test _infer_position returns empty when too much time passed (line 101)."""
        tracker = ConcreteTracker(self.roi)

        # Track once at t=1000
        tracker.track(1000, self.test_img)

        # Try to infer at t=32000 (31 seconds later, > 30s max)
        result = tracker._infer_position(32000, max_time=30 * 1000)

        self.assertEqual(result, [])

    def test_inferred_position_when_tracking_fails(self):
        """Test position inference when NoPositionError raised (lines 74-84)."""
        tracker = ConcreteTracker(self.roi)

        # First successful track
        tracker.track(1000, self.test_img)

        # Now make tracking fail
        tracker.fail_tracking = True
        result = tracker.track(2000, self.test_img)

        # Should return inferred position
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)
        # Check that position is marked as inferred
        self.assertTrue(bool(result[0]["is_inferred"]))

    def test_inferred_position_returns_empty_when_no_history(self):
        """Test inference returns empty list with no history (line 82)."""
        tracker = ConcreteTracker(self.roi, fail_tracking=True)

        # Track with no previous positions should return empty
        result = tracker.track(1000, self.test_img)

        self.assertEqual(result, [])

    def test_history_cleanup_when_max_length_exceeded(self):
        """Test position history cleanup (lines 93-94)."""
        tracker = ConcreteTracker(self.roi)
        # Set small max history for testing
        tracker._max_history_length = 100  # 100ms

        # Track at t=0, t=50, t=200
        tracker.track(0, self.test_img)
        tracker.track(50, self.test_img)
        tracker.track(200, self.test_img)

        # After tracking at t=200, the entry at t=0 should be removed
        # because (200 - 0) > 100ms
        self.assertEqual(len(tracker._times), 2)
        self.assertEqual(tracker._times[0], 50)

    def test_xy_pos_method(self):
        """Test xy_pos method returns first position at index (line 115)."""
        tracker = ConcreteTracker(self.roi)

        tracker.track(1000, self.test_img)
        tracker.track(2000, self.test_img)

        # Get first tracked position
        pos = tracker.xy_pos(0)

        self.assertIsNotNone(pos)

    def test_last_time_point_property(self):
        """Test last_time_point property (line 124)."""
        tracker = ConcreteTracker(self.roi)

        tracker.track(1000, self.test_img)
        tracker.track(2000, self.test_img)

        self.assertEqual(tracker.last_time_point, 2000)

    def test_times_property(self):
        """Test times property returns deque (line 132)."""
        tracker = ConcreteTracker(self.roi)

        tracker.track(1000, self.test_img)
        tracker.track(2000, self.test_img)

        times = tracker.times
        self.assertEqual(len(times), 2)
        self.assertEqual(times[0], 1000)
        self.assertEqual(times[1], 2000)


if __name__ == "__main__":
    unittest.main()
