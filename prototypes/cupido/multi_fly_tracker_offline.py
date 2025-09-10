#!/usr/bin/env python3
"""
MultiFlyTrackerOffline - Enhanced MultiFlyTracker for offline video analysis.

This tracker inherits from MultiFlyTracker and adds methods to create a constant
background image by averaging all frames from the video, providing more stable
background subtraction for compressed/noisy videos.
"""

import sys
import cv2
import numpy as np
import logging

# Add ethoscope to path
sys.path.insert(0, '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope')

from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
from ethoscope.hardware.input.cameras import MovieVirtualCamera

logger = logging.getLogger(__name__)


class MultiFlyTrackerOffline(MultiFlyTracker):
    """
    Enhanced MultiFlyTracker for offline video analysis with pre-computed background.
    
    This tracker creates a stable background image by averaging frames from the entire
    video, which provides better background subtraction for compressed videos with
    artifacts and varying lighting conditions.
    """
    
    def __init__(self, roi, data=None):
        """
        Initialize MultiFlyTrackerOffline with background pre-computation capability.
        
        Args:
            roi: Region of interest
            data: Configuration dictionary, same as MultiFlyTracker plus:
                - 'video_path': Path to video for background computation
                - 'background_frames': Number of frames to sample for background (default: 100)
                - 'background_method': 'mean' or 'median' (default: 'median')
                - 'precompute_background': Whether to compute background on init (default: True)
        """
        # Set default parameters
        if data is None:
            data = {}
            
        default_data = {
            'maxN': 2,
            'visualise': False,
            'fg_data': {
                'sample_size': 400,
                'normal_limits': [800, 2000],
                'tolerance': 0.8
            },
            'adaptive_threshold': True,
            'min_fg_threshold': 10,
            'max_fg_threshold': 50,
            'background_frames': 100,
            'background_method': 'median',  # 'mean' or 'median'
            'precompute_background': True
        }
        
        # Merge with provided data
        for key, value in default_data.items():
            if key not in data:
                data[key] = value
                
        # Store offline-specific parameters
        self._video_path = data.get('video_path', None)
        self._background_frames = data.get('background_frames', 100)
        self._background_method = data.get('background_method', 'median')
        self._precompute_background = data.get('precompute_background', True)
        
        # Initialize parent class
        super().__init__(roi, data)
        
        # Offline-specific attributes
        self._precomputed_background = None
        self._background_ready = False
        
        # Pre-compute background if requested and video path provided
        if self._precompute_background and self._video_path:
            self.compute_background_from_video(self._video_path)
    
    def compute_background_from_video(self, video_path, roi_mask=None):
        """
        Compute a stable background image by sampling frames from the entire video.
        
        Args:
            video_path: Path to the video file
            roi_mask: Optional mask to limit background computation to ROI area
            
        Returns:
            Background image as numpy array
        """
        logger.info(f"Computing background from video: {video_path}")
        logger.info(f"Sampling {self._background_frames} frames using {self._background_method} method")
        
        # Open video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Failed to open video: {video_path}")
            return None
            
        # Get video properties
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        logger.info(f"Video properties: {total_frames} frames, {width}x{height}")
        
        # Calculate frame sampling interval
        if total_frames <= self._background_frames:
            # Use all frames if video is short
            frame_indices = list(range(total_frames))
        else:
            # Sample frames evenly across the video
            frame_indices = np.linspace(0, total_frames - 1, self._background_frames, dtype=int)
            
        logger.info(f"Sampling frames: {len(frame_indices)} frames from {total_frames} total")
        
        # Collect frames for background computation
        background_frames = []
        
        for i, frame_idx in enumerate(frame_indices):
            # Seek to frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            
            if not ret:
                logger.warning(f"Failed to read frame {frame_idx}")
                continue
                
            # Convert to grayscale
            if len(frame.shape) == 3:
                gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                gray_frame = frame
                
            # Apply ROI mask if provided
            if roi_mask is not None:
                gray_frame = cv2.bitwise_and(gray_frame, roi_mask)
                
            background_frames.append(gray_frame)
            
            # Log progress
            if i % 20 == 0:
                logger.debug(f"Processed {i+1}/{len(frame_indices)} background frames")
                
        cap.release()
        
        if len(background_frames) == 0:
            logger.error("No frames collected for background computation")
            return None
            
        logger.info(f"Collected {len(background_frames)} frames for background computation")
        
        # Compute background using specified method
        background_stack = np.stack(background_frames, axis=0)
        
        if self._background_method == 'median':
            background_img = np.median(background_stack, axis=0).astype(np.uint8)
            logger.info("Background computed using median method")
        else:  # mean
            background_img = np.mean(background_stack, axis=0).astype(np.uint8)
            logger.info("Background computed using mean method")
            
        # Store the computed background
        self._precomputed_background = background_img
        self._background_ready = True
        
        logger.info(f"Background image computed: {background_img.shape}, dtype={background_img.dtype}")
        logger.info(f"Background stats: mean={np.mean(background_img):.1f}, std={np.std(background_img):.1f}")
        
        return background_img
    
    def set_precomputed_background(self, background_img):
        """
        Set a pre-computed background image directly.
        
        Args:
            background_img: Background image as numpy array
        """
        self._precomputed_background = background_img.copy()
        self._background_ready = True
        logger.info("Pre-computed background image set manually")
        
    def get_background_image(self):
        """
        Get the current background image.
        
        Returns:
            Background image or None if not available
        """
        if self._background_ready:
            return self._precomputed_background.copy()
        else:
            # Fallback to parent class background if available
            if self._bg_model.bg_img is not None:
                return self._bg_model.bg_img.copy()
            else:
                return None
                
    def save_background_image(self, output_path):
        """
        Save the computed background image to file.
        
        Args:
            output_path: Path to save the background image
            
        Returns:
            True if successful, False otherwise
        """
        if not self._background_ready:
            logger.error("No background image available to save")
            return False
            
        try:
            cv2.imwrite(output_path, self._precomputed_background)
            logger.info(f"Background image saved to: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save background image: {e}")
            return False
    
    def _track(self, img, grey, mask, t):
        """
        Override parent _track method to use precomputed background when available.
        """
        # Use precomputed background if available, otherwise fall back to adaptive background
        if self._background_ready and self._precomputed_background is not None:
            # Use our stable precomputed background
            if self._buff_fg is None:
                self._buff_fg = np.empty_like(grey)
                self._buff_object = np.empty_like(grey)
                self._buff_fg_backup = np.empty_like(grey)
                
            # Ensure background and current frame have same dimensions
            if self._precomputed_background.shape != grey.shape:
                # Resize background to match current frame
                bg_resized = cv2.resize(self._precomputed_background, 
                                      (grey.shape[1], grey.shape[0]))
            else:
                bg_resized = self._precomputed_background
                
            # Subtract precomputed background
            cv2.subtract(grey, bg_resized, self._buff_fg)
            
            # Continue with rest of tracking pipeline (threshold, morphological filtering, etc.)
            # Adaptive threshold based on image statistics
            if self._adaptive_threshold:
                # Calculate adaptive threshold based on foreground statistics
                fg_mean = np.mean(self._buff_fg[self._buff_fg > 0]) if np.any(self._buff_fg > 0) else 20
                self._current_fg_threshold = max(self._min_fg_threshold, 
                                               min(self._max_fg_threshold, 
                                                   int(fg_mean * 0.3)))
            
            cv2.threshold(self._buff_fg, self._current_fg_threshold, 255, cv2.THRESH_TOZERO, dst=self._buff_fg)
            
            # Apply morphological filtering to remove compression artifacts
            self._apply_morphological_filtering(self._buff_fg)
            
            self._buff_fg_backup = np.copy(self._buff_fg)

            n_fg_pix = np.count_nonzero(self._buff_fg)
            prop_fg_pix = n_fg_pix / (1.0 * grey.shape[0] * grey.shape[1])
            is_ambiguous = False

            # Use foreground-model-based max area calculation
            if prop_fg_pix > self._max_area_ratio:
                logging.debug(f"Too much foreground: {prop_fg_pix:.3f} > {self._max_area_ratio:.3f}")
                # Don't update background model when using precomputed background
                raise self.NoPositionError

            if prop_fg_pix == 0:
                logging.debug("No foreground pixels detected")
                raise self.NoPositionError

            # Find and process contours (same as parent class)
            if cv2.__version__.startswith('3'):
                _, contours, hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            else:
                contours, hierarchy = cv2.findContours(self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            contours = [cv2.approxPolyDP(c, 1.2, True) for c in contours]
            valid_contours = []

            if len(contours) == 0:
                logging.debug(f"No contours detected (threshold: {self._current_fg_threshold})")
                raise self.NoPositionError
            else:
                for c in contours:
                    if self._fg_model.is_contour_valid(c, img):
                        valid_contours.append(c)
                
                # If no valid contours found but contours exist, log for debugging
                if len(valid_contours) == 0 and len(contours) > 0:
                    areas = [cv2.contourArea(c) for c in contours]
                    logging.debug(f"No valid contours: found {len(contours)} contours with areas {areas}, limits: {self._fg_model.normal_limits}")

            out_pos = []
            
            # Process valid contours (same as parent class)
            for n_vc, vc in enumerate(valid_contours):
                
                #calculates the parameters to draw the centroid
                (x,y), (w,h), angle = cv2.minAreaRect(vc)
                
                #adjust the orientation for consistency
                if w < h:
                    angle -= 90
                    w,h = h,w
                angle = angle % 180

                #ignore if the ellipse is drawn outside the actual picture
                h_im = min(grey.shape)
                w_im = max(grey.shape)
                max_h = 2*h_im
                if w>max_h or h>max_h:
                    continue
                    
                pos = x +1.0j*y
                pos /= w_im

                #draw the ellipse around the blob
                cv2.ellipse(self._buff_fg, ((x,y), (int(w*1.5),int(h*1.5)),angle), 255, 1)

                # store the blob info in a list
                from ethoscope.core.variables import XPosVariable, YPosVariable, WidthVariable, HeightVariable, PhiVariable
                from ethoscope.core.data_point import DataPoint
                
                x_var = XPosVariable(int(round(x)))
                y_var = YPosVariable(int(round(y)))
                w_var = WidthVariable(int(round(w)))
                h_var = HeightVariable(int(round(h)))
                phi_var = PhiVariable(int(round(angle)))
                
                out = DataPoint([x_var, y_var, w_var, h_var, phi_var])
                out_pos.append(out)

            # end the for loop iterating within contours

            if self._visualise:
                cv2.imshow(self.multi_fly_tracker_window, self._buff_fg)
            
            if len(out_pos) == 0:
                logging.debug(f"No valid positions found after processing {len(valid_contours)} valid contours")
                raise self.NoPositionError
                
            # Limit to maxN detections to prevent false positives
            if len(out_pos) > self.maxN:
                # Sort by area (larger flies are more likely to be real)
                out_pos_with_area = [(pos, int(pos['w']) * int(pos['h'])) for pos in out_pos]  # w*h as area proxy
                out_pos_with_area.sort(key=lambda x: x[1], reverse=True)
                out_pos = [pos for pos, area in out_pos_with_area[:self.maxN]]
                logging.debug(f"Limited detections from {len(out_pos_with_area)} to {len(out_pos)}")

            cv2.bitwise_and(self._buff_fg_backup, self._buff_fg, self._buff_fg_backup)

            if mask is not None:
                cv2.bitwise_and(self._buff_fg, mask, self._buff_fg)

            # Don't update background model when using precomputed background
            # (this maintains the stable background throughout the video)

            return out_pos
            
        else:
            # Fall back to parent class adaptive background method
            logger.debug("Using adaptive background (no precomputed background available)")
            return super()._track(img, grey, mask, t)
    
    def reset_background(self):
        """
        Reset the background computation state.
        """
        self._precomputed_background = None
        self._background_ready = False
        logger.info("Background state reset")
        
    @property
    def background_ready(self):
        """Check if background is ready for use."""
        return self._background_ready
        
    @property 
    def background_method(self):
        """Get the background computation method."""
        return self._background_method
        
    @property
    def background_frame_count(self):
        """Get the number of frames used for background computation."""
        return self._background_frames


def test_offline_tracker():
    """Test function for MultiFlyTrackerOffline."""
    
    # Example usage
    video_path = "/path/to/your/video.mp4"
    
    # Create a dummy ROI for testing
    import numpy as np
    
    class DummyROI:
        def __init__(self):
            self.polygon = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.int32)
            
    roi = DummyROI()
    
    # Configuration for offline tracker
    config = {
        'maxN': 2,
        'visualise': False,
        'fg_data': {
            'sample_size': 400,
            'normal_limits': [800, 2000],
            'tolerance': 0.8
        },
        'video_path': video_path,
        'background_frames': 50,
        'background_method': 'median',
        'precompute_background': True
    }
    
    # Create tracker
    tracker = MultiFlyTrackerOffline(roi, config)
    
    if tracker.background_ready:
        print("Background computed successfully!")
        print(f"Method: {tracker.background_method}")
        print(f"Frames used: {tracker.background_frame_count}")
        
        # Save background image
        tracker.save_background_image("background.jpg")
    else:
        print("Background computation failed")


if __name__ == "__main__":
    test_offline_tracker()