#!/usr/bin/env python3
"""
ROI Manager for Cupido Offline Tracking (Enhanced)

This module provides utilities for managing JSON ROI templates created by the enhanced
mask_creator.py and provides compatible ROI builders for the offline tracking pipeline.

Usage:
    from roi_manager import CupidoROIManager
    
    manager = CupidoROIManager('results/masks')
    roi_builder = manager.get_roi_builder_for_machine('76')
    reference_points, rois = roi_builder.build(sample_frame)
"""

import os
import json
import sys
from typing import Dict, List, Optional, Tuple
import glob
import numpy as np

# Add ethoscope to path
sys.path.insert(0, '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope')

from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI
import cv2


class TemplateBasedROIBuilder(BaseROIBuilder):
    """
    ROI builder that uses JSON templates with optional manual target override.
    """
    
    def __init__(self, template_data: Dict, manual_targets: np.ndarray = None):
        """
        Initialize with template data and optional manual targets.
        
        Args:
            template_data: JSON template configuration
            manual_targets: Optional manual target coordinates to override detection
        """
        self.template_data = template_data
        self.manual_targets = manual_targets
        
        # Parse template parameters
        roi_def = template_data.get('roi_definition', {})
        grid = roi_def.get('grid', {})
        positioning = roi_def.get('positioning', {})
        margins = positioning.get('margins', {})
        fills = positioning.get('fill_ratios', {})
        
        # Create underlying TargetGridROIBuilder
        self.target_builder = TargetGridROIBuilder(
            n_rows=grid.get('n_rows', 1),
            n_cols=grid.get('n_cols', 1),
            top_margin=margins.get('top', 0),
            bottom_margin=margins.get('bottom', 0),
            left_margin=margins.get('left', 0),
            right_margin=margins.get('right', 0),
            horizontal_fill=fills.get('horizontal', 0.9),
            vertical_fill=fills.get('vertical', 0.9),
            enable_diagnostics=False
        )
        
        super(TemplateBasedROIBuilder, self).__init__()
        
    def _rois_from_img(self, img):
        """Build ROIs using template configuration."""
        if self.manual_targets is not None:
            # Use manual targets - override the detection method
            original_find_targets = self.target_builder._find_target_coordinates
            self.target_builder._find_target_coordinates = lambda image: self.manual_targets
            
            try:
                reference_points, rois = self.target_builder.build(img)
                return reference_points, rois
            finally:
                # Restore original method
                self.target_builder._find_target_coordinates = original_find_targets
        else:
            # Use automatic target detection
            reference_points, rois = self.target_builder.build(img)
            return reference_points, rois


