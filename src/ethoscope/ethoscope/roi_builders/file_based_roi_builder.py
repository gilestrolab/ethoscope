"""
File-based ROI builder for loading ROI configurations from external JSON templates.

This module provides the FileBasedROIBuilder class that replaces hardcoded ROI parameters
with external template files, allowing users to create and modify ROI configurations.
"""

import os
import warnings
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from ethoscope.core.roi import ROI
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.roi_builders.template import ROITemplate
from ethoscope.roi_builders.template import ROITemplateValidationError


class FileBasedROIBuilder(BaseROIBuilder):
    """
    ROI builder that loads configurations from external JSON template files.

    This class replaces hardcoded ROI configurations with flexible external templates
    that can be created, modified, and shared by users.
    """

    _description = {}

    def __init__(
        self,
        template_file: Optional[str] = None,
        template_name: Optional[str] = "sleep_monitor_20tube",
        template_data: Optional[Dict[str, Any]] = None,
        template_id: Optional[str] = None,
    ):
        """
        Initialize file-based ROI builder.

        Args:
            template_file: Path to JSON template file
            template_name: Name of builtin template (defaults to sleep_monitor_20tube)
            template_data: Template data as dictionary (for programmatic use)
            template_id: MD5 ID of template (for template lookup by ID)

        Raises:
            ValueError: If no template source is provided or multiple sources are provided
            ROITemplateValidationError: If template is invalid
        """
        super().__init__()

        # Prioritize template sources: template_data > template_file > template_id > template_name
        if template_data is not None:
            self.template_file = None
            self.template_name = None
            self.template_data = template_data
            self.template_id = None
        elif template_file is not None:
            self.template_file = template_file
            self.template_name = None
            self.template_data = None
            self.template_id = None
        elif template_id is not None:
            self.template_file = None
            self.template_name = None
            self.template_data = None
            self.template_id = template_id
        else:
            # Default to template_name (builtin template)
            self.template_file = None
            self.template_name = (
                template_name if template_name else "sleep_monitor_20tube"
            )
            self.template_data = None
            self.template_id = None

        self.template = None

        # Load the template
        self._load_template()

    def _load_template(self):
        """Load template from the specified source."""
        try:
            if self.template_data:
                self.template = ROITemplate.load(self.template_data)

            elif self.template_file:
                if not os.path.exists(self.template_file):
                    raise FileNotFoundError(
                        f"Template file not found: {self.template_file}"
                    )
                self.template = ROITemplate.load(self.template_file)

            elif self.template_id:
                # Load template by ID (MD5)
                from ethoscope.utils.roi_template_manager import ROITemplateManager

                manager = ROITemplateManager()
                self.template = manager.load_template_by_id(self.template_id)

            elif self.template_name:
                # Load using the new builtin/custom structure
                from ethoscope.utils.roi_template_manager import ROITemplateManager

                manager = ROITemplateManager()
                self.template = manager.load_template(self.template_name)

        except Exception as e:
            raise ROITemplateValidationError(f"Failed to load ROI template: {str(e)}")

    def build(self, camera):
        """
        Build ROIs using the loaded template.

        Args:
            camera: Camera instance to get dimensions and capture frames

        Returns:
            Tuple of (reference_points, rois) to match BaseROIBuilder interface

        Raises:
            ROITemplateValidationError: If ROI generation fails
        """
        if self.template is None:
            raise ROITemplateValidationError("No template loaded")

        try:
            # Generate ROIs and get reference points from template
            # For grid-based templates, this will detect the three target coordinates
            result = self.template.generate_rois(camera)

            if isinstance(result, tuple) and len(result) == 2:
                # Template returned (reference_points, rois) - use these reference points
                reference_points, rois = result
            else:
                # Template returned just rois - fall back to basic reference points
                rois = result
                reference_points = self._generate_basic_reference_points(camera)

            # Validate generated ROIs
            self._validate_generated_rois(rois, camera)

            return reference_points, rois

        except Exception as e:
            raise ROITemplateValidationError(
                f"Failed to generate ROIs from template: {str(e)}"
            )

    def _generate_basic_reference_points(self, camera):
        """Generate basic reference points as fallback when target detection is not available."""
        import numpy as np

        # Acquire frames and build reference image (similar to BaseROIBuilder)
        accum = []
        for i, (_, frame) in enumerate(camera):
            accum.append(frame)
            if i >= 5:
                break

        if accum:
            reference_points = np.median(np.array(accum), 0).astype(np.uint8)
        else:
            # Fallback: try to get a single frame from iterator
            try:
                _, frame = next(iter(camera))
                reference_points = frame
            except (StopIteration, Exception):
                # Last resort: create a default reference frame
                reference_points = np.zeros((480, 640), dtype=np.uint8)

        return reference_points

    def _validate_generated_rois(self, rois: List[ROI], camera):
        """
        Validate that generated ROIs are reasonable.

        Args:
            rois: List of generated ROIs
            camera: Camera instance

        Raises:
            ROITemplateValidationError: If validation fails
        """
        if not rois:
            raise ROITemplateValidationError("Template generated no ROIs")

        # Get camera dimensions by capturing a frame
        frame = None
        try:
            # Try to get a frame from the camera iterator
            _, frame = next(iter(camera))
        except (StopIteration, Exception):
            # Can't validate without frame, but don't fail
            warnings.warn("Could not capture frame for ROI validation")
            return

        img_height, img_width = frame.shape[:2]

        # Check template validation rules if specified
        validation = self.template.data.get("validation", {})
        min_area = validation.get("min_roi_area", 0)
        max_overlap = validation.get("max_roi_overlap", 1.0)

        # Validate each ROI
        for i, roi in enumerate(rois):
            # Check ROI is within image bounds
            x, y, w, h = roi.rectangle
            if x < 0 or y < 0 or x + w > img_width or y + h > img_height:
                warnings.warn(f"ROI {i} extends outside image bounds")

            # Check minimum area (calculate from rectangle dimensions)
            roi_area = w * h
            if roi_area < min_area:
                warnings.warn(f"ROI {i} area ({roi_area}) below minimum ({min_area})")

        # Check overlap if specified
        if max_overlap < 1.0:
            self._check_roi_overlap(rois, max_overlap)

    def _check_roi_overlap(self, rois: List[ROI], max_overlap: float):
        """Check for excessive ROI overlap."""

        # Create masks for each ROI
        if not rois:
            return

        # Get image dimensions from first ROI
        x, y, w, h = rois[0].rectangle
        img_height = max(roi.rectangle[1] + roi.rectangle[3] for roi in rois)
        img_width = max(roi.rectangle[0] + roi.rectangle[2] for roi in rois)

        for i in range(len(rois)):
            for j in range(i + 1, len(rois)):
                roi1, roi2 = rois[i], rois[j]

                # Calculate overlap using intersection of rectangles
                x1, y1, w1, h1 = roi1.rectangle
                x2, y2, w2, h2 = roi2.rectangle

                # Calculate intersection
                left = max(x1, x2)
                right = min(x1 + w1, x2 + w2)
                top = max(y1, y2)
                bottom = min(y1 + h1, y2 + h2)

                if left < right and top < bottom:
                    intersection_area = (right - left) * (bottom - top)
                    union_area = w1 * h1 + w2 * h2 - intersection_area
                    overlap_ratio = (
                        intersection_area / union_area if union_area > 0 else 0
                    )

                    if overlap_ratio > max_overlap:
                        warnings.warn(
                            f"ROI {i} and {j} overlap ratio ({overlap_ratio:.3f}) exceeds maximum ({max_overlap})"
                        )

    def get_template_info(self) -> Dict[str, Any]:
        """
        Get information about the loaded template.

        Returns:
            Dictionary with template metadata
        """
        if self.template is None:
            return {}

        return {
            "name": self.template.name,
            "version": self.template.version,
            "description": self.template.description,
            "source": self.template_file or self.template_name or "inline_data",
        }

    def to_legacy_params(self) -> Dict[str, Any]:
        """
        Convert template to legacy ROI builder parameters.

        This is useful for backward compatibility with existing code
        that expects legacy parameter formats.

        Returns:
            Dictionary of legacy parameters
        """
        if self.template is None:
            return {}

        return self.template.to_legacy_params()


# Convenience functions for common use cases


def create_from_builtin(template_name: str) -> FileBasedROIBuilder:
    """
    Create FileBasedROIBuilder using a builtin template.

    Args:
        template_name: Name of builtin template

    Returns:
        FileBasedROIBuilder instance
    """
    return FileBasedROIBuilder(template_name=template_name)


def create_from_file(template_file: str) -> FileBasedROIBuilder:
    """
    Create FileBasedROIBuilder from template file.

    Args:
        template_file: Path to template JSON file

    Returns:
        FileBasedROIBuilder instance
    """
    return FileBasedROIBuilder(template_file=template_file)


def create_from_legacy_builder(
    legacy_builder_class, **legacy_params
) -> FileBasedROIBuilder:
    """
    Create FileBasedROIBuilder from legacy builder class and parameters.

    This function helps migrate from hardcoded builders to template-based ones.

    Args:
        legacy_builder_class: Legacy ROI builder class
        **legacy_params: Legacy builder parameters

    Returns:
        FileBasedROIBuilder instance with equivalent template
    """
    from ethoscope.utils.roi_template_manager import convert_legacy_to_template

    template_data = convert_legacy_to_template(legacy_builder_class, **legacy_params)
    return FileBasedROIBuilder(template_data=template_data)
