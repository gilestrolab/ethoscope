#!/usr/bin/env python3
"""
Cupido Offline Tracker

Simple offline tracker for individual videos using ethoscope package with JSON mask templates.

Usage:
    python cupido_tracker.py --video /path/to/video.mp4 --mask /path/to/mask.json [--flies-per-roi 2]
    
Features:
- Individual video processing with JSON mask templates
- Multi-fly tracking support (1-N flies per ROI)
- SQLite database output compatible with ethoscope ecosystem
"""

import os
import sys
import json
import argparse
from typing import Optional
import time

# Add ethoscope to path
sys.path.insert(0, '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope')

from ethoscope.hardware.input.cameras import MovieVirtualCamera
# Removed AdaptiveBGModel - using MultiFlyTracker for 2 flies per ROI
from ethoscope.core.monitor import Monitor
from ethoscope.io import SQLiteResultWriter
from ethoscope.drawers.drawers import DefaultDrawer
from roi_manager import CupidoROIManager
from mask_creator import EnhancedMaskCreator
import cv2
import numpy as np
import logging

# Configure logging
logger = logging.getLogger(__name__)

def setup_logging(verbose=False):
    """Setup logging configuration for cupido tracker."""
    level = logging.DEBUG if verbose else logging.WARNING
    
    # Create a console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # Configure logger
    logger.setLevel(level)
    logger.addHandler(console_handler)
    
    return logger

class BGRDefaultDrawer(DefaultDrawer):
    """
    Custom drawer that handles BGR frames properly.
    Unlike DefaultDrawer, this doesn't assume grayscale input.
    """
    
    def draw(self, img, positions, tracking_units, reference_points=None):
        # Check if image is already BGR (3 channels)
        if len(img.shape) == 3 and img.shape[2] == 3:
            # Already BGR, just copy
            self._last_drawn_frame = img.copy()
        else:
            # Grayscale, convert to BGR
            self._last_drawn_frame = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        
        self._annotate_frame(self._last_drawn_frame, positions, tracking_units, reference_points)
        
        if self._draw_frames:
            cv2.imshow(self._live_window_name, self._last_drawn_frame)
            cv2.waitKey(1)

class DetectionAnalysisResultWriter:
    """
    Wrapper for SQLiteResultWriter that logs detection sizes for analysis.
    """
    
    def __init__(self, actual_writer, rois):
        self.actual_writer = actual_writer
        self.rois = rois
        self.detection_sizes = []
        self.frame_count = 0
        
    def write(self, timestamp, roi, data_rows):
        self.actual_writer.write(timestamp, roi, data_rows)
        
        # Log detection sizes for analysis
        for row in data_rows:
            if 'w' in row and 'h' in row:
                width, height = row['w'], row['h']
                area = width * height
                diameter = np.sqrt(area / np.pi) * 2  # Approximate diameter
                
                roi_idx = roi.idx - 1  # ROI index (0-based)
                roi_dims = cv2.boundingRect(self.rois[roi_idx].polygon)
                roi_max_dim = max(roi_dims[2], roi_dims[3])
                size_ratio = diameter / roi_max_dim
                
                self.detection_sizes.append({
                    'roi': roi.idx,
                    'diameter_px': diameter,
                    'area_px': area,
                    'size_ratio': size_ratio,
                    'timestamp': timestamp
                })
                
        # Log periodic analysis
        if len(self.detection_sizes) > 0 and len(self.detection_sizes) % 20 == 0:
            diameters = [d['diameter_px'] for d in self.detection_sizes[-20:]]
            ratios = [d['size_ratio'] for d in self.detection_sizes[-20:]]
            logger.debug(f"Last 20 detections: {np.mean(diameters):.1f}px avg diameter, {np.mean(ratios)*100:.2f}% of ROI")
                
    def flush(self, timestamp, frame):
        self.actual_writer.flush(timestamp, frame)
        self.frame_count += 1
        
        # Log summary every 100 frames
        if self.frame_count % 100 == 0 and self.detection_sizes:
            diameters = [d['diameter_px'] for d in self.detection_sizes]
            ratios = [d['size_ratio'] for d in self.detection_sizes]
            logger.info(f"Frame {self.frame_count}: {len(self.detection_sizes)} total detections")
            logger.info(f"Diameter range: {np.min(diameters):.1f}-{np.max(diameters):.1f}px (avg: {np.mean(diameters):.1f}px)")
            logger.info(f"Size ratio range: {np.min(ratios)*100:.2f}-{np.max(ratios)*100:.2f}% of ROI (avg: {np.mean(ratios)*100:.2f}%)")
    
    def __enter__(self):
        self.actual_writer.__enter__()
        return self
        
    def __exit__(self, *args):
        # Log final analysis
        if self.detection_sizes:
            logger.info("DETECTION ANALYSIS COMPLETE")
            logger.info(f"Total detections: {len(self.detection_sizes)}")
            
            diameters = [d['diameter_px'] for d in self.detection_sizes]
            areas = [d['area_px'] for d in self.detection_sizes]
            ratios = [d['size_ratio'] for d in self.detection_sizes]
            
            mean_area = np.mean(areas)
            std_area = np.std(areas)
            
            logger.info(f"Fly diameter: {np.min(diameters):.1f}-{np.max(diameters):.1f}px (avg: {np.mean(diameters):.1f}±{np.std(diameters):.1f}px)")
            logger.info(f"Fly area: {np.min(areas):.0f}-{np.max(areas):.0f}px² (avg: {mean_area:.1f}±{std_area:.1f}px²)")
            logger.info(f"Size ratio: {np.mean(ratios)*100:.2f}±{np.std(ratios)*100:.2f}% of ROI")
            
            # Calculate recommended limits (mean ± 2 standard deviations covers ~95% of data)
            conservative_min = max(int(mean_area - 2*std_area), 10)  # Don't go below 10
            conservative_max = int(mean_area + 2*std_area)
            liberal_min = max(int(mean_area - 3*std_area), 10)  # Don't go below 10  
            liberal_max = int(mean_area + 3*std_area)
            
            logger.info("RECOMMENDED MULTIFLYTRACKER PARAMETERS:")
            logger.info(f"Conservative (±2σ, ~95%): 'normal_limits': ({conservative_min}, {conservative_max})")
            logger.info(f"Liberal (±3σ, ~99.7%): 'normal_limits': ({liberal_min}, {liberal_max})")
            logger.info(f"Current settings: 'normal_limits': (20, 1000)")
        else:
            logger.warning("NO DETECTIONS FOUND - flies might be too small, too large, or tracking parameters need adjustment")
            
        return self.actual_writer.__exit__(*args)

