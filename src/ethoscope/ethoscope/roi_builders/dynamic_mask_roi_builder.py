"""
Dynamic Mask ROI Builder for real-time mask creation and editing.

This module provides the DynamicMaskROIBuilder class that allows users to create
custom ROI masks interactively by detecting targets once and then allowing
real-time manipulation of ROI parameters while streaming video.
"""

__author__ = 'ethoscope_team'

import cv2
import logging
import time
import json
import numpy as np
from typing import Optional, Tuple, List, Dict, Any
from collections import OrderedDict

from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.core.roi import ROI
from ethoscope.utils.debug import EthoscopeException


class DynamicMaskROIBuilder(TargetGridROIBuilder):
    """
    A dynamic ROI builder for interactive mask creation.
    
    This class extends TargetGridROIBuilder to provide real-time ROI manipulation
    capabilities for creating custom masks. It detects targets once at startup
    and then allows dynamic adjustment of ROI parameters without re-running
    target detection.
    """
    
    _description = {
        "overview": "Interactive mask creation with real-time ROI manipulation. "
                   "Detects targets once and allows dynamic parameter adjustment.",
        "arguments": [
            {"type": "number", "min": 1, "max": 16, "step": 1, "name": "n_cols", 
             "description": "The number of columns", "default": 2},
            {"type": "number", "min": 1, "max": 16, "step": 1, "name": "n_rows", 
             "description": "The number of rows", "default": 10},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.001, "name": "top_margin", 
             "description": "The vertical distance between the middle of the top ROIs and the middle of the top target.", "default": 0.0},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.001, "name": "bottom_margin", 
             "description": "Same as top_margin, but for the bottom.", "default": 0.0},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.001, "name": "right_margin", 
             "description": "Same as top_margin, but for the right.", "default": 0.0},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.001, "name": "left_margin", 
             "description": "Same as top_margin, but for the left.", "default": 0.0},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.001, "name": "horizontal_fill", 
             "description": "The proportion of the grid space used by the roi, horizontally.", "default": 0.90},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.001, "name": "vertical_fill", 
             "description": "Same as horizontal_margin, but vertically.", "default": 0.90}
        ]
    }

    def __init__(self, n_rows=10, n_cols=2, top_margin=0, bottom_margin=0,
                 left_margin=0, right_margin=0, horizontal_fill=0.9, vertical_fill=0.9,
                 enable_diagnostics=False, device_id="unknown", save_success_images=False,
                 max_detection_attempts=5, enable_frame_averaging=True):
        """
        Initialize the DynamicMaskROIBuilder.
        
        Parameters match TargetGridROIBuilder with additional functionality for
        dynamic mask creation and real-time parameter updates.
        """
        super().__init__(
            n_rows=n_rows, n_cols=n_cols, top_margin=top_margin, bottom_margin=bottom_margin,
            left_margin=left_margin, right_margin=right_margin, 
            horizontal_fill=horizontal_fill, vertical_fill=vertical_fill,
            enable_diagnostics=enable_diagnostics, device_id=device_id,
            save_success_images=save_success_images, max_detection_attempts=max_detection_attempts,
            enable_frame_averaging=enable_frame_averaging
        )
        
        # Dynamic mask creation state
        self._stored_target_coordinates = None
        self._targets_detected = False
        self._current_rois = []
        self._mask_creation_active = False
        
        logging.info(f"DynamicMaskROIBuilder initialized for device {device_id}")

    def detect_targets_once(self, img):
        """
        Run target detection once and store the results for future ROI generation.
        
        Args:
            img: Input image for target detection
            
        Returns:
            bool: True if targets were successfully detected, False otherwise
        """
        if self._targets_detected:
            logging.debug("Targets already detected, using stored coordinates")
            return True
            
        logging.info("Starting one-time target detection for mask creation")
        logging.info(f"Input image shape: {img.shape if hasattr(img, 'shape') else 'No shape available'}")
        start_time = time.time()
        
        try:
            # Use parent class target detection
            target_coordinates = self._find_target_coordinates(img)
            logging.info(f"Target detection result: {target_coordinates}")
            
            if target_coordinates is not None and len(target_coordinates) >= 3:
                self._stored_target_coordinates = target_coordinates
                self._targets_detected = True
                self._mask_creation_active = True
                
                detection_time = time.time() - start_time
                logging.info(f"Target detection completed successfully in {detection_time:.2f}s")
                logging.info(f"Detected targets at coordinates: {target_coordinates.tolist()}")
                
                # Generate initial ROIs with current parameters
                self._generate_rois_from_stored_targets()
                return True
            else:
                logging.error(f"Target detection failed - insufficient targets found. Got {len(target_coordinates) if target_coordinates is not None else 0} targets, need 3")
                return False
                
        except Exception as e:
            logging.error(f"Error during target detection: {e}")
            return False

    def _generate_rois_from_stored_targets(self):
        """
        Generate ROIs using stored target coordinates and current parameters.
        
        Returns:
            tuple: (reference_points, rois) where reference_points are the stored 
                   target coordinates and rois is a list of ROI objects
        """
        if not self._targets_detected or self._stored_target_coordinates is None:
            raise EthoscopeException("Targets not detected yet. Call detect_targets_once() first.")
        
        # Use the same transformation logic as parent class but with stored coordinates
        reference_points = self._stored_target_coordinates
        
        # Transform coordinates for ROI generation
        dst_points = np.array([(0, -1), (0, 0), (-1, 0)], dtype=np.float32)
        wrap_mat = cv2.getAffineTransform(dst_points, reference_points)
        
        # Generate grid with current parameters
        rectangles = self._make_grid(
            self._n_cols, self._n_rows,
            self._top_margin, self._bottom_margin,
            self._left_margin, self._right_margin,
            self._horizontal_fill, self._vertical_fill
        )
        
        shift = np.dot(wrap_mat, [1, 1, 0]) - reference_points[1]
        
        rois = []
        for i, r in enumerate(rectangles):
            r = np.append(r, np.zeros((4, 1)), axis=1)
            mapped_rectangle = np.dot(wrap_mat, r.T).T
            mapped_rectangle -= shift
            ct = mapped_rectangle.reshape((1, 4, 2)).astype(np.int32)
            rois.append(ROI(ct, idx=i+1))
        
        self._current_rois = rois
        logging.debug(f"Generated {len(rois)} ROIs from stored target coordinates")
        
        return reference_points, rois

    def update_roi_parameters(self, params):
        """
        Update ROI parameters and regenerate ROIs using stored target coordinates.
        
        Args:
            params (dict): Dictionary containing ROI parameters to update.
                          Supported keys: n_rows, n_cols, top_margin, bottom_margin,
                          left_margin, right_margin, horizontal_fill, vertical_fill
        
        Returns:
            tuple: (reference_points, rois) with updated ROI configuration
            
        Raises:
            EthoscopeException: If targets haven't been detected yet
        """
        if not self._targets_detected:
            raise EthoscopeException("Cannot update ROI parameters: targets not detected yet")
        
        # Update parameters
        if 'n_rows' in params:
            self._n_rows = max(1, min(16, int(params['n_rows'])))
        if 'n_cols' in params:
            self._n_cols = max(1, min(16, int(params['n_cols'])))
        if 'top_margin' in params:
            self._top_margin = max(0.0, min(1.0, float(params['top_margin'])))
        if 'bottom_margin' in params:
            self._bottom_margin = max(0.0, min(1.0, float(params['bottom_margin'])))
        if 'left_margin' in params:
            self._left_margin = max(0.0, min(1.0, float(params['left_margin'])))
        if 'right_margin' in params:
            self._right_margin = max(0.0, min(1.0, float(params['right_margin'])))
        if 'horizontal_fill' in params:
            self._horizontal_fill = max(0.0, min(1.0, float(params['horizontal_fill'])))
        if 'vertical_fill' in params:
            self._vertical_fill = max(0.0, min(1.0, float(params['vertical_fill'])))
        
        logging.debug(f"Updated ROI parameters: {params}")
        
        # Regenerate ROIs with new parameters
        return self._generate_rois_from_stored_targets()

    def get_current_rois_as_template(self):
        """
        Export current ROI configuration as a template dictionary.
        
        Returns:
            dict: Template data compatible with ROITemplate system
        """
        if not self._targets_detected:
            raise EthoscopeException("Cannot export template: targets not detected yet")
        
        template_data = {
            "template_info": {
                "name": "custom_dynamic_mask",
                "version": "1.0",
                "description": "Custom mask created with DynamicMaskROIBuilder",
                "author": "ethoscope_user",
                "created_timestamp": time.time(),
                "hardware_type": "ethoscope_standard"
            },
            "roi_definition": {
                "type": "grid_with_targets",
                "grid": {
                    "n_rows": self._n_rows,
                    "n_cols": self._n_cols,
                    "orientation": "vertical"
                },
                "alignment": {
                    "target_detection": True,
                    "expected_targets": 3,
                    "adaptive_radius": self._adaptive_med_rad,
                    "min_target_distance": self._expected__min_target_dist
                },
                "positioning": {
                    "margins": {
                        "top": self._top_margin,
                        "bottom": self._bottom_margin,
                        "left": self._left_margin,
                        "right": self._right_margin
                    },
                    "fill_ratios": {
                        "horizontal": self._horizontal_fill,
                        "vertical": self._vertical_fill
                    }
                },
                "target_coordinates": self._stored_target_coordinates.tolist() if self._stored_target_coordinates is not None else None
            }
        }
        
        logging.info("Exported current ROI configuration as template")
        return template_data

    def apply_roi_template(self, template_data):
        """
        Apply a template configuration to the current mask builder.
        
        Args:
            template_data (dict): Template data to apply
            
        Returns:
            bool: True if template was applied successfully
        """
        try:
            roi_def = template_data.get('roi_definition', {})
            
            # Apply grid parameters
            grid = roi_def.get('grid', {})
            self._n_rows = grid.get('n_rows', self._n_rows)
            self._n_cols = grid.get('n_cols', self._n_cols)
            
            # Apply positioning parameters
            positioning = roi_def.get('positioning', {})
            margins = positioning.get('margins', {})
            fill_ratios = positioning.get('fill_ratios', {})
            
            self._top_margin = margins.get('top', self._top_margin)
            self._bottom_margin = margins.get('bottom', self._bottom_margin)
            self._left_margin = margins.get('left', self._left_margin)
            self._right_margin = margins.get('right', self._right_margin)
            self._horizontal_fill = fill_ratios.get('horizontal', self._horizontal_fill)
            self._vertical_fill = fill_ratios.get('vertical', self._vertical_fill)
            
            # If template contains target coordinates, use them
            target_coords = roi_def.get('target_coordinates')
            if target_coords:
                self._stored_target_coordinates = np.array(target_coords, dtype=np.float32)
                self._targets_detected = True
                self._mask_creation_active = True
                
            # Regenerate ROIs if targets are available
            if self._targets_detected:
                self._generate_rois_from_stored_targets()
                
            logging.info("Applied ROI template successfully")
            return True
            
        except Exception as e:
            logging.error(f"Error applying ROI template: {e}")
            return False

    def get_current_parameters(self):
        """
        Get current ROI parameters as a dictionary.
        
        Returns:
            dict: Current parameter values
        """
        return {
            'n_rows': self._n_rows,
            'n_cols': self._n_cols,
            'top_margin': self._top_margin,
            'bottom_margin': self._bottom_margin,
            'left_margin': self._left_margin,  
            'right_margin': self._right_margin,
            'horizontal_fill': self._horizontal_fill,
            'vertical_fill': self._vertical_fill,
            'targets_detected': self._targets_detected,
            'mask_creation_active': self._mask_creation_active
        }

    def draw_roi_overlay(self, img):
        """
        Draw ROI overlay on the provided image for visualization.
        
        Args:
            img: Image to draw overlay on (will be modified in place)
            
        Returns:
            img: Image with ROI overlay drawn
        """
        if not self._targets_detected or not self._current_rois:
            # Draw target detection status
            cv2.putText(img, "Detecting targets...", (10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            return img
        
        # Draw target points
        if self._stored_target_coordinates is not None:
            for i, pt in enumerate(self._stored_target_coordinates):
                x, y = int(pt[0]), int(pt[1])
                cv2.circle(img, (x, y), 8, (0, 255, 0), 2)  # Green circles for targets
                cv2.putText(img, f"T{i+1}", (x+10, y+10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Draw ROI boundaries
        for i, roi in enumerate(self._current_rois):
            # Get ROI contour points
            contour = roi.polygon.astype(np.int32)
            cv2.drawContours(img, [contour], -1, (255, 0, 0), 2)  # Blue ROI boundaries
            
            # Draw ROI number
            center = np.mean(contour, axis=0).astype(int)
            cv2.putText(img, str(i+1), (center[0]-10, center[1]+5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        
        # Draw status info
        status_text = f"ROIs: {len(self._current_rois)} ({self._n_rows}x{self._n_cols})"
        cv2.putText(img, status_text, (10, img.shape[0] - 20), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return img

    def _rois_from_img(self, img):
        """
        Override parent method to use stored target coordinates or detect once.
        
        Args:
            img: Input image
            
        Returns:
            tuple: (reference_points, rois) or (None, None) if detection fails
        """
        if not self._targets_detected:
            # First time - detect targets
            if not self.detect_targets_once(img):
                logging.warning("Target detection failed in _rois_from_img")
                return None, None
        
        # Use stored coordinates to generate ROIs
        return self._generate_rois_from_stored_targets()

    def is_mask_creation_active(self):
        """Check if mask creation mode is active."""
        return self._mask_creation_active
    
    def reset_detection(self):
        """Reset target detection state to allow re-detection."""
        self._stored_target_coordinates = None
        self._targets_detected = False
        self._current_rois = []
        self._mask_creation_active = False
        logging.info("Reset target detection state")