"""
Target Detection Diagnostics Module

This module provides comprehensive diagnostic capabilities for target detection
in the TargetGridROIBuilder, including image quality analysis, detailed logging,
and systematic collection of detection samples for future analysis.
"""

__author__ = "giorgio"

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import cv2
import numpy as np


class TargetDetectionDiagnostics:
    """
    Handles diagnostic data collection and analysis for target detection.

    This class provides methods to analyze image quality, log detection attempts,
    save diagnostic images, and create metadata for failed/successful detections.
    """

    def __init__(
        self,
        device_id: str = "unknown",
        base_path: str = "/ethoscope_data/various/target_detection_logs",
    ):
        """
        Initialize diagnostics with device identifier and storage path.

        Args:
            device_id: Identifier for the ethoscope device
            base_path: Base directory for storing diagnostic data
        """
        self.device_id = device_id
        self.base_path = Path(base_path)
        self.logger = logging.getLogger(__name__)

        # Create directory structure
        self._setup_directories()

    def _setup_directories(self) -> None:
        """Create necessary directory structure for diagnostic data storage."""
        directories = [
            self.base_path / "failed",
            self.base_path / "success",
            self.base_path / "analysis_reports",
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Ensured directory exists: {directory}")

    def analyze_image_quality(self, image: np.ndarray) -> Dict[str, float]:
        """
        Analyze image quality metrics relevant to target detection.

        Args:
            image: Input image (BGR or grayscale)

        Returns:
            Dictionary containing image quality metrics
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # Basic statistics
        mean_brightness = float(np.mean(gray))
        median_brightness = float(np.median(gray))
        std_brightness = float(np.std(gray))
        min_brightness = float(np.min(gray))
        max_brightness = float(np.max(gray))

        # Contrast measures
        contrast_rms = float(np.sqrt(np.mean((gray - mean_brightness) ** 2)))
        contrast_range = max_brightness - min_brightness

        # Histogram analysis
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist_entropy = self._calculate_entropy(hist.flatten())

        # Edge density (proxy for detail/noise)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.sum(edges > 0) / edges.size)

        return {
            "mean_brightness": mean_brightness,
            "median_brightness": median_brightness,
            "std_brightness": std_brightness,
            "min_brightness": min_brightness,
            "max_brightness": max_brightness,
            "contrast_rms": contrast_rms,
            "contrast_range": contrast_range,
            "histogram_entropy": hist_entropy,
            "edge_density": edge_density,
            "image_shape": list(image.shape),
        }

    def _calculate_entropy(self, hist: np.ndarray) -> float:
        """Calculate entropy of histogram for image complexity measure."""
        hist = hist + 1e-10  # Avoid log(0)
        hist_norm = hist / np.sum(hist)
        return float(-np.sum(hist_norm * np.log2(hist_norm)))

    def log_detection_attempt(
        self,
        image: np.ndarray,
        targets_found: List[Tuple[float, float]],
        expected_targets: int = 3,
        threshold_used: Optional[int] = None,
        circularity_scores: Optional[List[float]] = None,
        processing_time: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Log detailed information about a target detection attempt.

        Args:
            image: Input image used for detection
            targets_found: List of (x, y) coordinates of detected targets
            expected_targets: Number of targets expected (default: 3)
            threshold_used: Threshold value that produced the best result
            circularity_scores: Circularity scores for detected targets
            processing_time: Time taken for detection in seconds

        Returns:
            Dictionary containing comprehensive detection metadata
        """
        timestamp = datetime.now()
        image_quality = self.analyze_image_quality(image)

        detection_success = len(targets_found) == expected_targets
        targets_missing = expected_targets - len(targets_found)

        metadata = {
            "timestamp": timestamp.isoformat(),
            "device_id": self.device_id,
            "detection_success": detection_success,
            "targets_expected": expected_targets,
            "targets_found": len(targets_found),
            "targets_missing": targets_missing,
            "target_coordinates": targets_found,
            "threshold_used": threshold_used,
            "circularity_scores": circularity_scores or [],
            "processing_time_seconds": processing_time,
            "image_quality": image_quality,
        }

        # Log summary
        if detection_success:
            self.logger.info(
                f"Target detection SUCCESS: Found {len(targets_found)}/{expected_targets} targets "
                f"(threshold={threshold_used}, brightness={image_quality['mean_brightness']:.1f})"
            )
        else:
            self.logger.warning(
                f"Target detection FAILED: Found {len(targets_found)}/{expected_targets} targets "
                f"(missing={targets_missing}, threshold={threshold_used}, "
                f"brightness={image_quality['mean_brightness']:.1f}, "
                f"contrast={image_quality['contrast_rms']:.1f})"
            )

            # Detailed failure analysis
            if image_quality["mean_brightness"] < 50:
                self.logger.warning(
                    "Image appears very dark - consider increasing illumination"
                )
            elif image_quality["mean_brightness"] > 200:
                self.logger.warning(
                    "Image appears very bright - consider reducing illumination"
                )

            if image_quality["contrast_rms"] < 20:
                self.logger.warning(
                    "Low contrast detected - targets may not be clearly distinguishable"
                )

            if image_quality["edge_density"] > 0.3:
                self.logger.warning(
                    "High noise/edge density - consider cleaning arena or adjusting focus"
                )

        return metadata

    def save_detection_image(
        self,
        image: np.ndarray,
        metadata: Dict[str, Any],
        save_success: bool = True,
        save_failed: bool = True,
    ) -> Optional[str]:
        """
        Save detection image with metadata to appropriate directory.

        Args:
            image: Original image used for detection
            metadata: Detection metadata from log_detection_attempt
            save_success: Whether to save successful detection images
            save_failed: Whether to save failed detection images

        Returns:
            Path to saved image file, or None if not saved
        """
        success = metadata.get("detection_success", False)

        # Check if we should save this type of result
        if success and not save_success:
            return None
        if not success and not save_failed:
            return None

        # Determine save directory
        subdir = "success" if success else "failed"
        save_dir = self.base_path / subdir

        # Generate filename
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_filename = f"{timestamp}_{self.device_id}"

        # Save image
        image_path = save_dir / f"{base_filename}_original.png"
        cv2.imwrite(str(image_path), image)

        # Save metadata
        metadata_path = save_dir / f"{base_filename}_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

        self.logger.debug(f"Saved detection sample: {image_path}")
        return str(image_path)

    def create_annotated_image(
        self,
        image: np.ndarray,
        targets_found: List[Tuple[float, float]],
        metadata: Dict[str, Any],
    ) -> np.ndarray:
        """
        Create an annotated version of the image showing detection results.

        Args:
            image: Original image
            targets_found: List of detected target coordinates
            metadata: Detection metadata

        Returns:
            Annotated image with detection overlay
        """
        annotated = image.copy()

        # Draw detected targets
        for i, (x, y) in enumerate(targets_found):
            center = (int(x), int(y))
            cv2.circle(annotated, center, 20, (0, 255, 0), 3)  # Green circles
            cv2.putText(
                annotated,
                f"T{i+1}",
                (int(x + 25), int(y)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
            )

        # Add status text
        success = metadata.get("detection_success", False)
        status_text = "SUCCESS" if success else "FAILED"
        status_color = (0, 255, 0) if success else (0, 0, 255)

        cv2.putText(
            annotated,
            f"Detection: {status_text}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            status_color,
            2,
        )

        # Add statistics
        targets_info = f"Targets: {len(targets_found)}/3"
        cv2.putText(
            annotated,
            targets_info,
            (10, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        brightness = metadata.get("image_quality", {}).get("mean_brightness", 0)
        brightness_info = f"Brightness: {brightness:.1f}"
        cv2.putText(
            annotated,
            brightness_info,
            (10, 110),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        return annotated

    def get_diagnostics_summary(self) -> Dict[str, int]:
        """
        Get summary statistics of collected diagnostic data.

        Returns:
            Dictionary with counts of failed/successful detections
        """
        failed_dir = self.base_path / "failed"
        success_dir = self.base_path / "success"

        failed_count = (
            len(list(failed_dir.glob("*_original.png")))
            if failed_dir.exists()
            else 0
        )
        success_count = (
            len(list(success_dir.glob("*_original.png")))
            if success_dir.exists()
            else 0
        )

        return {
            "failed_detections": failed_count,
            "successful_detections": success_count,
            "total_samples": failed_count + success_count,
        }