class BGRMovieVirtualCamera(MovieVirtualCamera):
    """
    Wrapper for MovieVirtualCamera that converts grayscale frames to BGR 
    for trackers that expect color input (like MultiFlyTracker).
    """
    
    def _next_image(self):
        # Get grayscale frame from parent
        gray_frame = super()._next_image()
        # Convert to BGR for trackers that expect color input
        return cv2.cvtColor(gray_frame, cv2.COLOR_GRAY2BGR)

class ConstrainedMultiFlyTracker:
    """
    Wrapper for MultiFlyTracker that enforces maximum detection limit.
    If more than maxN detections found, returns empty list to avoid false positives.
    No minimum enforced (flies could be dead/inactive).
    """
    
    def __init__(self, roi, data):
        self.maxN = data.get('maxN', 2)
        
        # Create the underlying MultiFlyTracker
        self._tracker = MultiFlyTracker(roi, data)
        
        logger.info(f"Max constraint: ≤{self.maxN} flies per ROI (no minimum - flies could be dead)")
    
    def track(self, timestamp, img):
        """Track and enforce maximum detection constraint."""
        try:
            detections = self._tracker.track(timestamp, img)
            detection_count = len(detections)
            
            # Only enforce maximum constraint (allow 0 to maxN detections)
            if detection_count > self.maxN:
                # Too many detections - likely false positives, return empty list
                return []
            else:
                # Valid detection count (0 to maxN), return as-is
                return detections
                
        except Exception as e:
            # Pass through any tracking exceptions
            raise e
    
    def __getattr__(self, name):
        """Delegate all other attributes to the underlying tracker."""
        return getattr(self._tracker, name)

# Optional import for multi-fly tracker
try:
    from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
    from multi_fly_tracker_offline import MultiFlyTrackerOffline
    MULTI_FLY_TRACKER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"MultiFlyTracker not available: {e}")
    MultiFlyTracker = None
    MultiFlyTrackerOffline = None
    MULTI_FLY_TRACKER_AVAILABLE = False


