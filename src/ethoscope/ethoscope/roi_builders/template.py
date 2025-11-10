"""
ROI Template system for external configuration of ROI definitions.

This module provides the ROITemplate class that allows loading ROI configurations
from external JSON files, replacing hardcoded parameters in ROI builders.
"""

import json
import os
import numpy as np
import cv2
from typing import Dict, List, Union, Optional, Any
import warnings

from ethoscope.core.roi import ROI


class ROITemplateValidationError(Exception):
    """Raised when ROI template validation fails."""

    pass


class ROITemplate:
    """
    A template for defining ROI configurations externally.

    Supports loading from JSON files and generating ROIs based on template parameters.
    """

    # JSON Schema for template validation
    TEMPLATE_SCHEMA = {
        "type": "object",
        "required": ["template_info", "roi_definition"],
        "properties": {
            "template_info": {
                "type": "object",
                "required": ["name", "version"],
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "string"},
                    "description": {"type": "string"},
                    "author": {"type": "string"},
                    "hardware_type": {"type": "string"},
                },
            },
            "roi_definition": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {
                        "enum": ["grid_with_targets", "manual_polygons", "image_mask"]
                    },
                    "grid": {
                        "type": "object",
                        "properties": {
                            "n_rows": {"type": "integer", "minimum": 1},
                            "n_cols": {"type": "integer", "minimum": 1},
                            "orientation": {"enum": ["vertical", "horizontal"]},
                        },
                    },
                    "alignment": {
                        "type": "object",
                        "properties": {
                            "target_detection": {"type": "boolean"},
                            "expected_targets": {"type": "integer", "minimum": 0},
                            "adaptive_radius": {"type": "number", "minimum": 0},
                            "min_target_distance": {"type": "number", "minimum": 0},
                        },
                    },
                    "positioning": {
                        "type": "object",
                        "properties": {
                            "margins": {
                                "type": "object",
                                "properties": {
                                    "top": {"type": "number"},
                                    "bottom": {"type": "number"},
                                    "left": {"type": "number"},
                                    "right": {"type": "number"},
                                },
                            },
                            "fill_ratios": {
                                "type": "object",
                                "properties": {
                                    "horizontal": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                    "vertical": {
                                        "type": "number",
                                        "minimum": 0,
                                        "maximum": 1,
                                    },
                                },
                            },
                        },
                    },
                    "roi_shapes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type"],
                            "properties": {
                                "type": {"enum": ["rectangle", "ellipse", "polygon"]},
                                "grid_position": {
                                    "type": "object",
                                    "properties": {
                                        "row": {
                                            "oneOf": [
                                                {"type": "integer"},
                                                {"const": "all"},
                                            ]
                                        },
                                        "col": {
                                            "oneOf": [
                                                {"type": "integer"},
                                                {"const": "all"},
                                            ]
                                        },
                                    },
                                },
                                "parameters": {"type": "object"},
                            },
                        },
                    },
                    "manual_rois": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["polygon"],
                            "properties": {
                                "polygon": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                },
                                "value": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            "validation": {
                "type": "object",
                "properties": {
                    "min_roi_area": {"type": "number", "minimum": 0},
                    "max_roi_overlap": {"type": "number", "minimum": 0, "maximum": 1},
                    "required_targets": {"type": "integer", "minimum": 0},
                },
            },
        },
    }

    def __init__(self, template_data: Dict[str, Any]):
        """
        Initialize ROI template.

        Args:
            template_data: Dictionary containing template configuration
        """
        self.data = template_data
        self._validate()

    @classmethod
    def load(cls, source: Union[str, Dict[str, Any]]) -> "ROITemplate":
        """
        Load template from file path or dictionary.

        Args:
            source: File path to JSON template or dictionary with template data

        Returns:
            ROITemplate instance

        Raises:
            FileNotFoundError: If template file doesn't exist
            json.JSONDecodeError: If JSON is invalid
            ROITemplateValidationError: If template doesn't match schema
        """
        if isinstance(source, str):
            if not os.path.exists(source):
                raise FileNotFoundError(f"Template file not found: {source}")
            with open(source, "r") as f:
                template_data = json.load(f)
        elif isinstance(source, dict):
            template_data = source.copy()
        else:
            raise TypeError("Source must be file path string or dictionary")

        return cls(template_data)

    def _validate(self):
        """Validate template against schema."""
        try:
            # Basic structure validation
            if not isinstance(self.data, dict):
                raise ROITemplateValidationError("Template must be a dictionary")

            if "template_info" not in self.data:
                raise ROITemplateValidationError(
                    "Missing required field: template_info"
                )

            if "roi_definition" not in self.data:
                raise ROITemplateValidationError(
                    "Missing required field: roi_definition"
                )

            # Validate template_info
            info = self.data["template_info"]
            if not isinstance(info.get("name"), str):
                raise ROITemplateValidationError("template_info.name must be a string")
            if not isinstance(info.get("version"), str):
                raise ROITemplateValidationError(
                    "template_info.version must be a string"
                )

            # Validate roi_definition
            roi_def = self.data["roi_definition"]
            if roi_def.get("type") not in [
                "grid_with_targets",
                "manual_polygons",
                "image_mask",
            ]:
                raise ROITemplateValidationError(
                    "roi_definition.type must be one of: grid_with_targets, manual_polygons, image_mask"
                )

            # Type-specific validation
            if roi_def["type"] == "grid_with_targets":
                self._validate_grid_template(roi_def)
            elif roi_def["type"] == "manual_polygons":
                self._validate_manual_template(roi_def)

        except Exception as e:
            if isinstance(e, ROITemplateValidationError):
                raise
            raise ROITemplateValidationError(f"Template validation failed: {str(e)}")

    def _validate_grid_template(self, roi_def: Dict):
        """Validate grid-based template."""
        if "grid" not in roi_def:
            raise ROITemplateValidationError(
                "grid_with_targets requires 'grid' configuration"
            )

        grid = roi_def["grid"]
        if not isinstance(grid.get("n_rows"), int) or grid["n_rows"] < 1:
            raise ROITemplateValidationError("grid.n_rows must be positive integer")
        if not isinstance(grid.get("n_cols"), int) or grid["n_cols"] < 1:
            raise ROITemplateValidationError("grid.n_cols must be positive integer")

    def _validate_manual_template(self, roi_def: Dict):
        """Validate manual polygon template."""
        if "manual_rois" not in roi_def:
            raise ROITemplateValidationError(
                "manual_polygons requires 'manual_rois' configuration"
            )

        manual_rois = roi_def["manual_rois"]
        if not isinstance(manual_rois, list) or len(manual_rois) == 0:
            raise ROITemplateValidationError("manual_rois must be non-empty list")

        for i, roi in enumerate(manual_rois):
            if "polygon" not in roi:
                raise ROITemplateValidationError(
                    f"manual_rois[{i}] missing 'polygon' field"
                )

            polygon = roi["polygon"]
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise ROITemplateValidationError(
                    f"manual_rois[{i}].polygon must have at least 3 points"
                )

            for j, point in enumerate(polygon):
                if not isinstance(point, list) or len(point) != 2:
                    raise ROITemplateValidationError(
                        f"manual_rois[{i}].polygon[{j}] must be [x, y] coordinate"
                    )
                if not all(isinstance(coord, (int, float)) for coord in point):
                    raise ROITemplateValidationError(
                        f"manual_rois[{i}].polygon[{j}] coordinates must be numbers"
                    )

    def generate_rois(self, camera):
        """
        Generate ROIs based on template configuration.

        Args:
            camera: Camera instance to get dimensions and capture frames

        Returns:
            For grid_with_targets: (reference_points, rois) tuple
            For other types: List of ROI objects
        """
        roi_def = self.data["roi_definition"]

        if roi_def["type"] == "grid_with_targets":
            return self._generate_grid_rois(camera, roi_def)
        elif roi_def["type"] == "manual_polygons":
            return self._generate_manual_rois(camera, roi_def)
        elif roi_def["type"] == "image_mask":
            return self._generate_mask_rois(camera, roi_def)
        else:
            raise ROITemplateValidationError(f"Unsupported ROI type: {roi_def['type']}")

    def _generate_grid_rois(self, camera, roi_def: Dict):
        """Generate ROIs from grid template using target alignment."""
        from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder

        # Extract grid parameters
        grid = roi_def["grid"]
        n_rows = grid["n_rows"]
        n_cols = grid["n_cols"]

        # Extract positioning parameters with defaults
        positioning = roi_def.get("positioning", {})
        margins = positioning.get("margins", {})
        fill_ratios = positioning.get("fill_ratios", {})

        # Extract alignment parameters with defaults
        alignment = roi_def.get("alignment", {})

        # Create legacy TargetGridROIBuilder with template parameters
        builder_params = {
            "n_rows": n_rows,
            "n_cols": n_cols,
            "top_margin": margins.get("top", 0.063),
            "bottom_margin": margins.get("bottom", 0.063),
            "left_margin": margins.get("left", -0.033),
            "right_margin": margins.get("right", -0.033),
            "horizontal_fill": fill_ratios.get("horizontal", 0.975),
            "vertical_fill": fill_ratios.get("vertical", 0.7),
        }

        # Use existing target-based ROI builder with template parameters
        # This detects the three target coordinates and returns (reference_points, rois)
        builder = TargetGridROIBuilder(**builder_params)
        reference_points, rois = builder.build(camera)

        # Return both reference points (detected target coordinates) and ROIs
        return reference_points, rois

    def _generate_manual_rois(self, camera, roi_def: Dict) -> List[ROI]:
        """Generate ROIs from manual polygon definitions."""
        rois = []
        manual_rois = roi_def["manual_rois"]

        for i, roi_data in enumerate(manual_rois):
            polygon = np.array(roi_data["polygon"], dtype=np.float32)
            value = roi_data.get("value", i)

            roi = ROI(polygon, idx=i, value=value)
            rois.append(roi)

        return rois

    def _generate_mask_rois(self, camera, roi_def: Dict) -> List[ROI]:
        """Generate ROIs from image mask."""
        # This would load an image mask and extract contours
        raise NotImplementedError("Image mask ROI generation not yet implemented")

    def to_legacy_params(self) -> Dict[str, Any]:
        """
        Convert template to legacy ROI builder parameters for backward compatibility.

        Returns:
            Dictionary of legacy parameters
        """
        roi_def = self.data["roi_definition"]

        if roi_def["type"] == "grid_with_targets":
            grid = roi_def["grid"]
            positioning = roi_def.get("positioning", {})
            margins = positioning.get("margins", {})
            fill_ratios = positioning.get("fill_ratios", {})

            return {
                "n_rows": grid["n_rows"],
                "n_cols": grid["n_cols"],
                "top_margin": margins.get("top", 0.063),
                "bottom_margin": margins.get("bottom", 0.063),
                "left_margin": margins.get("left", -0.033),
                "right_margin": margins.get("right", -0.033),
                "horizontal_fill": fill_ratios.get("horizontal", 0.975),
                "vertical_fill": fill_ratios.get("vertical", 0.7),
            }
        else:
            return {}

    def save(self, file_path: str):
        """
        Save template to JSON file.

        Args:
            file_path: Path to save template file
        """
        with open(file_path, "w") as f:
            json.dump(self.data, f, indent=2)

    @property
    def name(self) -> str:
        """Get template name."""
        return self.data["template_info"]["name"]

    @property
    def version(self) -> str:
        """Get template version."""
        return self.data["template_info"]["version"]

    @property
    def description(self) -> str:
        """Get template description."""
        return self.data["template_info"].get("description", "")

    def __str__(self) -> str:
        return f"ROITemplate(name='{self.name}', version='{self.version}')"

    def __repr__(self) -> str:
        return self.__str__()
