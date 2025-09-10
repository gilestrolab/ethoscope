#!/usr/bin/env python3
"""
Interactive ROI Mask Creator for Cupido Offline Tracking (Enhanced)

This tool creates JSON ROI templates compatible with ethoscope's TargetGridROIBuilder.
It uses automatic target detection and allows interactive target correction when needed.

Usage:
    python mask_creator.py
    python mask_creator.py --machine 76 --template custom_template.json
    
The tool will:
1. Load a sample video frame from the metadata
2. Attempt automatic target detection using TargetGridROIBuilder
3. Allow manual target clicking if automatic detection fails
4. Apply a JSON template mask or create one interactively
5. Save the ROI template as JSON for use with TargetGridROIBuilder
"""

import cv2
import numpy as np
import csv
import os
import sys
import argparse
from typing import Dict, List, Tuple, Optional, Any
import json
from datetime import datetime

# Add ethoscope to path
sys.path.insert(0, '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope')

from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder


class EnhancedMaskCreator:
    """
    Enhanced mask creator that integrates with ethoscope's target detection system.
    
    Workflow:
    1. Automatic target detection using TargetGridROIBuilder
    2. Interactive target correction if needed
    3. Template-based or interactive ROI creation
    4. JSON template export
    """
    
    def __init__(self, metadata_csv: str, results_dir: str = "results/masks", force_manual: bool = False):
        self.metadata_csv = metadata_csv
        self.metadata_data = self._load_csv(metadata_csv)
        self.results_dir = results_dir
        self.force_manual = force_manual  # Flag to disable automatic detection
        
        # Current state
        self.current_frame = None
        self.original_frame = None
        self.current_machine = None
        self.targets = None
        self.template_data = None
        self.roi_builder = None
        self.rois = None
        
        # Interactive state
        self.manual_targets = []
        self.manual_mode = force_manual  # Start in manual mode if forced
        self.show_overlay = True
        
        # Create results directory
        os.makedirs(self.results_dir, exist_ok=True)
        
    def _load_csv(self, csv_path: str) -> List[Dict]:
        """Load CSV data into list of dictionaries."""
        data = []
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return data
        
    def get_machine_names(self) -> List[str]:
        """Get unique machine names from metadata."""
        machine_names = set()
        for row in self.metadata_data:
            machine_names.add(str(row['machine_name']))
        return sorted(machine_names)
        
    def get_sample_video_for_machine(self, machine_name: str) -> Optional[str]:
        """Get a sample video path for the specified machine."""
        machine_rows = [row for row in self.metadata_data 
                       if str(row['machine_name']) == machine_name]
        
        if len(machine_rows) == 0:
            return None
            
        # Get the first video with a valid path
        for row in machine_rows:
            video_path = row.get('path', '')
            if video_path and os.path.exists(video_path):
                return video_path
                
        return None
        
    def load_sample_frame(self, video_path: str, frame_number: int = 10) -> np.ndarray:
        """Load a sample frame from the video."""
        try:
            camera = MovieVirtualCamera(video_path)
            
            # Skip to desired frame
            for i, (_, frame) in enumerate(camera):
                if i == frame_number:
                    # Convert to BGR for OpenCV display
                    if len(frame.shape) == 3 and frame.shape[2] == 3:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    else:
                        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    
                    camera.restart()
                    return frame_bgr
                    
        except Exception as e:
            print(f"Error loading frame from {video_path}: {e}")
            
        return None
        
    def load_template(self, template_path: str) -> Optional[Dict]:
        """Load a JSON ROI template."""
        if not template_path or not os.path.exists(template_path):
            return None
            
        try:
            with open(template_path, 'r') as f:
                template = json.load(f)
            return template
        except Exception as e:
            print(f"Error loading template {template_path}: {e}")
            return None
            
    def detect_targets_automatically(self) -> Optional[np.ndarray]:
        """Attempt automatic target detection using TargetGridROIBuilder."""
        if self.current_frame is None:
            return None
            
        print("  🎯 Attempting automatic target detection...")
        
        try:
            # Create a temporary TargetGridROIBuilder for detection
            temp_builder = TargetGridROIBuilder(
                n_rows=1, n_cols=1,  # Minimal grid for target detection only
                enable_diagnostics=False,
                max_detection_attempts=3
            )
            
            # Try to detect targets
            targets = temp_builder._find_target_coordinates(self.current_frame.copy())
            
            if targets is not None and len(targets) == 3:
                print(f"  ✅ Found 3 targets automatically")
                return targets
            else:
                print(f"  ❌ Automatic detection failed (found {len(targets) if targets is not None else 0}/3 targets)")
                return None
                
        except Exception as e:
            print(f"  ❌ Automatic detection error: {e}")
            return None
            
    def mouse_callback(self, event, x, y, flags, param):
        """Handle mouse events for manual target clicking."""
        if not self.manual_mode:
            return
            
        if event == cv2.EVENT_LBUTTONDOWN:
            if len(self.manual_targets) < 3:
                self.manual_targets.append((x, y))
                print(f"  👆 Target {len(self.manual_targets)}: ({x}, {y})")
                self._update_display()
                
                if len(self.manual_targets) == 3:
                    print(f"  ✅ All 3 targets marked manually")
                    # Automatically test template after all targets are placed
                    self._auto_test_template_with_manual_targets()
                    
    def _update_display(self):
        """Update the display window."""
        if self.current_frame is None:
            return
            
        display_frame = self.current_frame.copy()
        
        # Draw targets
        if self.targets is not None and self.show_overlay:
            for i, (x, y) in enumerate(self.targets):
                cv2.circle(display_frame, (int(x), int(y)), 10, (0, 255, 0), 2)
                cv2.putText(display_frame, f"T{i+1}", (int(x)-10, int(y)-15), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                           
        # Draw manual targets
        if self.manual_targets and self.show_overlay:
            for i, (x, y) in enumerate(self.manual_targets):
                color = (0, 0, 255)  # Red for manual targets
                cv2.circle(display_frame, (x, y), 10, color, 2)
                cv2.putText(display_frame, f"M{i+1}", (x-10, y-15), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                           
        # Draw ROIs if available using ethoscope drawer style
        if self.rois is not None and self.show_overlay:
            for i, roi in enumerate(self.rois):
                # Draw ROI polygon using ethoscope style (black outline + colored fill)
                black_colour = (0, 0, 0)
                roi_colour = (0, 255, 0)  # Green like in ethoscope
                cv2.drawContours(display_frame, [roi.polygon], -1, black_colour, 3)
                cv2.drawContours(display_frame, [roi.polygon], -1, roi_colour, 1)
                
                # Draw ROI number using ethoscope positioning style
                x, y = roi.offset
                text_x = int(x + 10)  # Small offset from edge like ethoscope
                text_y = int(y + 40)  # Position further down from top of ROI
                roi_text = str(roi.idx)
                
                # Draw text with black outline for better visibility like ethoscope
                cv2.putText(display_frame, roi_text, (text_x, text_y), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,0), 4)  # Black outline
                cv2.putText(display_frame, roi_text, (text_x, text_y), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255,255,255), 2)  # White text
                               
        # Add UI text
        self._draw_ui_text(display_frame)
        
        cv2.imshow('Enhanced Mask Creator', display_frame)
        
    def _draw_ui_text(self, frame: np.ndarray):
        """Draw UI text on the frame."""
        text_color = (255, 255, 255)
        bg_color = (0, 0, 0)
        
        # Status info with target order guidance
        y_pos = 25
        if self.manual_mode:
            remaining = 3 - len(self.manual_targets)
            if remaining > 0:
                target_names = ["TOP-RIGHT", "BOTTOM-LEFT", "BOTTOM-RIGHT"]
                current_target = target_names[len(self.manual_targets)]
                status = f"MANUAL MODE: Click {current_target} target ({remaining} remaining)"
                color = (0, 0, 255)  # Red
            else:
                status = f"MANUAL MODE: All 3 targets set ✓"
                color = (0, 255, 0)  # Green
            cv2.rectangle(frame, (10, 5), (650, 30), bg_color, -1)
            cv2.putText(frame, status, (15, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        elif self.targets is not None:
            status = f"AUTO DETECTED: {len(self.targets)}/3 targets ✓"
            cv2.rectangle(frame, (10, 5), (350, 30), bg_color, -1)
            cv2.putText(frame, status, (15, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            status = f"NO TARGETS - Press 'm' for manual mode"
            cv2.rectangle(frame, (10, 5), (400, 30), bg_color, -1)
            cv2.putText(frame, status, (15, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
        # ROI info
        if self.rois is not None:
            roi_status = f"ROIs: {len(self.rois)}"
            cv2.rectangle(frame, (10, 35), (150, 60), bg_color, -1)
            cv2.putText(frame, roi_status, (15, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
            
        # Instructions - moved to top-left to avoid obstructing targets
        instructions = [
            "Controls:",
            "m: Manual target mode",
            "r: Reset manual targets",
            "o: Toggle overlay", 
            "t: Test template",
            "s: Save template",
            "ESC: Exit"
        ]
        
        # Place instructions on the left side, starting below the status info
        y_start = 80
        for i, instruction in enumerate(instructions):
            y = y_start + i * 18
            cv2.rectangle(frame, (10, y-10), (180, y+6), bg_color, -1)
            cv2.putText(frame, instruction, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, text_color, 1)
            
    def handle_key(self, key: int) -> bool:
        """Handle keyboard input. Returns False to exit."""
        if key == 27:  # ESC
            return False
        elif key == ord('m') and not self.force_manual:
            self._toggle_manual_mode()
        elif key == ord('r'):
            self._reset_manual_targets()
        elif key == ord('o'):
            self.show_overlay = not self.show_overlay
            print(f"Overlay: {'ON' if self.show_overlay else 'OFF'}")
        elif key == ord('t'):
            self._test_template()
        elif key == ord('s'):
            self._save_template()
            
        self._update_display()
        return True
        
    def _toggle_manual_mode(self):
        """Toggle manual target placement mode."""
        self.manual_mode = not self.manual_mode
        if self.manual_mode:
            self.manual_targets = []
            print(f"Manual mode ON - Click on 3 target positions")
            print(f"Target order: 1) TOP-RIGHT, 2) BOTTOM-LEFT, 3) BOTTOM-RIGHT")
        else:
            print(f"Manual mode OFF")
            
    def _reset_manual_targets(self):
        """Reset manual targets."""
        self.manual_targets = []
        if self.manual_mode:
            print(f"Manual targets reset - Click on 3 target positions")
            print(f"Target order: 1) TOP-RIGHT, 2) BOTTOM-LEFT, 3) BOTTOM-RIGHT")
            
    def _test_template(self):
        """Test the current template configuration."""
        if self.template_data is None:
            print("No template loaded")
            return
            
        current_targets = self._get_current_targets()
        if current_targets is None:
            print("No targets available for testing")
            return
            
        try:
            # Create ROI builder with template parameters
            roi_def = self.template_data.get('roi_definition', {})
            grid = roi_def.get('grid', {})
            positioning = roi_def.get('positioning', {})
            margins = positioning.get('margins', {})
            fills = positioning.get('fill_ratios', {})
            
            builder = TargetGridROIBuilder(
                n_rows=grid.get('n_rows', 1),
                n_cols=grid.get('n_cols', 1),
                top_margin=margins.get('top', 0),
                bottom_margin=margins.get('bottom', 0),
                left_margin=margins.get('left', 0),
                right_margin=margins.get('right', 0),
                horizontal_fill=fills.get('horizontal', 0.9),
                vertical_fill=fills.get('vertical', 0.9)
            )
            
            # Manually set targets and build ROIs
            builder._manual_targets = current_targets
            
            # Create a copy of the frame for testing
            test_frame = self.current_frame.copy()
            
            # Override the target detection with our known targets
            original_find_targets = builder._find_target_coordinates
            builder._find_target_coordinates = lambda img: current_targets
            
            try:
                reference_points, rois = builder.build(test_frame)
                
                if rois and len(rois) > 0:
                    self.roi_builder = builder
                    self.rois = rois
                    print(f"✅ Template test successful! Created {len(rois)} ROIs")
                else:
                    print(f"❌ Template test failed: No ROIs created")
                    
            finally:
                # Restore original method
                builder._find_target_coordinates = original_find_targets
                
        except Exception as e:
            print(f"❌ Template test failed: {e}")
            
    def _auto_test_template_with_manual_targets(self):
        """Automatically test template when all manual targets are placed."""
        if self.template_data is None:
            print("  📝 No template loaded, creating default template...")
            self.template_data = self._create_default_template()
            
        # Automatically test the template
        print("  🧪 Auto-testing template with manual targets...")
        self._test_template()
        
        if self.rois is not None and len(self.rois) > 0:
            print(f"  🎉 Template ready! {len(self.rois)} ROIs created. Press 's' to save.")
            
    def _get_current_targets(self) -> Optional[np.ndarray]:
        """Get current targets (automatic or manual)."""
        if len(self.manual_targets) == 3:
            # Use manual targets, converting to numpy array format
            targets = np.array(self.manual_targets, dtype=np.float32)
            return self._sort_targets(targets)
        elif self.targets is not None:
            return self.targets
        else:
            return None
            
    def _sort_targets(self, targets: np.ndarray) -> np.ndarray:
        """Sort targets using the exact same algorithm as ethoscope's TargetGridROIBuilder."""
        if len(targets) != 3:
            return targets
            
        # Convert to the same format as ethoscope (list of tuples)
        src_points = [(float(p[0]), float(p[1])) for p in targets]
        
        # Use the exact same algorithm as in target_roi_builder.py lines 367-396
        a, b, c = src_points
        pairs = [(a,b), (b,c), (a,c)]
        
        # Calculate distances for each pair
        dists = [self._points_distance(*p) for p in pairs]
        
        # Find the pair with the longest distance (hypotenuse)
        hypo_vertices = pairs[np.argmax(dists)]
        
        # Find the point not in the longest pair (this is sorted_b)
        for sp in src_points:
            if not sp in hypo_vertices:
                break
        sorted_b = sp
        
        # Find sorted_c: the point with the largest distance from sorted_b
        dist = 0
        for sp in src_points:
            if sorted_b is sp:
                continue
            if self._points_distance(sp, sorted_b) > dist:
                dist = self._points_distance(sp, sorted_b)
                sorted_c = sp
        
        # The remaining point is sorted_a
        sorted_a = [sp for sp in src_points if not sp is sorted_b and not sp is sorted_c][0]
        
        # Return in the same format as ethoscope: [sorted_a, sorted_b, sorted_c]
        sorted_points = [sorted_a, sorted_b, sorted_c]
        return np.array(sorted_points, dtype=np.float32)
    
    def _points_distance(self, pt1, pt2):
        """Calculate Euclidean distance between two points (same as in ethoscope)."""
        x1, y1 = pt1
        x2, y2 = pt2
        return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
        
    def _save_template(self):
        """Save the current template configuration."""
        if self.template_data is None:
            # Create a new template from current settings
            self.template_data = self._create_default_template()
            
        current_targets = self._get_current_targets()
        if current_targets is None:
            print("No targets available - cannot save template")
            return
            
        if self.rois is None:
            print("No ROIs created - test template first with 't'")
            return
            
        # Add target information to template
        self.template_data['targets'] = {
            'coordinates': [[float(t[0]), float(t[1])] for t in current_targets],
            'detection_method': 'manual' if len(self.manual_targets) == 3 else 'automatic',
            'timestamp': datetime.now().isoformat()
        }
        
        # Create filename
        machine_name = getattr(self, 'current_machine', 'unknown')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        template_filename = f"roi_template_machine_{machine_name}_{timestamp}.json"
        template_path = os.path.join(self.results_dir, template_filename)
        
        # Save template
        with open(template_path, 'w') as f:
            json.dump(self.template_data, f, indent=2)
            
        print(f"✅ Template saved: {template_path}")
        print(f"   ROIs: {len(self.rois)}")
        print(f"   Targets: {len(current_targets)} ({'manual' if len(self.manual_targets) == 3 else 'automatic'})")
        
    def _create_default_template(self) -> Dict:
        """Create a default template structure."""
        machine_name = getattr(self, 'current_machine', 'unknown')
        
        return {
            "template_info": {
                "name": f"Cupido Machine {machine_name}",
                "version": "1.0",
                "description": f"Custom template for machine {machine_name}",
                "author": "Cupido Mask Creator",
                "hardware_type": "cupido_tracking",
                "created": datetime.now().isoformat()
            },
            "roi_definition": {
                "type": "grid_with_targets",
                "grid": {
                    "n_rows": 2,
                    "n_cols": 3,  # 2x3 grid for mating arena
                    "orientation": "rectangular"
                },
                "alignment": {
                    "target_detection": True,
                    "expected_targets": 3,
                    "adaptive_radius": 0.10,
                    "min_target_distance": 10
                },
                "positioning": {
                    "margins": {
                        "top": 0.0,
                        "bottom": 0.0,
                        "left": 0.0,
                        "right": 0.0
                    },
                    "fill_ratios": {
                        "horizontal": 0.9,
                        "vertical": 0.9
                    }
                }
            },
            "validation": {
                "min_roi_area": 100,
                "max_roi_overlap": 0.05,
                "required_targets": 3
            }
        }
        
    def create_template_for_machine(self, machine_name: str, template_path: str = None):
        """Create a template for the specified machine."""
        print(f"\n🎯 Creating template for machine {machine_name}")
        
        # Get sample video
        video_path = self.get_sample_video_for_machine(machine_name)
        if not video_path:
            print(f"❌ No valid video found for machine {machine_name}")
            return
            
        print(f"📹 Loading sample frame from: {os.path.basename(video_path)}")
        
        # Load sample frame
        frame = self.load_sample_frame(video_path)
        if frame is None:
            print(f"❌ Failed to load frame from {video_path}")
            return
            
        # Initialize
        self.current_frame = frame
        self.original_frame = frame.copy()
        self.current_machine = machine_name
        self.targets = None
        self.manual_targets = []
        self.manual_mode = self.force_manual  # Use force_manual flag
        
        # Load template if provided, otherwise use default
        if template_path:
            self.template_data = self.load_template(template_path)
            if self.template_data:
                print(f"📋 Loaded template: {os.path.basename(template_path)}")
            else:
                print(f"❌ Failed to load template: {template_path}")
        else:
            # Try to load default template
            default_template_path = os.path.join(os.path.dirname(__file__), "HD_Mating_Arena_6_ROIS.json")
            self.template_data = self.load_template(default_template_path)
            if self.template_data:
                print(f"📋 Loaded default template: HD_Mating_Arena_6_ROIS.json")
                
        # Try automatic target detection (unless manual mode is forced)
        if not self.force_manual:
            self.targets = self.detect_targets_automatically()
            
            if self.targets is None:
                print(f"\n⚠️  Automatic target detection failed!")
                print(f"Switching to manual mode...")
                self.manual_mode = True
        else:
            print(f"🖱️  Manual mode enabled by --manual flag")
            
        if self.manual_mode:
            print(f"Please click on the 3 target positions manually:")
            print(f"1. Top target (usually top-left)")
            print(f"2. Bottom-left target") 
            print(f"3. Bottom-right target")
            print(f"Target clicking is active - click on targets now")
            
        # Setup OpenCV window
        cv2.namedWindow('Enhanced Mask Creator', cv2.WINDOW_NORMAL)
        cv2.setMouseCallback('Enhanced Mask Creator', self.mouse_callback)
        
        # Resize window to match image size if image is loaded
        if self.current_frame is not None:
            height, width = self.current_frame.shape[:2]
            cv2.resizeWindow('Enhanced Mask Creator', width, height)
        
        print(f"\n🎮 Controls:")
        if not self.force_manual:
            print(f"  m - Toggle manual target mode")
        print(f"  r - Reset manual targets") 
        print(f"  o - Toggle overlay display")
        print(f"  t - Test current template")
        print(f"  s - Save template")
        print(f"  ESC - Exit")
        
        if self.template_data:
            print(f"\n🧪 Template loaded - press 't' to test it")
        else:
            print(f"\n📝 No template loaded - will create default template")
            
        self._update_display()
        
        # Main loop
        while True:
            key = cv2.waitKey(1) & 0xFF
            if not self.handle_key(key):
                break
                
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description='Enhanced ROI Mask Creator')
    parser.add_argument('--metadata', '-m', 
                       default='2025_07_15_metadata.csv',
                       help='Path to metadata CSV file')
    parser.add_argument('--output', '-o',
                       default='results/masks',
                       help='Output directory for templates')
    parser.add_argument('--machine', '-M',
                       help='Specific machine name to create template for')
    parser.add_argument('--template', '-t',
                       help='Path to JSON template file to use/modify')
    parser.add_argument('--manual', action='store_true',
                       help='Disable automatic target detection and use manual mode')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.metadata):
        print(f"❌ Metadata file not found: {args.metadata}")
        return
        
    # Create mask creator
    creator = EnhancedMaskCreator(args.metadata, args.output, args.manual)
    
    if args.machine:
        # Create template for specific machine
        creator.create_template_for_machine(args.machine, args.template)
    else:
        # Interactive machine selection
        machines = creator.get_machine_names()
        print("Available machines:")
        for i, machine in enumerate(machines, 1):
            print(f"{i}. {machine}")
            
        while True:
            try:
                choice = input("\nSelect machine number (or 'q' to quit): ").strip()
                if choice.lower() == 'q':
                    break
                    
                machine_idx = int(choice) - 1
                if 0 <= machine_idx < len(machines):
                    creator.create_template_for_machine(machines[machine_idx], args.template)
                else:
                    print("Invalid choice")
                    
            except (ValueError, KeyboardInterrupt):
                break
                
    print("Template creation complete!")


if __name__ == "__main__":
    main()