class CupidoTracker:
    """
    Simple offline tracker for individual videos using JSON mask templates.
    """
    
    def __init__(self, video_path: str, mask_path: str, flies_per_roi: int = 2, manual_targets: bool = False, show_tracking: bool = False, targets_coords: str = None):
        """
        Initialize the Cupido tracker.
        
        Args:
            video_path: Path to video file
            mask_path: Path to JSON mask template
            flies_per_roi: Number of flies to track per ROI (default: 2)
            manual_targets: Use manual target detection (default: False)
            show_tracking: Show live tracking visualization (default: False)
            targets_coords: Pre-defined target coordinates as string "((x,y),(x1,y1),(x2,y2))"
        """
        self.video_path = video_path
        self.mask_path = mask_path
        self.flies_per_roi = flies_per_roi
        self.manual_targets = manual_targets
        self.show_tracking = show_tracking
        self.targets_coords = targets_coords
        
        # Validate inputs
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not os.path.exists(mask_path):
            raise FileNotFoundError(f"Mask file not found: {mask_path}")
            
        # Initialize ROI manager with single mask
        self.roi_manager = CupidoROIManager(".")
    
    def _get_tracker_params_from_template(self):
        """
        Extract tracker parameters from the mask template tracking_recommendations.
        Returns parameters dict if found, None otherwise.
        """
        try:
            # Read JSON template directly
            with open(self.mask_path, 'r') as f:
                template_data = json.load(f)
            
            if 'tracking_recommendations' in template_data:
                recommendations = template_data['tracking_recommendations']
                
                # Check if it's for MultiFlyTracker
                if recommendations.get('tracker_class') == 'MultiFlyTracker':
                    params = recommendations.get('parameters', {}).copy()  # Make a copy to avoid modifying original
                    
                    # Ensure maxN matches our flies_per_roi setting
                    params['maxN'] = self.flies_per_roi
                    
                    logger.info("Found tracker parameters in template")
                    if 'notes' in recommendations:
                        logger.info(f"Notes: {recommendations['notes']}")
                    if 'calibration_data' in recommendations:
                        cal_data = recommendations['calibration_data']
                        if 'detection_count' in cal_data:
                            logger.info(f"Based on {cal_data['detection_count']} detections")
                    
                    return params
                else:
                    logger.info(f"Template recommends {recommendations.get('tracker_class', 'Unknown')} - using fallback parameters")
                    return None
            
            return None
            
        except Exception as e:
            logger.warning(f"Could not read tracker parameters from template: {e}")
            return None

    def track(self, output_path: Optional[str] = None) -> bool:
        """
        Track the video using the specified mask.
        
        Args:
            output_path: Optional path for output database (defaults to video_name.db)
            
        Returns:
            True if tracking succeeded, False otherwise
        """
        # Generate output path if not provided
        if output_path is None:
            video_basename = os.path.splitext(os.path.basename(self.video_path))[0]
            output_path = f"{video_basename}_tracking.db"
        
        logger.info("Starting Cupido tracking")
        logger.info(f"Video: {os.path.basename(self.video_path)}")
        logger.info(f"Mask: {os.path.basename(self.mask_path)}")
        logger.info(f"Output: {os.path.basename(output_path)}")
        logger.info(f"Flies per ROI: {self.flies_per_roi}")
        
        try:
            # Initialize camera (will be updated later based on tracker choice)
            camera = MovieVirtualCamera(self.video_path)
            
            # Handle target detection (manual, coordinates, or template-based)
            manual_targets = None
            
            # Check if pre-defined coordinates are provided
            if self.targets_coords:
                try:
                    # Parse coordinates from string format "((x,y),(x1,y1),(x2,y2))"
                    import ast
                    coords_tuple = ast.literal_eval(self.targets_coords)
                    if len(coords_tuple) == 3:
                        manual_targets = np.array([[float(x), float(y)] for x, y in coords_tuple], dtype=np.float32)
                        logger.info(f"Using provided target coordinates: {coords_tuple}")
                    else:
                        logger.error(f"Invalid coordinates format - expected 3 targets, got {len(coords_tuple)}")
                        return False
                except Exception as e:
                    logger.error(f"Failed to parse target coordinates: {e}")
                    return False
                    
            elif self.manual_targets:
                logger.info("Manual target detection requested")
                
                # Get a sample frame from the video (using camera iterator)
                sample_frame = None
                try:
                    for i, (_, frame) in enumerate(camera):
                        if i == 10:  # Use frame 10 like mask_creator does
                            # Convert to BGR for OpenCV display
                            if len(frame.shape) == 3:
                                # Color frame - convert RGB to BGR
                                sample_frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                            elif len(frame.shape) == 2:
                                # Grayscale frame - convert to BGR
                                sample_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                            else:
                                # Unexpected format
                                logger.error(f"Unexpected frame format: {frame.shape}")
                                return False
                            break
                except Exception as e:
                    logger.error(f"Failed to load sample frame: {e}")
                    return False
                
                if sample_frame is None:
                    logger.error("Failed to get sample frame from video")
                    return False
                    
                # Use EnhancedMaskCreator's manual target detection functionality
                # Create temporary CSV for EnhancedMaskCreator
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
                    f.write("machine_name,path\n")
                    f.write(f"temp,{self.video_path}\n")
                    temp_csv = f.name
                
                try:
                    # Create mask creator temporarily 
                    mask_creator = EnhancedMaskCreator(temp_csv, ".", force_manual=True)
                    
                    # Set the frame and enable manual mode
                    mask_creator.current_frame = sample_frame
                    mask_creator.original_frame = sample_frame.copy()
                    mask_creator.manual_mode = True
                    mask_creator.manual_targets = []
                    
                    # Use the existing interactive UI
                    logger.info("Manual target detection using mask creator UI")
                    logger.info("Click on targets in order: TOP-RIGHT, BOTTOM-LEFT, BOTTOM-RIGHT") 
                    logger.info("Press ESC when done")
                    
                    # Set up OpenCV window with the same name mask_creator uses
                    window_name = 'Enhanced Mask Creator'
                    cv2.namedWindow(window_name)
                    cv2.setMouseCallback(window_name, mask_creator.mouse_callback)
                    
                    # Interactive loop
                    while True:
                        mask_creator._update_display()
                        key = cv2.waitKey(1) & 0xFF
                        
                        if key == 27:  # ESC
                            break
                        elif len(mask_creator.manual_targets) == 3:
                            # Convert and sort targets
                            targets_array = np.array(mask_creator.manual_targets, dtype=np.float32)
                            manual_targets = mask_creator._sort_targets(targets_array)
                            break
                    
                    cv2.destroyWindow(window_name)
                    
                finally:
                    # Clean up temp file
                    if os.path.exists(temp_csv):
                        os.unlink(temp_csv)
                
                if manual_targets is None or len(manual_targets) != 3:
                    logger.error("Manual target detection failed or incomplete")
                    return False
                    
                logger.info(f"Manual targets detected: {len(manual_targets)} targets")
                
                # Output coordinates in reusable format
                coords_str = f"(({int(manual_targets[0][0])},{int(manual_targets[0][1])}),({int(manual_targets[1][0])},{int(manual_targets[1][1])}),({int(manual_targets[2][0])},{int(manual_targets[2][1])}))"
                logger.info(f"Target coordinates (for --targets flag): {coords_str}")
                
                # Restart camera after using it for frame extraction
                camera.restart()
            
            # Get ROI builder from mask with optional manual targets
            roi_builder = self.roi_manager.load_roi_builder_from_file(self.mask_path, manual_targets)
            if roi_builder is None:
                logger.error("Failed to load ROI builder from mask")
                return False
            
            # Build ROIs
            logger.info("Building ROIs from mask")
            reference_points, rois = roi_builder.build(camera)
            
            if not rois or len(rois) == 0:
                logger.error("No ROIs created")
                return False
                
            logger.info(f"Created {len(rois)} ROI(s)")
            
            # Debug ROI sizes and tracking parameters
            logger.info("ROI analysis:")
            
            # Get limits from template if available, otherwise use defaults
            tracker_params = self._get_tracker_params_from_template()
            if tracker_params and 'fg_data' in tracker_params:
                limits = tracker_params['fg_data']['normal_limits']
            else:
                limits = [800, 2000]  # Empirical defaults
            
            for i, roi in enumerate(rois):
                x, y, w, h = cv2.boundingRect(roi.polygon)
                logger.info(f"ROI {i+1}: {w}x{h} pixels at ({x},{y})")
                
                # Show what MultiFlyTracker expects based on limits
                min_diameter = int(2 * np.sqrt(limits[0] / np.pi))  
                max_diameter = int(2 * np.sqrt(limits[1] / np.pi))  
                logger.info(f"MultiFlyTracker expects flies {min_diameter}-{max_diameter}px diameter")
                logger.info(f"Area range: {limits[0]}-{limits[1]}px²")
                logger.warning("If flies are outside this range, they won't be detected")
            
            # Use MultiFlyTracker for multi-fly tracking (2 flies per ROI)
            if not MULTI_FLY_TRACKER_AVAILABLE:
                logger.error("MultiFlyTracker not available - cannot track multiple flies per ROI")
                return False
            else:
                tracker_class = ConstrainedMultiFlyTracker
                
                # Try to get parameters from template tracking_recommendations
                tracker_params = self._get_tracker_params_from_template()
                if tracker_params:
                    # Use template parameters
                    tracker_kwargs = {'data': tracker_params}
                    limits = tracker_params['fg_data']['normal_limits']
                    logger.info(f"Using MultiFlyTracker with template parameters (normal_limits: {limits})")
                else:
                    # Fallback to empirically determined parameters
                    tracker_kwargs = {
                        'data': {
                            'maxN': self.flies_per_roi,
                            'visualise': False,
                            'fg_data': {
                                'sample_size': 400,
                                'normal_limits': (800, 2000),  # Empirically optimized from HD video analysis
                                'tolerance': 0.8
                            }
                        }
                    }
                    logger.info("Using MultiFlyTracker with default empirical parameters (normal_limits: 800, 2000)")
                
                logger.info(f"Tracking up to {self.flies_per_roi} flies per ROI")
            
            # MultiFlyTracker expects BGR frames, use appropriate camera
            camera = BGRMovieVirtualCamera(self.video_path)
            logger.info("Using BGR camera for MultiFlyTracker compatibility")
            
            # Initialize tracking
            monitor = Monitor(camera, tracker_class, rois, **tracker_kwargs)
            
            logger.info("Tracker configured:")
            for i, track_unit in enumerate(monitor._unit_trackers):
                tracker = track_unit._tracker
                roi_size = max(cv2.boundingRect(rois[i].polygon)[2:])
                
                if hasattr(tracker, '_object_expected_size'):
                    # AdaptiveBGModel
                    expected_px = int(tracker._object_expected_size * roi_size)
                    logger.debug(f"ROI {i+1}: AdaptiveBGModel expects ~{expected_px}px flies")
                elif hasattr(tracker, '_object_expected_size'):
                    # MultiFlyTracker 
                    expected_px = int(tracker._object_expected_size * roi_size)
                    logger.debug(f"ROI {i+1}: MultiFlyTracker expects ~{expected_px}px flies")
                else:
                    logger.debug(f"ROI {i+1}: Tracker type: {type(tracker).__name__}")
            
            # Create metadata for database
            metadata = {
                'video_path': self.video_path,
                'mask_path': self.mask_path,
                'flies_per_roi': self.flies_per_roi,
                'tracker_class': tracker_class.__name__
            }
            
            # Track with database writer
            logger.info("Starting tracking")
            start_time = time.time()
            
            try:
                db_credentials = {"name": output_path}
                
                # Set up drawer if visualization is requested
                drawer = None
                if self.show_tracking:
                    drawer = BGRDefaultDrawer(draw_frames=True)
                    logger.info("Live tracking visualization enabled")
                
                with SQLiteResultWriter(db_credentials, rois, metadata) as sqlite_writer:
                    # Wrap with analysis writer to collect size statistics
                    #analysis_writer = DetectionAnalysisResultWriter(sqlite_writer, rois)
                    monitor.run(result_writer=sqlite_writer, drawer=drawer, verbose=True)
            except Exception as e:
                logger.error(f"Detailed error: {e}")
                import traceback
                traceback.print_exc()
                raise
                
            end_time = time.time()
            duration = end_time - start_time
            
            logger.info(f"Tracking completed in {duration:.1f} seconds")
            logger.info(f"Results saved to: {output_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Tracking failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description='Cupido Offline Tracker - Simple video tracking with JSON masks')
    parser.add_argument('--video', '-v', required=True,
                       help='Path to video file')
    parser.add_argument('--mask', '-m', required=True,
                       help='Path to JSON mask template')
    parser.add_argument('--flies-per-roi', '-f', type=int, default=2,
                       help='Number of flies to track per ROI (default: 2)')
    parser.add_argument('--output', '-o',
                       help='Output database path (default: video_name_tracking.db)')
    parser.add_argument('--manual-targets', action='store_true',
                       help='Use manual target detection instead of template targets')
    parser.add_argument('--targets',
                       help='Use specific target coordinates "((x,y),(x1,y1),(x2,y2))"')
    parser.add_argument('--show', action='store_true',
                       help='Show live tracking visualization')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging output')
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(args.verbose)
    
    try:
        # Create tracker
        tracker = CupidoTracker(args.video, args.mask, args.flies_per_roi, args.manual_targets, args.show, args.targets)
        
        # Run tracking
        success = tracker.track(args.output)
        
        if success:
            logger.info("Tracking completed successfully")
        else:
            logger.error("Tracking failed")
            return 1
            
    except Exception as e:
        logger.error(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
