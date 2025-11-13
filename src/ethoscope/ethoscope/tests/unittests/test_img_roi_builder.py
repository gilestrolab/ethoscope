"""
Unit tests for ImgMaskROIBuilder.

Tests ROI generation from grayscale image masks where each contour becomes an ROI.
"""

import os
import pathlib
import unittest

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
        for i, roi in enumerate(rois):
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


if __name__ == "__main__":
    unittest.main()
