"""
Unit tests for target detection diagnostics.

Tests diagnostic capabilities for target detection including image quality analysis,
logging, and diagnostic data collection.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from ethoscope.roi_builders.target_detection_diagnostics import (
    TargetDetectionDiagnostics,
)


class TestTargetDetectionDiagnostics(unittest.TestCase):
    """Test suite for TargetDetectionDiagnostics class."""

    def setUp(self):
        """Create temporary directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.diagnostics = TargetDetectionDiagnostics(
            device_id="test_device", base_path=self.temp_dir
        )

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_setup_directories(self):
        """Test directory creation."""
        expected_dirs = ["failed", "success", "analysis_reports"]

        for dir_name in expected_dirs:
            dir_path = Path(self.temp_dir) / dir_name
            self.assertTrue(dir_path.exists())
            self.assertTrue(dir_path.is_dir())

    def test_analyze_image_quality_color_image(self):
        """Test image quality analysis with color image."""
        # Create a test color image
        test_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        quality = self.diagnostics.analyze_image_quality(test_image)

        # Check that all expected metrics are present
        expected_metrics = [
            "mean_brightness",
            "median_brightness",
            "std_brightness",
            "min_brightness",
            "max_brightness",
            "contrast_rms",
            "edge_density",
        ]

        for metric in expected_metrics:
            self.assertIn(metric, quality)
            self.assertIsInstance(quality[metric], float)

    def test_analyze_image_quality_grayscale_image(self):
        """Test image quality analysis with grayscale image (line 74)."""
        # Create a test grayscale image
        test_image = np.random.randint(0, 255, (480, 640), dtype=np.uint8)

        quality = self.diagnostics.analyze_image_quality(test_image)

        # Should still return all metrics
        self.assertIn("mean_brightness", quality)
        self.assertIn("contrast_rms", quality)
        self.assertGreaterEqual(quality["mean_brightness"], 0)

    def test_log_detection_attempt_success(self):
        """Test logging successful detection."""
        test_image = np.zeros((480, 640), dtype=np.uint8)
        targets_found = [(100, 100), (200, 200), (300, 300)]

        with patch.object(self.diagnostics.logger, "info") as mock_info:
            metadata = self.diagnostics.log_detection_attempt(
                image=test_image,
                targets_found=targets_found,
                expected_targets=3,
                threshold_used=128,
            )

        # Should log success message
        mock_info.assert_called()
        call_args = str(mock_info.call_args)
        self.assertIn("SUCCESS", call_args)

        # Metadata should contain required fields
        self.assertTrue(metadata["detection_success"])
        self.assertEqual(metadata["targets_found"], 3)
        self.assertEqual(metadata["targets_expected"], 3)

    def test_log_detection_attempt_failure_dark_image(self):
        """Test logging failed detection with dark image (lines 164-187)."""
        # Create very dark image (mean brightness < 50)
        test_image = np.ones((480, 640), dtype=np.uint8) * 20

        targets_found = [(100, 100)]

        with patch.object(self.diagnostics.logger, "warning") as mock_warning:
            metadata = self.diagnostics.log_detection_attempt(
                image=test_image,
                targets_found=targets_found,
                expected_targets=3,
                threshold_used=128,
            )

        # Should log failure and dark image warnings
        self.assertGreaterEqual(mock_warning.call_count, 2)
        self.assertFalse(metadata["detection_success"])

        # Check for dark image warning
        warnings = [str(call) for call in mock_warning.call_args_list]
        self.assertTrue(any("dark" in str(w).lower() for w in warnings))

    def test_log_detection_attempt_failure_bright_image(self):
        """Test logging failed detection with bright image (lines 164-187)."""
        # Create very bright image (mean brightness > 200)
        test_image = np.ones((480, 640), dtype=np.uint8) * 220

        targets_found = [(100, 100)]

        with patch.object(self.diagnostics.logger, "warning") as mock_warning:
            self.diagnostics.log_detection_attempt(
                image=test_image,
                targets_found=targets_found,
                expected_targets=3,
                threshold_used=128,
            )

        # Check for bright image warning
        warnings = [str(call) for call in mock_warning.call_args_list]
        self.assertTrue(any("bright" in str(w).lower() for w in warnings))

    def test_log_detection_attempt_low_contrast(self):
        """Test logging with low contrast warning (lines 164-187)."""
        # Create low contrast image (uniform gray)
        test_image = np.ones((480, 640), dtype=np.uint8) * 128

        targets_found = []

        with patch.object(self.diagnostics.logger, "warning") as mock_warning:
            self.diagnostics.log_detection_attempt(
                image=test_image,
                targets_found=targets_found,
                expected_targets=3,
                threshold_used=128,
            )

        # Check for contrast warning
        warnings = [str(call) for call in mock_warning.call_args_list]
        self.assertTrue(any("contrast" in str(w).lower() for w in warnings))

    def test_save_detection_image_skip_success(self):
        """Test save_detection_image skips when save_success=False (lines 215-216)."""
        test_image = np.zeros((480, 640), dtype=np.uint8)
        metadata = {"detection_success": True}

        # Should return None when save_success=False
        result = self.diagnostics.save_detection_image(
            image=test_image,
            metadata=metadata,
            save_success=False,  # Don't save success
            save_failed=True,
        )

        self.assertIsNone(result)

    def test_save_detection_image_skip_failed(self):
        """Test save_detection_image skips when save_failed=False (lines 217-218)."""
        test_image = np.zeros((480, 640), dtype=np.uint8)
        metadata = {"detection_success": False}

        # Should return None when save_failed=False
        result = self.diagnostics.save_detection_image(
            image=test_image,
            metadata=metadata,
            save_success=True,
            save_failed=False,  # Don't save failed
        )

        self.assertIsNone(result)

    def test_create_annotated_image(self):
        """Test annotated image creation (lines 240-312)."""
        test_image = np.zeros((480, 640, 3), dtype=np.uint8)
        targets_found = [(100, 100), (200, 200)]
        metadata = {
            "detection_success": True,
            "image_quality": {"mean_brightness": 128.5},
        }

        annotated = self.diagnostics.create_annotated_image(
            test_image, targets_found, metadata
        )

        # Should return an image of the same shape
        self.assertEqual(annotated.shape, test_image.shape)
        self.assertIsNot(annotated, test_image)  # Should be a copy

        # Image should have been modified (circles and text added)
        self.assertFalse(np.array_equal(annotated, test_image))

    def test_create_annotated_image_failed_detection(self):
        """Test annotated image for failed detection (lines 240-312)."""
        test_image = np.zeros((480, 640, 3), dtype=np.uint8)
        targets_found = [(100, 100)]  # Only found 1/3
        metadata = {
            "detection_success": False,
            "image_quality": {"mean_brightness": 45.2},
        }

        annotated = self.diagnostics.create_annotated_image(
            test_image, targets_found, metadata
        )

        # Should create annotated image with FAILED status
        self.assertEqual(annotated.shape, test_image.shape)
        self.assertFalse(np.array_equal(annotated, test_image))

    def test_get_diagnostics_summary_empty(self):
        """Test diagnostics summary with no saved images (lines 321-331)."""
        summary = self.diagnostics.get_diagnostics_summary()

        self.assertEqual(summary["failed_detections"], 0)
        self.assertEqual(summary["successful_detections"], 0)
        self.assertEqual(summary["total_samples"], 0)

    def test_get_diagnostics_summary_with_files(self):
        """Test diagnostics summary with saved files (lines 321-331)."""
        # Create some fake diagnostic files
        failed_dir = Path(self.temp_dir) / "failed"
        success_dir = Path(self.temp_dir) / "success"

        # Create test files
        (failed_dir / "test1_original.png").touch()
        (failed_dir / "test2_original.png").touch()
        (success_dir / "test3_original.png").touch()

        summary = self.diagnostics.get_diagnostics_summary()

        self.assertEqual(summary["failed_detections"], 2)
        self.assertEqual(summary["successful_detections"], 1)
        self.assertEqual(summary["total_samples"], 3)


if __name__ == "__main__":
    unittest.main()