class CupidoROIManager:
    """
    Manager for JSON ROI templates specific to the Cupido project.
    
    Handles loading and managing template files created by the enhanced mask_creator.py tool,
    and provides appropriate ROI builders for different machines.
    """
    
    def __init__(self, templates_dir: str = "results/masks"):
        """
        Initialize the ROI manager.
        
        Args:
            templates_dir: Directory containing JSON template files
        """
        self.templates_dir = templates_dir
        self.available_templates = self._discover_templates()
        
    def _discover_templates(self) -> Dict[str, Dict]:
        """
        Discover available JSON template files and their metadata.
        
        Returns:
            Dictionary mapping machine names to template information
        """
        templates = {}
        
        if not os.path.exists(self.templates_dir):
            return templates
            
        # Find all JSON template files
        json_files = glob.glob(os.path.join(self.templates_dir, "roi_template_machine_*.json"))
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    template_data = json.load(f)
                    
                # Extract machine name from filename
                basename = os.path.basename(json_file)
                parts = basename.replace('.json', '').split('_')
                machine_name = None
                
                # Try to extract machine name from filename
                for i, part in enumerate(parts):
                    if part == 'machine' and i + 1 < len(parts):
                        machine_name = parts[i + 1]
                        break
                        
                if not machine_name:
                    continue
                    
                # Store template information
                template_info = {
                    'template_file': json_file,
                    'template_data': template_data,
                    'machine_name': machine_name,
                    'timestamp': template_data.get('targets', {}).get('timestamp', ''),
                    'roi_count': self._estimate_roi_count(template_data),
                    'has_targets': 'targets' in template_data
                }
                
                # Handle multiple templates per machine (keep newest)
                if machine_name in templates:
                    existing_ts = templates[machine_name]['timestamp']
                    new_ts = template_info['timestamp']
                    if new_ts > existing_ts:
                        templates[machine_name] = template_info
                else:
                    templates[machine_name] = template_info
                    
            except Exception as e:
                print(f"Warning: Failed to load template from {json_file}: {e}")
                
        return templates
        
    def _estimate_roi_count(self, template_data: Dict) -> int:
        """Estimate number of ROIs from template data."""
        roi_def = template_data.get('roi_definition', {})
        grid = roi_def.get('grid', {})
        return grid.get('n_rows', 1) * grid.get('n_cols', 1)
        
    def get_available_machines(self) -> List[str]:
        """Get list of machine names with available templates."""
        return sorted(self.available_templates.keys())
        
    def has_template_for_machine(self, machine_name: str) -> bool:
        """Check if a template is available for the specified machine."""
        return machine_name in self.available_templates
        
    def get_template_info(self, machine_name: str) -> Optional[Dict]:
        """Get template information for a specific machine."""
        return self.available_templates.get(machine_name)
        
    def get_roi_builder_for_machine(self, machine_name: str, 
                                   manual_targets: np.ndarray = None) -> Optional[BaseROIBuilder]:
        """
        Get an appropriate ROI builder for the specified machine.
        
        Args:
            machine_name: Name of the machine/ethoscope
            manual_targets: Optional manual target coordinates to override detection
            
        Returns:
            ROI builder instance or None if no template available
        """
        if not self.has_template_for_machine(machine_name):
            print(f"Warning: No template available for machine {machine_name}")
            return None
            
        template_info = self.get_template_info(machine_name)
        template_data = template_info['template_data']
        
        try:
            # Use stored manual targets from template if available and no override provided
            if manual_targets is None and template_info['has_targets']:
                stored_targets = template_data.get('targets', {}).get('coordinates', [])
                if stored_targets and len(stored_targets) == 3:
                    manual_targets = np.array(stored_targets, dtype=np.float32)
                    print(f"Using stored targets for machine {machine_name}")
                    
            # Create template-based ROI builder
            roi_builder = TemplateBasedROIBuilder(template_data, manual_targets)
            return roi_builder
            
        except Exception as e:
            print(f"Error creating ROI builder for machine {machine_name}: {e}")
            return None
            
    def create_fallback_roi_builder(self, frame_shape: Tuple[int, int]) -> BaseROIBuilder:
        """
        Create a fallback ROI builder that uses the entire frame as one ROI.
        
        Args:
            frame_shape: (height, width) of the video frame
            
        Returns:
            ROI builder that creates one ROI covering the entire frame
        """
        return FullFrameROIBuilder(frame_shape)
        
    def validate_template(self, machine_name: str, test_frame: np.ndarray = None) -> bool:
        """
        Validate that a template works correctly.
        
        Args:
            machine_name: Machine name to test
            test_frame: Optional test frame to use for validation
            
        Returns:
            True if template is valid, False otherwise
        """
        if not self.has_template_for_machine(machine_name):
            return False
            
        try:
            roi_builder = self.get_roi_builder_for_machine(machine_name)
            if roi_builder is None:
                return False
                
            # Create test frame if not provided
            if test_frame is None:
                template_info = self.get_template_info(machine_name)
                test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                
            # Try to build ROIs
            reference_points, rois = roi_builder.build(test_frame)
            
            if rois is None or len(rois) == 0:
                print(f"Template validation failed for {machine_name}: No ROIs found")
                return False
                
            print(f"Template validation successful for {machine_name}: {len(rois)} ROIs found")
            return True
            
        except Exception as e:
            print(f"Template validation failed for {machine_name}: {e}")
            return False
            
    def get_roi_count_for_machine(self, machine_name: str) -> int:
        """Get the expected number of ROIs for a machine."""
        if not self.has_template_for_machine(machine_name):
            return 0
            
        template_info = self.get_template_info(machine_name)
        return template_info['roi_count']
        
    def print_summary(self):
        """Print a summary of available templates."""
        print(f"\n📋 ROI Manager Summary (Enhanced):")
        print(f"Templates directory: {self.templates_dir}")
        print(f"Available machines: {len(self.available_templates)}")
        
        if not self.available_templates:
            print("  No templates found. Use mask_creator.py to create templates first.")
            return
            
        for machine_name, template_info in self.available_templates.items():
            print(f"\nMachine {machine_name}:")
            print(f"  Expected ROIs: {template_info['roi_count']}")
            print(f"  Has stored targets: {'Yes' if template_info['has_targets'] else 'No'}")
            if template_info['timestamp']:
                print(f"  Created: {template_info['timestamp']}")
            print(f"  Template: {os.path.basename(template_info['template_file'])}")
            
            # Validate the template
            is_valid = self.validate_template(machine_name)
            print(f"  Status: {'✓ Valid' if is_valid else '✗ Invalid'}")
            
    def load_builtin_template(self, template_name: str) -> Optional[Dict]:
        """
        Load a built-in template from the ethoscope package.
        
        Args:
            template_name: Name of built-in template (e.g., 'sleep_monitor_20tube')
            
        Returns:
            Template data dictionary or None if not found
        """
        builtin_dir = '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope/ethoscope/roi_builders/roi_templates/builtin'
        template_path = os.path.join(builtin_dir, f"{template_name}.json")
        
        if os.path.exists(template_path):
            try:
                with open(template_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading built-in template {template_name}: {e}")
                
        return None
    
    def load_roi_builder_from_file(self, template_path: str, manual_targets: np.ndarray = None) -> Optional[BaseROIBuilder]:
        """
        Load ROI builder directly from a JSON template file.
        
        Args:
            template_path: Path to JSON template file
            manual_targets: Optional manual target coordinates
            
        Returns:
            TemplateBasedROIBuilder or None if loading failed
        """
        if not os.path.exists(template_path):
            print(f"Template file not found: {template_path}")
            return None
            
        try:
            with open(template_path, 'r') as f:
                template_data = json.load(f)
            
            print(f"Loaded template: {template_data.get('template_info', {}).get('name', 'Unknown')}")
            return TemplateBasedROIBuilder(template_data, manual_targets)
            
        except Exception as e:
            print(f"Error loading template from {template_path}: {e}")
            return None
        
    def save_template_for_machine(self, machine_name: str, template_data: Dict, 
                                 targets: np.ndarray = None) -> str:
        """
        Save a template for a specific machine.
        
        Args:
            machine_name: Machine identifier
            template_data: Template configuration data
            targets: Optional target coordinates
            
        Returns:
            Path to saved template file
        """
        from datetime import datetime
        
        # Add targets if provided
        if targets is not None:
            template_data['targets'] = {
                'coordinates': [[float(t[0]), float(t[1])] for t in targets],
                'detection_method': 'programmatic',
                'timestamp': datetime.now().isoformat()
            }
            
        # Create filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        template_filename = f"roi_template_machine_{machine_name}_{timestamp}.json"
        template_path = os.path.join(self.templates_dir, template_filename)
        
        # Ensure directory exists
        os.makedirs(self.templates_dir, exist_ok=True)
        
        # Save template
        with open(template_path, 'w') as f:
            json.dump(template_data, f, indent=2)
            
        # Refresh templates
        self.available_templates = self._discover_templates()
        
        print(f"Template saved for machine {machine_name}: {template_path}")
        return template_path


class FullFrameROIBuilder(BaseROIBuilder):
    """
    Simple ROI builder that creates one ROI covering the entire frame.
    Used as fallback when no template is available.
    """
    
    def __init__(self, frame_shape: Tuple[int, int]):
        """
        Initialize with frame dimensions.
        
        Args:
            frame_shape: (height, width) of the video frame
        """
        self.frame_shape = frame_shape
        super(FullFrameROIBuilder, self).__init__()
        
    def _rois_from_img(self, img):
        """
        Create a single ROI covering the entire frame.
        
        Args:
            img: Input image/frame
            
        Returns:
            Tuple of (reference_points, rois)
        """
        h, w = img.shape[:2]
        
        # Create contour covering entire frame
        contour = np.array([
            [0, 0],
            [w, 0], 
            [w, h],
            [0, h]
        ], dtype=np.int32).reshape(-1, 1, 2)
        
        # Create ROI with ID 1 and value 1
        roi = ROI(contour, 1, value=1)
        
        # Reference points for full frame (corners)
        reference_points = np.array([
            [0, 0],
            [0, h],
            [w, h]
        ], dtype=np.float32)
        
        return reference_points, [roi]


def main():
    """Test the enhanced ROI manager functionality."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced ROI Manager')
    parser.add_argument('--templates-dir', '-d',
                       default='results/masks',
                       help='Directory containing JSON template files')
    parser.add_argument('--machine', '-m',
                       help='Test specific machine')
    parser.add_argument('--validate', '-v', action='store_true',
                       help='Validate all templates')
    parser.add_argument('--list-builtin', action='store_true',
                       help='List built-in templates')
    
    args = parser.parse_args()
    
    if args.list_builtin:
        # List built-in templates
        builtin_dir = '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope/ethoscope/roi_builders/roi_templates/builtin'
        if os.path.exists(builtin_dir):
            print("Built-in templates:")
            for template_file in glob.glob(os.path.join(builtin_dir, "*.json")):
                template_name = os.path.basename(template_file).replace('.json', '')
                print(f"  {template_name}")
        return
    
    # Create ROI manager
    manager = CupidoROIManager(args.templates_dir)
    
    # Print summary
    manager.print_summary()
    
    if args.machine:
        # Test specific machine
        print(f"\nTesting machine {args.machine}:")
        if manager.has_template_for_machine(args.machine):
            roi_builder = manager.get_roi_builder_for_machine(args.machine)
            if roi_builder:
                print(f"  ROI builder created successfully")
                print(f"  Expected ROIs: {manager.get_roi_count_for_machine(args.machine)}")
            else:
                print(f"  Failed to create ROI builder")
        else:
            print(f"  No template available")
            
    if args.validate:
        # Validate all templates
        print(f"\nValidating all templates:")
        machines = manager.get_available_machines()
        for machine in machines:
            is_valid = manager.validate_template(machine)
            print(f"  Machine {machine}: {'✓ Valid' if is_valid else '✗ Invalid'}")


if __name__ == "__main__":
    main()