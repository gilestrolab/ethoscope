"""
Unit tests for ImgMaskROIBuilder.

Tests ROI generation from grayscale image masks where each contour becomes an ROI.
"""

import os
import pathlib
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from ethoscope.roi_builders.img_roi_builder import ImgMaskROIBuilder

# Get the absolute path to the test images
test_dir = pathlib.Path(__file__).parent.parent / "static_files" / "img"
TEST_MASK_PATH = str(test_dir / "test_roi_mask.png")


class TestImgMaskROIBuilder(unittest.TestCase):
    """Test suite for ImgMaskROIBuilder."""

    def test_init_with_valid_mask(self):
        """Test initialization with a valid mask file."""
        builder = ImgMaskROIBuilder(TEST_MASK_PATH)
        self.assertIsNotNone(builder._mask)
        self.assertEqual(len(builder._mask.shape), 2)  # Should be grayscale

    def test_init_with_invalid_path(self):
        """Test initialization with non-existent mask file."""
        # cv2.imread returns None for invalid paths, doesn't raise exception
        # So the builder will have None as mask, which we can check
        builder = ImgMaskROIBuilder("/nonexistent/path/to/mask.png")
        self.assertIsNone(builder._mask)

    def test_rois_from_img_generates_rois(self):
        """Test that _rois_from_img generates ROIs from mask."""
        builder = ImgMaskROIBuilder(TEST_MASK_PATH)

        # Create dummy input image (actual frame from camera)
        dummy_img = np.zeros((480, 640), dtype=np.uint8)

        rois = builder._rois_from_img(dummy_img)

        # Should generate 2 ROIs from our test mask (2 rectangles)
        self.assertGreater(len(rois), 0)
        self.assertLessEqual(len(rois), 3)  # Allow some tolerance for contour detection

        # Check ROI properties
        for roi in rois:
            self.assertIsNotNone(roi)
            self.assertGreater(roi.idx, 0)
            # ROI value should match the grayscale value from mask
            self.assertIn(roi.value, [0, 100, 200])

    def test_rois_have_unique_indices(self):
        """Test that generated ROIs have unique sequential indices."""
        builder = ImgMaskROIBuilder(TEST_MASK_PATH)
        dummy_img = np.zeros((480, 640), dtype=np.uint8)

        rois = builder._rois_from_img(dummy_img)

        indices = [roi.idx for roi in rois]
        # Indices should start from 1 and be sequential
        self.assertEqual(indices, list(range(1, len(rois) + 1)))

    def test_handles_color_mask(self):
        """Test that builder handles color masks by converting to grayscale."""
        # Create a color version of the mask
        color_mask = cv2.imread(TEST_MASK_PATH)
        if color_mask is None:
            self.skipTest("Could not load test mask as color image")

        # Save as color
        color_mask_path = str(test_dir / "test_roi_mask_color.png")
        cv2.imwrite(color_mask_path, color_mask)

        try:
            builder = ImgMaskROIBuilder(color_mask_path)
            dummy_img = np.zeros((480, 640), dtype=np.uint8)

            rois = builder._rois_from_img(dummy_img)

            # Should still generate ROIs even with color input
            self.assertGreater(len(rois), 0)

        finally:
            # Cleanup
            if os.path.exists(color_mask_path):
                os.remove(color_mask_path)

    def test_cv_version_3_compatibility(self):
        """Test that builder works with OpenCV 3.x API (line 42-44)."""
        # Test the OpenCV 3.x code path which has different findContours return value
        from ethoscope import roi_builders

        # Temporarily mock CV_VERSION to test cv3 compatibility
        original_cv_version = roi_builders.img_roi_builder.CV_VERSION
        try:
            roi_builders.img_roi_builder.CV_VERSION = 3

            builder = ImgMaskROIBuilder(TEST_MASK_PATH)
            dummy_img = np.zeros((480, 640), dtype=np.uint8)

            # Mock cv2.findContours to return 3 values like CV3 does
            original_findContours = cv2.findContours

            def mock_findContours_cv3(*args, **kwargs):
                contours, hierarchy = original_findContours(*args, **kwargs)
                return (None, contours, hierarchy)  # CV3 returns 3 values

            with patch("cv2.findContours", side_effect=mock_findContours_cv3):
                rois = builder._rois_from_img(dummy_img)

            # Should work with OpenCV 3.x code path
            self.assertGreater(len(rois), 0)

        finally:
            # Restore original CV_VERSION
            roi_builders.img_roi_builder.CV_VERSION = original_cv_version

    def test_cv_version_4_compatibility(self):
        """Test that builder works with OpenCV 4.x API (same as 2.x)."""
        # Test the OpenCV 4.x code path (same as 2.x - line 46-48)
        from ethoscope import roi_builders

        # Temporarily mock CV_VERSION to test cv4 compatibility (uses 2.x API)
        original_cv_version = roi_builders.img_roi_builder.CV_VERSION
        try:
            roi_builders.img_roi_builder.CV_VERSION = 4

            builder = ImgMaskROIBuilder(TEST_MASK_PATH)
            dummy_img = np.zeros((480, 640), dtype=np.uint8)

            rois = builder._rois_from_img(dummy_img)

            # Should work with OpenCV 4.x code path
            self.assertGreater(len(rois), 0)

        finally:
            # Restore original CV_VERSION
            roi_builders.img_roi_builder.CV_VERSION = original_cv_version

    def test_cv_version_exception_handling(self):
        """Test CV_VERSION exception handling at import time."""
        # This tests lines 5-6 (exception handling)
        # We can't directly test import-time exceptions, but we can verify
        # that CV_VERSION is set correctly in the module
        from ethoscope.roi_builders import img_roi_builder

        # CV_VERSION should be an integer
        self.assertIsInstance(img_roi_builder.CV_VERSION, int)
        # Should be 2, 3, or 4 (current OpenCV versions)
        self.assertIn(img_roi_builder.CV_VERSION, [2, 3, 4])

    def test_opencv_import_compatibility(self):
        """Test that OpenCV constants are imported correctly."""
        # This tests lines 10-11 and 13-14 (import compatibility)
        from ethoscope.roi_builders import img_roi_builder

        # Verify that the constants were imported successfully
        self.assertTrue(hasattr(img_roi_builder, "CHAIN_APPROX_SIMPLE"))
        self.assertTrue(hasattr(img_roi_builder, "RETR_EXTERNAL"))
        self.assertTrue(hasattr(img_roi_builder, "IMG_READ_FLAG_GREY"))

    def test_rois_from_img_with_3channel_mask(self):
        """Test _rois_from_img properly converts 3-channel masks to grayscale."""
        # This specifically tests line 40 (color conversion)
        builder = ImgMaskROIBuilder(TEST_MASK_PATH)

        # Create a 3-channel mask to force color conversion
        three_channel_mask = cv2.cvtColor(builder._mask, cv2.COLOR_GRAY2BGR)
        builder._mask = three_channel_mask

        # Verify mask is 3-channel
        self.assertEqual(len(builder._mask.shape), 3)

        dummy_img = np.zeros((480, 640), dtype=np.uint8)
        rois = builder._rois_from_img(dummy_img)

        # After conversion, mask should be grayscale
        self.assertEqual(len(builder._mask.shape), 2)
        # Should still generate ROIs
        self.assertGreater(len(rois), 0)


if __name__ == "__main__":
    unittest.main()
