"""
Unit tests for adaptive background tracker ObjectModel.

Tests specifically for the boundary validation and size compatibility fixes
to prevent OpenCV size mismatch crashes.
"""

import pytest
import numpy as np
import cv2
from unittest.mock import Mock, patch

try:
    from ethoscope.trackers.adaptive_bg_tracker import ObjectModel
except ImportError:
    # Handle import for different test runner contexts
    import sys
    import os

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.trackers.adaptive_bg_tracker import ObjectModel


class TestObjectModel:
    """Test class for ObjectModel compute_features method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.model = ObjectModel(history_length=100)

    def test_compute_features_normal_case(self):
        """Test compute_features with normal bounding rectangle."""
        # Create a test image
        img = np.zeros((100, 100), dtype=np.uint8)
        img[40:60, 40:60] = 255  # White square

        # Create a contour that fits within bounds
        contour = np.array([[45, 45], [55, 45], [55, 55], [45, 55]], dtype=np.int32)

        # Should not raise an exception
        features = self.model.compute_features(img, contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3  # area, height, mean_grey
        assert np.issubdtype(features.dtype, np.floating)  # Accept any float type

    def test_compute_features_boundary_overflow(self):
        """Test compute_features with bounding rectangle extending beyond image bounds."""
        # Create a small test image
        img = np.zeros((50, 50), dtype=np.uint8)
        img[20:30, 20:30] = 255

        # Create a contour that extends beyond image boundaries
        contour = np.array([[45, 45], [60, 45], [60, 60], [45, 60]], dtype=np.int32)

        # Should handle gracefully without crashing
        features = self.model.compute_features(img, contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3
        assert not np.isnan(features).any()  # No NaN values

    def test_compute_features_zero_size_region(self):
        """Test compute_features when clipping results in zero-size region."""
        img = np.zeros((50, 50), dtype=np.uint8)

        # Create a contour completely outside image bounds
        contour = np.array([[60, 60], [70, 60], [70, 70], [60, 70]], dtype=np.int32)

        # Should return default features
        features = self.model.compute_features(img, contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3
        assert np.allclose(features, [0.0, 0.0, 0.0])

    def test_compute_features_negative_coordinates(self):
        """Test compute_features with negative coordinates in bounding rectangle."""
        img = np.zeros((50, 50), dtype=np.uint8)
        img[5:15, 5:15] = 255

        # Create a contour that starts at negative coordinates
        contour = np.array([[-5, -5], [10, -5], [10, 10], [-5, 10]], dtype=np.int32)

        # Should handle gracefully by clipping to valid bounds
        features = self.model.compute_features(img, contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3
        assert not np.isnan(features).any()

    def test_compute_features_shape_mismatch_handling(self):
        """Test that shape mismatches are handled correctly."""
        img = np.zeros((30, 40), dtype=np.uint8)  # Rectangular image
        img[10:20, 15:25] = 255

        # Create a contour near the edge where shape mismatch might occur
        contour = np.array([[35, 25], [45, 25], [45, 35], [35, 35]], dtype=np.int32)

        # Should handle shape mismatches gracefully
        features = self.model.compute_features(img, contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3
        assert not np.isnan(features).any()

    @patch("cv2.mean")
    def test_compute_features_cv2_error_handling(self, mock_mean):
        """Test that OpenCV errors are handled gracefully."""
        # Setup mock to raise cv2.error
        mock_mean.side_effect = cv2.error("Test OpenCV error")

        img = np.zeros((50, 50), dtype=np.uint8)
        contour = np.array([[10, 10], [20, 10], [20, 20], [10, 20]], dtype=np.int32)

        # Should not crash, should use fallback value
        features = self.model.compute_features(img, contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3
        # The mean_col feature should be 1.0 due to fallback (mean_col=0.0 + 1)
        assert features[2] == 1.0

    def test_buffer_reallocation(self):
        """Test that image buffers are reallocated correctly when needed."""
        # Start with small image
        small_img = np.zeros((20, 20), dtype=np.uint8)
        small_contour = np.array([[5, 5], [10, 5], [10, 10], [5, 10]], dtype=np.int32)

        self.model.compute_features(small_img, small_contour)

        # Now use larger image - should trigger reallocation
        large_img = np.zeros((100, 100), dtype=np.uint8)
        large_contour = np.array(
            [[40, 40], [60, 40], [60, 60], [40, 60]], dtype=np.int32
        )

        features = self.model.compute_features(large_img, large_contour)

        assert isinstance(features, np.ndarray)
        assert len(features) == 3
        # Buffers should have been reallocated
        assert self.model._roi_img_buff.shape[0] >= 20
        assert self.model._roi_img_buff.shape[1] >= 20

    def test_multiple_calls_consistency(self):
        """Test that multiple calls with the same input produce consistent results."""
        img = np.zeros((50, 50), dtype=np.uint8)
        img[20:30, 20:30] = 128
        contour = np.array([[18, 18], [32, 18], [32, 32], [18, 32]], dtype=np.int32)

        features1 = self.model.compute_features(img, contour)
        features2 = self.model.compute_features(img, contour)

        np.testing.assert_array_almost_equal(features1, features2)


if __name__ == "__main__":
    pytest.main([__file__])
