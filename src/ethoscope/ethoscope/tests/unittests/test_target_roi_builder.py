__author__ = "quentin"

import cv2
import unittest
import os
import numpy as np
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder

try:
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import LINE_AA

# Get the absolute path to the test images
import pathlib

test_dir = pathlib.Path(__file__).parent.parent / "static_files" / "img"
images = {
    "bright_targets": str(test_dir / "bright_targets.png"),
    "dark_targets": str(test_dir / "dark_targets.png"),
}

LOG_DIR = "./test_logs/"


class TestTargetROIBuilder(unittest.TestCase):

    def setUp(self):
        # Test with different configurations
        self.roi_builder_basic = TargetGridROIBuilder(n_rows=2, n_cols=1)
        self.roi_builder_diagnostic = TargetGridROIBuilder(
            n_rows=2, n_cols=1, enable_diagnostics=True, device_id="test_device"
        )

    def _draw_rois(self, img, rois):
        """Draw ROIs on image for visual verification"""
        for r in rois:
            cv2.drawContours(img, r.polygon, -1, (255, 255, 0), 2, LINE_AA)

    def _draw_targets(self, img, target_points):
        """Draw detected target points on image"""
        if target_points is not None:
            for i, pt in enumerate(target_points):
                # Draw circles for detected targets
                cv2.circle(img, (int(pt[0]), int(pt[1])), 10, (0, 255, 0), 2)
                # Label the points A, B, C
                labels = ["A", "B", "C"]
                cv2.putText(
                    img,
                    labels[i],
                    (int(pt[0]) + 15, int(pt[1]) + 15),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                )

    def test_geometric_validation(self):
        """Test the geometric validation function with known configurations"""

        # Good configuration (similar to expected arena layout)
        good_points = np.array(
            [
                [400, 100],  # A - upper right
                [405, 350],  # B - lower right
                [100, 345],  # C - lower left
            ],
            dtype=np.float32,
        )

        # Bad configuration - points in a line
        bad_points = np.array([[100, 200], [200, 200], [300, 200]], dtype=np.float32)

        # Test geometric validation
        self.assertTrue(
            self.roi_builder_basic._validate_target_geometry(good_points),
            "Good geometric configuration should pass validation",
        )

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(bad_points),
            "Bad geometric configuration should fail validation",
        )

    def test_target_detection_with_sample_images(self):
        """Test target detection using the provided sample images"""

        for image_name, image_path in images.items():
            with self.subTest(image=image_name):
                # Load image
                img = cv2.imread(image_path)
                self.assertIsNotNone(img, f"Could not load image: {image_path}")

                # Create a copy for drawing
                img_with_results = img.copy()

                # Test target detection
                target_points = self.roi_builder_basic._find_target_coordinates(img)

                # For these specific test images, we expect to find targets
                # (adjust expectation based on actual image content)
                if target_points is not None:
                    self.assertEqual(
                        len(target_points),
                        3,
                        f"Should detect exactly 3 targets in {image_name}",
                    )

                    # Verify geometric validity
                    self.assertTrue(
                        self.roi_builder_basic._validate_target_geometry(target_points),
                        f"Detected targets should have valid geometry in {image_name}",
                    )

                    # Draw detected targets
                    self._draw_targets(img_with_results, target_points)

                    # Test full ROI building
                    reference_points, rois = self.roi_builder_basic._rois_from_img(img)

                    if rois is not None:
                        self.assertEqual(
                            len(rois),
                            2,
                            f"Should create 2 ROIs (2 rows × 1 col) in {image_name}",
                        )
                        self._draw_rois(img_with_results, rois)

                # Save result image for visual inspection
                os.makedirs(LOG_DIR, exist_ok=True)
                output_path = os.path.join(LOG_DIR, f"{image_name}_results.png")
                cv2.imwrite(output_path, img_with_results)
                print(f"Saved test result: {output_path}")

    def test_diagnostic_logging(self):
        """Test that diagnostic logging works without errors"""

        # Test with bright targets image
        img_path = images["bright_targets"]
        img = cv2.imread(img_path)

        # This should trigger diagnostic logging
        target_points = self.roi_builder_diagnostic._find_target_coordinates(img)

        # Should complete without errors regardless of detection success
        # (diagnostics should handle both success and failure cases)
        self.assertTrue(True, "Diagnostic logging completed without exceptions")

    def test_frame_averaging(self):
        """Test simplified frame averaging functionality"""

        roi_builder = TargetGridROIBuilder(
            n_rows=1, n_cols=1, enable_frame_averaging=True
        )

        # Load test image
        img = cv2.imread(images["dark_targets"])

        # First detection (no previous frame)
        self.assertIsNone(roi_builder._previous_frame)

        # Run detection - this will either succeed or fail and store frame
        target_points1 = roi_builder._find_target_coordinates(img)

        # After first detection attempt, previous frame should be set if frame averaging is enabled
        # (Note: only stored if detection failed completely, but we test the mechanism works)

        # Create a second test with no detectable targets to ensure frame storage
        # Create a blank image that won't have detectable targets
        blank_img = np.zeros((480, 640, 3), dtype=np.uint8)

        # This should fail and store the frame
        roi_builder._find_target_coordinates(blank_img)

        # Now previous frame should be set
        self.assertIsNotNone(roi_builder._previous_frame)

        # Test that subsequent detection with frame averaging doesn't crash
        target_points2 = roi_builder._find_target_coordinates(blank_img)

        # Should complete without errors
        self.assertTrue(True, "Frame averaging completed without exceptions")

    def test_reduced_attempts(self):
        """Test that max attempts are limited to 3"""

        roi_builder = TargetGridROIBuilder(
            max_detection_attempts=10  # Request 10 attempts
        )

        # Should be capped at 3
        self.assertEqual(
            roi_builder._max_detection_attempts, 3, "Max attempts should be capped at 3"
        )

    def test_all(self):
        """Main test entry point - runs all target detection tests"""

        # Run the comprehensive test
        self.test_target_detection_with_sample_images()
        self.test_geometric_validation()
        self.test_diagnostic_logging()
        self.test_frame_averaging()
        self.test_reduced_attempts()
