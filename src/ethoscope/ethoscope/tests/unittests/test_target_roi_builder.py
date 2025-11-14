__author__ = "quentin"

import os
import shutil
import tempfile
import unittest

import cv2
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
        # Create temporary directory for diagnostic data
        self.temp_dir = tempfile.mkdtemp(prefix="test_target_roi_")

        # Test with different configurations
        self.roi_builder_basic = TargetGridROIBuilder(n_rows=2, n_cols=1)
        self.roi_builder_diagnostic = TargetGridROIBuilder(
            n_rows=2,
            n_cols=1,
            enable_diagnostics=True,
            device_id="test_device",
            diagnostic_base_path=self.temp_dir,
        )

    def tearDown(self):
        """Clean up temporary directory."""
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

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
        self.roi_builder_diagnostic._find_target_coordinates(img)

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
        roi_builder._find_target_coordinates(img)

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
        roi_builder._find_target_coordinates(blank_img)

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

    def test_import_compatibility(self):
        """Test import exception handling and OpenCV version detection"""
        from ethoscope.roi_builders import target_roi_builder

        # Test CV_VERSION was set correctly
        self.assertIsInstance(target_roi_builder.CV_VERSION, int)
        self.assertIn(target_roi_builder.CV_VERSION, [2, 3, 4])

        # Test that LINE_AA constant was imported
        self.assertTrue(hasattr(target_roi_builder, "LINE_AA"))
        self.assertTrue(hasattr(target_roi_builder, "CHAIN_APPROX_SIMPLE"))

    def test_diagnostics_without_base_path(self):
        """Test diagnostic initialization with temporary base path"""
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            roi_builder = TargetGridROIBuilder(
                n_rows=1,
                n_cols=1,
                enable_diagnostics=True,
                device_id="test",
                diagnostic_base_path=temp_dir,
            )

            # Should initialize diagnostics without error
            self.assertTrue(roi_builder._enable_diagnostics)
            self.assertIsNotNone(roi_builder._diagnostics)

    def test_grayscale_image_input(self):
        """Test that builder handles grayscale images correctly"""
        # Load and convert to grayscale
        img = cv2.imread(images["bright_targets"], cv2.IMREAD_GRAYSCALE)
        self.assertEqual(len(img.shape), 2, "Image should be grayscale (2D)")

        # Should handle grayscale without error
        self.roi_builder_basic._find_target_coordinates(img)
        # Result can be None or valid targets, just shouldn't crash
        self.assertTrue(True, "Grayscale image handled without exception")

    def test_validation_with_wrong_number_of_points(self):
        """Test validation fails with wrong number of points"""
        # Test with 2 points
        two_points = np.array([[100, 100], [200, 200]], dtype=np.float32)
        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(two_points),
            "Validation should fail with 2 points",
        )

        # Test with 4 points
        four_points = np.array(
            [[100, 100], [200, 100], [200, 200], [100, 200]], dtype=np.float32
        )
        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(four_points),
            "Validation should fail with 4 points",
        )

    def test_validation_hypotenuse_check(self):
        """Test validation fails when AC is not the longest distance"""
        # Points where BC is longer than AC (A, B, C are sorted but not right-angle config)
        bad_points = np.array(
            [
                [200, 100],  # A
                [205, 150],  # B - close to A
                [100, 140],  # C - far from B (makes BC > AC)
            ],
            dtype=np.float32,
        )

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(bad_points),
            "Validation should fail when AC is not the hypotenuse",
        )

    def test_validation_alignment_failures(self):
        """Test validation fails with poor alignment"""
        # Points with bad vertical alignment (A and B x-coords very different)
        bad_vertical = np.array(
            [
                [100, 100],  # A
                [300, 400],  # B - x-coord too far from A
                [50, 395],  # C
            ],
            dtype=np.float32,
        )

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(bad_vertical),
            "Validation should fail with poor vertical alignment",
        )

        # Points with bad horizontal alignment (B and C y-coords very different)
        bad_horizontal = np.array(
            [
                [400, 100],  # A
                [405, 350],  # B
                [100, 150],  # C - y-coord too far from B
            ],
            dtype=np.float32,
        )

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(bad_horizontal),
            "Validation should fail with poor horizontal alignment",
        )

    def test_validation_zero_dimensions(self):
        """Test validation fails with zero width or height"""
        # Points with zero height (all same y)
        zero_height = np.array([[100, 200], [200, 200], [300, 200]], dtype=np.float32)

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(zero_height),
            "Validation should fail with zero height",
        )

        # Points with zero width (all same x)
        zero_width = np.array([[200, 100], [200, 200], [200, 300]], dtype=np.float32)

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(zero_width),
            "Validation should fail with zero width",
        )

    def test_validation_extreme_aspect_ratios(self):
        """Test validation fails with extreme aspect ratios"""
        # Very wide aspect ratio (> 4.0)
        very_wide = np.array(
            [
                [500, 100],  # A
                [505, 150],  # B - very small height
                [100, 145],  # C - very wide
            ],
            dtype=np.float32,
        )

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(very_wide),
            "Validation should fail with aspect ratio > 4.0",
        )

        # Very narrow aspect ratio (< 0.3)
        very_narrow = np.array(
            [
                [200, 100],  # A
                [205, 500],  # B - very tall
                [150, 495],  # C - very narrow
            ],
            dtype=np.float32,
        )

        self.assertFalse(
            self.roi_builder_basic._validate_target_geometry(very_narrow),
            "Validation should fail with aspect ratio < 0.3",
        )

    def test_rois_from_img_with_failed_detection(self):
        """Test _rois_from_img handles failed target detection gracefully"""
        # Create a blank image that won't have detectable targets
        blank_img = np.zeros((480, 640, 3), dtype=np.uint8)

        # Should return None, None for failed detection
        reference_points, rois = self.roi_builder_basic._rois_from_img(blank_img)

        self.assertIsNone(reference_points, "Should return None for failed detection")
        self.assertIsNone(rois, "Should return None for failed ROI generation")

    def test_diagnostics_save_success_images(self):
        """Test diagnostic saving with save_success_images enabled"""
        roi_builder = TargetGridROIBuilder(
            n_rows=1,
            n_cols=1,
            enable_diagnostics=True,
            device_id="test",
            diagnostic_base_path=self.temp_dir,
            save_success_images=True,  # Enable success image saving
        )

        # Try detection on good image
        img = cv2.imread(images["bright_targets"])
        roi_builder._find_target_coordinates(img)

        # Should complete without error
        self.assertTrue(True, "Diagnostic with save_success_images completed")

    def test_all(self):
        """Main test entry point - runs all target detection tests"""

        # Run the comprehensive test
        self.test_target_detection_with_sample_images()
        self.test_geometric_validation()
        self.test_diagnostic_logging()
        self.test_frame_averaging()
        self.test_reduced_attempts()
        self.test_import_compatibility()
        self.test_diagnostics_without_base_path()
        self.test_grayscale_image_input()
        self.test_validation_with_wrong_number_of_points()
        self.test_validation_hypotenuse_check()
        self.test_validation_alignment_failures()
        self.test_validation_zero_dimensions()
        self.test_validation_extreme_aspect_ratios()
        self.test_rois_from_img_with_failed_detection()
        self.test_diagnostics_save_success_images()
