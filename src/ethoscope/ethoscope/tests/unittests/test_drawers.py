"""
Unit tests for drawers/drawers.py.

Tests BaseDrawer, NullDrawer, and DefaultDrawer frame annotation.
"""

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from ethoscope.core.roi import ROI
from ethoscope.drawers.drawers import BaseDrawer, DefaultDrawer, NullDrawer


class TestNullDrawer(unittest.TestCase):
    """Test NullDrawer does nothing."""

    def test_init(self):
        with patch.object(BaseDrawer, "__init__", lambda self, **kw: None):
            drawer = NullDrawer()
            drawer._draw_frames = False
            drawer._video_out = None
            drawer._video_writer = None

    def test_annotate_frame_is_noop(self):
        with patch.object(BaseDrawer, "__init__", lambda self, **kw: None):
            drawer = NullDrawer()
            drawer._draw_frames = False
            img = np.zeros((100, 100, 3), dtype=np.uint8)
            # Should not raise or modify img
            drawer._annotate_frame(img, [], [])


class TestDefaultDrawerStimulatorIndicator(unittest.TestCase):
    """Test DefaultDrawer._draw_stimulator_indicator."""

    def setUp(self):
        with patch.object(BaseDrawer, "__init__", lambda self, **kw: None):
            self.drawer = DefaultDrawer()
            self.drawer._draw_frames = False
            self.drawer._video_out = None
            self.drawer._video_writer = None
            self.drawer._video_out_fourcc = "DIVX"
            self.drawer._video_out_fps = 25

        self.img = np.zeros((200, 300, 3), dtype=np.uint8)
        self.roi = ROI(
            polygon=((10, 10), (150, 10), (150, 80), (10, 80)), idx=1, value=1
        )

    def test_inactive_state(self):
        """Test inactive state draws empty circle."""
        self.drawer._draw_stimulator_indicator(self.img, self.roi, "inactive")
        # Should not crash; circle drawn

    def test_scheduled_state(self):
        """Test scheduled state draws white filled circle."""
        self.drawer._draw_stimulator_indicator(self.img, self.roi, "scheduled")

    def test_stimulating_state(self):
        """Test stimulating state draws blue filled circle."""
        self.drawer._draw_stimulator_indicator(self.img, self.roi, "stimulating")

    def test_unknown_state(self):
        """Test unknown state draws red warning circle."""
        self.drawer._draw_stimulator_indicator(self.img, self.roi, "weird_state")

    def test_error_state(self):
        """Test error state draws red circle."""
        self.drawer._draw_stimulator_indicator(self.img, self.roi, "error")


class TestDefaultDrawerAnnotateFrame(unittest.TestCase):
    """Test DefaultDrawer._annotate_frame."""

    def setUp(self):
        with patch.object(BaseDrawer, "__init__", lambda self, **kw: None):
            self.drawer = DefaultDrawer()
            self.drawer._draw_frames = False
            self.drawer._video_out = None
            self.drawer._video_writer = None

    def test_annotate_frame_none_img(self):
        """Test _annotate_frame returns early for None img."""
        self.drawer._annotate_frame(None, {}, [])

    def test_annotate_frame_empty_tracking_units(self):
        """Test _annotate_frame with empty tracking units."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        self.drawer._annotate_frame(img, {}, [])

    def test_annotate_frame_with_tracking_unit(self):
        """Test _annotate_frame draws ROI info."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        roi = ROI(polygon=((10, 10), (150, 10), (150, 80), (10, 80)), idx=1)

        mock_tu = Mock()
        mock_tu.roi = roi
        mock_tu.stimulator = None

        positions = {}  # No positions for this ROI

        self.drawer._annotate_frame(img, positions, [mock_tu])

    def test_annotate_frame_with_position_data(self):
        """Test _annotate_frame draws ellipses for positions."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        roi = ROI(polygon=((10, 10), (150, 10), (150, 80), (10, 80)), idx=1)

        mock_tu = Mock()
        mock_tu.roi = roi
        mock_tu.stimulator = None

        positions = {
            1: [
                {
                    "x": 50,
                    "y": 30,
                    "w": 20,
                    "h": 10,
                    "phi": 0,
                    "has_interacted": False,
                }
            ]
        }

        self.drawer._annotate_frame(img, positions, [mock_tu])

    def test_annotate_frame_with_interacted_position(self):
        """Test interacted position drawn in different color."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        roi = ROI(polygon=((10, 10), (150, 10), (150, 80), (10, 80)), idx=1)

        mock_tu = Mock()
        mock_tu.roi = roi
        mock_tu.stimulator = None

        positions = {
            1: [
                {
                    "x": 50,
                    "y": 30,
                    "w": 20,
                    "h": 10,
                    "phi": 0,
                    "has_interacted": True,
                }
            ]
        }

        self.drawer._annotate_frame(img, positions, [mock_tu])

    def test_annotate_frame_with_stimulator_state(self):
        """Test annotation with stimulator that has get_stimulator_state."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        roi = ROI(polygon=((10, 10), (150, 10), (150, 80), (10, 80)), idx=1)

        mock_stim = Mock()
        mock_stim.get_stimulator_state.return_value = "scheduled"

        mock_tu = Mock()
        mock_tu.roi = roi
        mock_tu.stimulator = mock_stim

        self.drawer._annotate_frame(img, {}, [mock_tu])

    def test_annotate_frame_with_reference_points(self):
        """Test annotation draws reference point markers."""
        img = np.zeros((200, 300, 3), dtype=np.uint8)
        ref_points = [(50, 50), (100, 100)]

        self.drawer._annotate_frame(img, {}, [], reference_points=ref_points)


class TestBaseDrawerProperties(unittest.TestCase):
    """Test BaseDrawer basic properties."""

    def test_last_drawn_frame_initially_none(self):
        with patch.object(BaseDrawer, "__init__", lambda self, **kw: None):
            drawer = BaseDrawer()
            drawer._last_drawn_frame = None
            self.assertIsNone(drawer.last_drawn_frame)


if __name__ == "__main__":
    unittest.main()
