__author__ = "quentin"

import cv2
import logging  # noqa: F811
import time
from typing import Optional, Tuple, List

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

try:
    from cv2.cv import CV_CHAIN_APPROX_SIMPLE as CHAIN_APPROX_SIMPLE
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import CHAIN_APPROX_SIMPLE
    from cv2 import LINE_AA

import numpy as np
import logging  # noqa: F811
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI
from ethoscope.utils.debug import EthoscopeException
from ethoscope.roi_builders.target_detection_diagnostics import (
    TargetDetectionDiagnostics,
)
import itertools


class TargetGridROIBuilder(BaseROIBuilder):

    _adaptive_med_rad = 0.10
    _expected__min_target_dist = (
        10  # the minimal distance between two targets, in 'target diameter'
    )
    _n_rows = 10
    _n_cols = 2
    _top_margin = 0
    _bottom_margin = None
    _left_margin = 0
    _right_margin = None
    _horizontal_fill = 1
    _vertical_fill = None

    _description = {
        "overview": "A flexible ROI builder that allows users to select parameters for the ROI layout."
        "Lengths are relative to the distance between the two bottom targets (width)",
        "arguments": [
            {
                "type": "number",
                "min": 1,
                "max": 16,
                "step": 1,
                "name": "n_cols",
                "description": "The number of columns",
                "default": 1,
            },
            {
                "type": "number",
                "min": 1,
                "max": 16,
                "step": 1,
                "name": "n_rows",
                "description": "The number of rows",
                "default": 1,
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.001,
                "name": "top_margin",
                "description": "The vertical distance between the middle of the top ROIs and the middle of the top target.",
                "default": 0.0,
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.001,
                "name": "bottom_margin",
                "description": "Same as top_margin, but for the bottom.",
                "default": 0.0,
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.001,
                "name": "right_margin",
                "description": "Same as top_margin, but for the right.",
                "default": 0.0,
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.001,
                "name": "left_margin",
                "description": "Same as top_margin, but for the left.",
                "default": 0.0,
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.001,
                "name": "horizontal_fill",
                "description": "The proportion of the grid space used by the roi, horizontally.",
                "default": 0.90,
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.001,
                "name": "vertical_fill",
                "description": "Same as horizontal_margin, but vertically.",
                "default": 0.90,
            },
        ],
    }

    def __init__(
        self,
        n_rows=1,
        n_cols=1,
        top_margin=0,
        bottom_margin=0,
        left_margin=0,
        right_margin=0,
        horizontal_fill=0.9,
        vertical_fill=0.9,
        enable_diagnostics=False,
        device_id="unknown",
        save_success_images=False,
        max_detection_attempts=5,
        enable_frame_averaging=True,
    ):
        """
        This roi builder uses three black circles drawn on the arena (targets) to align a grid layout:

        IMAGE HERE

        :param n_rows: The number of rows in the grid.
        :type n_rows: int
        :param n_cols: The number of columns.
        :type n_cols: int
        :param top_margin: The vertical distance between the middle of the top ROIs and the middle of the top target
        :type top_margin: float
        :param bottom_margin: same as top_margin, but for the bottom.
        :type bottom_margin: float
        :param left_margin: same as top_margin, but for the left side.
        :type left_margin: float
        :param right_margin: same as top_margin, but for the right side.
        :type right_margin: float
        :param horizontal_fill: The proportion of the grid space user by the roi, horizontally (between 0 and 1).
        :type horizontal_fill: float
        :param vertical_fill: same as vertical_fill, but horizontally.
        :type vertical_fill: float
        :param enable_diagnostics: Enable detailed diagnostic logging and image collection.
        :type enable_diagnostics: bool
        :param device_id: Identifier for the ethoscope device (used in diagnostic filenames).
        :type device_id: str
        :param save_success_images: Whether to save images of successful detections for analysis.
        :type save_success_images: bool
        :param max_detection_attempts: Maximum number of detection attempts with different strategies.
        :type max_detection_attempts: int
        :param enable_frame_averaging: Whether to use frame averaging for noise reduction.
        :type enable_frame_averaging: bool
        """

        self._n_rows = n_rows
        self._n_cols = n_cols
        self._top_margin = top_margin
        self._bottom_margin = bottom_margin
        self._left_margin = left_margin
        self._right_margin = right_margin
        self._horizontal_fill = horizontal_fill
        self._vertical_fill = vertical_fill

        # Diagnostics configuration
        self._enable_diagnostics = enable_diagnostics
        self._save_success_images = save_success_images
        self._diagnostics = None

        # Multi-frame detection configuration
        self._max_detection_attempts = min(
            max_detection_attempts, 3
        )  # Limit to 3 attempts
        self._enable_frame_averaging = enable_frame_averaging
        self._previous_frame = None  # Simple previous frame storage

        if self._enable_diagnostics:
            self._diagnostics = TargetDetectionDiagnostics(device_id=device_id)
            logging.info(f"Target detection diagnostics enabled for device {device_id}")

        # if self._vertical_fill is None:
        #     self._vertical_fill = self._horizontal_fill
        # if self._right_margin is None:
        #     self._right_margin = self._left_margin
        # if self._bottom_margin is None:
        #     self._bottom_margin = self._top_margin

        super(TargetGridROIBuilder, self).__init__()

    def _find_blobs(self, im, scoring_fun):

        if len(im.shape) == 2:
            grey = im

        elif len(im.shape) == 3:
            grey = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)

        rad = int(self._adaptive_med_rad * im.shape[1])
        if rad % 2 == 0:
            rad += 1

        med = np.median(grey)
        scale = 255 / (med)
        cv2.multiply(grey, scale, dst=grey)
        bin = np.copy(grey)
        score_map = np.zeros_like(bin)
        for t in range(0, 255, 5):
            cv2.threshold(grey, t, 255, cv2.THRESH_BINARY_INV, bin)
            if np.count_nonzero(bin) > 0.7 * im.shape[0] * im.shape[1]:
                continue
            if CV_VERSION == 3:
                _, contours, h = cv2.findContours(
                    bin, cv2.RETR_EXTERNAL, CHAIN_APPROX_SIMPLE
                )
            else:
                contours, h = cv2.findContours(
                    bin, cv2.RETR_EXTERNAL, CHAIN_APPROX_SIMPLE
                )

            bin.fill(0)
            for c in contours:
                score = scoring_fun(c, im)
                if score > 0:
                    cv2.drawContours(bin, [c], 0, score, -1)
            cv2.add(bin, score_map, score_map)
        return score_map

    def _make_grid(
        self,
        n_col,
        n_row,
        top_margin=0.0,
        bottom_margin=0.0,
        left_margin=0.0,
        right_margin=0.0,
        horizontal_fill=1.0,
        vertical_fill=1.0,
    ):

        y_positions = (np.arange(n_row) * 2.0 + 1) * (
            1 - top_margin - bottom_margin
        ) / (2 * n_row) + top_margin
        x_positions = (np.arange(n_col) * 2.0 + 1) * (
            1 - left_margin - right_margin
        ) / (2 * n_col) + left_margin
        all_centres = [
            np.array([x, y]) for x, y in itertools.product(x_positions, y_positions)
        ]

        sign_mat = np.array([[-1, -1], [+1, -1], [+1, +1], [-1, +1]])
        xy_size_vec = (
            np.array([horizontal_fill / float(n_col), vertical_fill / float(n_row)])
            / 2.0
        )
        rectangles = [sign_mat * xy_size_vec + c for c in all_centres]
        return rectangles

    def _points_distance(self, pt1, pt2):
        x1, y1 = pt1
        x2, y2 = pt2
        return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def _validate_target_geometry(self, sorted_points, tolerance=0.15):
        """
        Validate that the three targets form the expected right-angle configuration.
        Expected: A (upper-right), B (lower-right), C (lower-left)
        """
        if len(sorted_points) != 3:
            return False

        a, b, c = sorted_points

        # Calculate distances to verify the sorting is correct
        ab_dist = self._points_distance(a, b)
        bc_dist = self._points_distance(b, c)
        ac_dist = self._points_distance(a, c)

        # AC should be the hypotenuse (longest distance)
        max_dist = max(ab_dist, bc_dist, ac_dist)
        if ac_dist != max_dist:
            return False

        # Validate right-angle configuration
        # A should be upper-right relative to B (higher y, similar x)
        # C should be lower-left relative to B (similar y, lower x)

        # Check vertical alignment: A and B should have similar x-coordinates
        x_alignment_tolerance = tolerance * abs(a[0] - c[0])  # relative to width
        if abs(a[0] - b[0]) > x_alignment_tolerance:
            return False

        # Check horizontal alignment: B and C should have similar y-coordinates
        y_alignment_tolerance = tolerance * abs(a[1] - b[1])  # relative to height
        if abs(b[1] - c[1]) > y_alignment_tolerance:
            return False

        # Check aspect ratio consistency (width/height should be reasonable)
        width = abs(b[0] - c[0])
        height = abs(a[1] - b[1])
        if height == 0 or width == 0:
            return False

        aspect_ratio = width / height
        # Expect roughly 1:1 to 3:1 aspect ratio for typical arenas
        if aspect_ratio < 0.3 or aspect_ratio > 4.0:
            return False

        return True

    def _score_targets(self, contour, im):

        area = cv2.contourArea(contour)
        perim = cv2.arcLength(contour, True)

        if perim == 0:
            return 0
        circul = 4 * np.pi * area / perim**2

        if circul < 0.8:  # fixme magic number
            return 0
        return 1

    def _find_target_coordinates(self, img):
        """
        Finds the coordinates of the three blobs on the given img with simplified multi-attempt detection
        """
        start_time = time.time() if self._enable_diagnostics else None

        # Try simplified detection with up to 3 attempts
        for attempt in range(self._max_detection_attempts):
            logging.debug(
                f"Target detection attempt {attempt + 1}/{self._max_detection_attempts}"
            )

            # Use frame averaging on second attempt if enabled
            if (
                attempt == 1
                and self._enable_frame_averaging
                and self._previous_frame is not None
            ):
                # Simple 2-frame average
                processed_img = (
                    (img.astype(np.float32) + self._previous_frame.astype(np.float32))
                    / 2
                ).astype(np.uint8)
            else:
                processed_img = img

            # Attempt detection on processed image
            result = self._single_detection_attempt(processed_img, attempt)

            if result is not None:
                # Success - log and return
                if self._enable_diagnostics:
                    processing_time = time.time() - start_time if start_time else None
                    self._log_detection_result(
                        processed_img, result, True, attempt, processing_time
                    )
                return result

        # Store current frame for next detection
        if self._enable_frame_averaging:
            self._previous_frame = img.copy()

        # All attempts failed
        if self._enable_diagnostics:
            processing_time = time.time() - start_time if start_time else None
            self._log_detection_result(
                img, None, False, self._max_detection_attempts - 1, processing_time
            )

        logging.error(
            f"Target detection failed after {self._max_detection_attempts} attempts"
        )
        return None

    def _single_detection_attempt(self, img, attempt):
        """
        Perform a single detection attempt with geometric validation
        """
        map = self._find_blobs(img, self._score_targets)
        bin = np.zeros_like(map)

        # Find threshold that gives exactly 3 high-quality, geometrically valid targets
        for t in range(0, 255, 1):
            cv2.threshold(map, t, 255, cv2.THRESH_BINARY, bin)
            if CV_VERSION == 3:
                _, contours, h = cv2.findContours(
                    bin, cv2.RETR_EXTERNAL, CHAIN_APPROX_SIMPLE
                )
            else:
                contours, h = cv2.findContours(
                    bin, cv2.RETR_EXTERNAL, CHAIN_APPROX_SIMPLE
                )

            # Only proceed if we have exactly 3 contours
            if len(contours) != 3:
                continue

            # Verify circular quality
            quality_scores = [self._score_targets(c, img) for c in contours]
            if not all(score > 0 for score in quality_scores):
                continue

            # Check diameter consistency (fixed tolerance)
            target_diams = [cv2.boundingRect(c)[2] for c in contours]
            mean_diam = np.mean(target_diams)
            mean_sd = np.std(target_diams)
            diameter_variation = mean_sd / mean_diam if mean_diam > 0 else 1.0
            if diameter_variation > 0.15:  # Fixed 15% tolerance
                continue

            # Extract and sort target coordinates
            src_points = []
            for c in contours:
                moms = cv2.moments(c)
                x, y = moms["m10"] / moms["m00"], moms["m01"] / moms["m00"]
                src_points.append((x, y))

            # Sort points: A (upper-right), B (lower-right), C (lower-left)
            a, b, c = src_points
            pairs = [(a, b), (b, c), (a, c)]
            dists = [self._points_distance(*p) for p in pairs]
            hypo_vertices = pairs[np.argmax(dists)]  # AC should be longest

            # Find B (not in AC pair)
            for sp in src_points:
                if sp not in hypo_vertices:
                    break
            sorted_b = sp

            # Find C (point with largest distance from B, excluding B itself)
            dist = 0
            for sp in src_points:
                if sorted_b is sp:
                    continue
                if self._points_distance(sp, sorted_b) > dist:
                    dist = self._points_distance(sp, sorted_b)
                    sorted_c = sp

            # A is the remaining point
            sorted_a = [
                sp for sp in src_points if sp is not sorted_b and sp is not sorted_c
            ][0]
            sorted_src_pts = np.array([sorted_a, sorted_b, sorted_c], dtype=np.float32)

            # Validate geometry - this is the key improvement
            geometric_tolerance = 0.10 + (attempt * 0.05)  # Modest tolerance increase
            if self._validate_target_geometry(sorted_src_pts, geometric_tolerance):
                logging.debug(
                    f"Found valid target geometry at threshold {t} (attempt {attempt + 1})"
                )
                return sorted_src_pts
            else:
                logging.debug(
                    f"Invalid geometry at threshold {t} (attempt {attempt + 1})"
                )

        # No valid configuration found
        logging.debug(f"No geometrically valid targets found on attempt {attempt + 1}")
        return None

    def _log_detection_result(self, img, result, success, attempt, processing_time):
        """
        Consolidated logging for both successful and failed detection attempts
        """
        if not self._enable_diagnostics or not self._diagnostics:
            return

        if success and result is not None:
            target_coordinates = [(float(pt[0]), float(pt[1])) for pt in result]
            logging.info(
                f"Target detection SUCCESS on attempt {attempt + 1}: Found 3/3 targets"
            )
        else:
            target_coordinates = []

        metadata = self._diagnostics.log_detection_attempt(
            image=img,
            targets_found=target_coordinates,
            expected_targets=3,
            threshold_used=None,
            circularity_scores=[],
            processing_time=processing_time,
        )

        # Add simplified metadata
        metadata["detection_attempts"] = (
            attempt + 1 if success else self._max_detection_attempts
        )
        metadata["used_frame_averaging"] = (
            self._enable_frame_averaging and self._previous_frame is not None
        )
        metadata["geometric_validation"] = True

        # Save diagnostic images based on success and configuration
        if (success and self._save_success_images) or (not success):
            self._diagnostics.save_detection_image(
                image=img,
                metadata=metadata,
                save_success=success,
                save_failed=not success,
            )

    def _rois_from_img(self, img):
        """
        Fit a ROI to the provided img
        """

        reference_points = self._find_target_coordinates(img)

        # Handle graceful failure when target detection fails
        if reference_points is None:
            logging.warning("ROI building failed: could not detect required targets")
            return None, None

        # point 1 is the reference point at coords A,B; point 0 will be A,y and point 2 x,B
        # we then transform the ROIS on the assumption that those points are aligned perpendicularly in this way
        dst_points = np.array([(0, -1), (0, 0), (-1, 0)], dtype=np.float32)

        wrap_mat = cv2.getAffineTransform(dst_points, reference_points)

        rectangles = self._make_grid(
            self._n_cols,
            self._n_rows,
            self._top_margin,
            self._bottom_margin,
            self._left_margin,
            self._right_margin,
            self._horizontal_fill,
            self._vertical_fill,
        )

        shift = (
            np.dot(wrap_mat, [1, 1, 0]) - reference_points[1]
        )  # point 1 is the ref which we have set at 0,0

        rois = []
        for i, r in enumerate(rectangles):
            r = np.append(r, np.zeros((4, 1)), axis=1)
            mapped_rectangle = np.dot(wrap_mat, r.T).T
            mapped_rectangle -= shift
            ct = mapped_rectangle.reshape((1, 4, 2)).astype(np.int32)
            cv2.drawContours(img, [ct], -1, (255, 0, 0), 1, LINE_AA)
            rois.append(ROI(ct, idx=i + 1))

        # rois is an array of ROI objects
        # reference points is an array containing the abslolute coordinates of the three refs

        return reference_points, rois
