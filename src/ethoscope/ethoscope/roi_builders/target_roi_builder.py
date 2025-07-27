__author__ = 'quentin'

import cv2
import logging
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
import logging
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI
from ethoscope.utils.debug import EthoscopeException
from ethoscope.roi_builders.target_detection_diagnostics import TargetDetectionDiagnostics
import itertools


class TargetGridROIBuilder(BaseROIBuilder):

    _adaptive_med_rad = 0.10
    _expected__min_target_dist = 10 # the minimal distance between two targets, in 'target diameter'
    _n_rows = 10
    _n_cols = 2
    _top_margin =  0
    _bottom_margin = None
    _left_margin = 0
    _right_margin = None
    _horizontal_fill = 1
    _vertical_fill = None

    _description = {"overview": "A flexible ROI builder that allows users to select parameters for the ROI layout."
                               "Lengths are relative to the distance between the two bottom targets (width)",
                    "arguments": [
                                    {"type": "number", "min": 1, "max": 16, "step":1, "name": "n_cols", "description": "The number of columns","default":1},
                                    {"type": "number", "min": 1, "max": 16, "step":1, "name": "n_rows", "description": "The number of rows","default":1},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "top_margin", "description": "The vertical distance between the middle of the top ROIs and the middle of the top target.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "bottom_margin", "description": "Same as top_margin, but for the bottom.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "right_margin", "description": "Same as top_margin, but for the right.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "left_margin", "description": "Same as top_margin, but for the left.","default":0.0},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "horizontal_fill", "description": "The proportion of the grid space used by the roi, horizontally.","default":0.90},
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":.001, "name": "vertical_fill", "description": "Same as horizontal_margin, but vertically.","default":0.90}
                                   ]}
                                   
    def __init__(self, n_rows=1, n_cols=1, top_margin=0, bottom_margin=0,
                 left_margin=0, right_margin=0, horizontal_fill=.9, vertical_fill=.9,
                 enable_diagnostics=False, device_id="unknown", save_success_images=False,
                 max_detection_attempts=5, enable_frame_averaging=True):
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
        self._top_margin =  top_margin
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
        self._max_detection_attempts = max_detection_attempts
        self._enable_frame_averaging = enable_frame_averaging
        self._frame_buffer = []  # Buffer for frame averaging
        
        if self._enable_diagnostics:
            self._diagnostics = TargetDetectionDiagnostics(device_id=device_id)
            logging.info(f"Target detection diagnostics enabled for device {device_id}")
        
        # if self._vertical_fill is None:
        #     self._vertical_fill = self._horizontal_fill
        # if self._right_margin is None:
        #     self._right_margin = self._left_margin
        # if self._bottom_margin is None:
        #     self._bottom_margin = self._top_margin

        super(TargetGridROIBuilder,self).__init__()

    def _find_blobs(self, im, scoring_fun):
        
        if len(im.shape) == 2:
            grey = im
        
        elif len(im.shape) == 3:
            grey = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        
        rad = int(self._adaptive_med_rad * im.shape[1])
        if rad % 2 == 0:
            rad += 1

        med = np.median(grey)
        scale = 255/(med)
        cv2.multiply(grey,scale,dst=grey)
        bin = np.copy(grey)
        score_map = np.zeros_like(bin)
        for t in range(0, 255,5):
            cv2.threshold(grey, t, 255,cv2.THRESH_BINARY_INV,bin)
            if np.count_nonzero(bin) > 0.7 * im.shape[0] * im.shape[1]:
                continue
            if CV_VERSION == 3:
                _, contours, h = cv2.findContours(bin,cv2.RETR_EXTERNAL,CHAIN_APPROX_SIMPLE)
            else:
                contours, h = cv2.findContours(bin,cv2.RETR_EXTERNAL,CHAIN_APPROX_SIMPLE)

            bin.fill(0)
            for c in contours:
                score = scoring_fun(c, im)
                if score >0:
                    cv2.drawContours(bin,[c],0,score,-1)
            cv2.add(bin, score_map,score_map)
        return score_map

    def _make_grid(self, n_col, n_row,
              top_margin=0.0, bottom_margin=0.0,
              left_margin=0.0, right_margin=0.0,
              horizontal_fill = 1.0, vertical_fill=1.0):

        y_positions = (np.arange(n_row) * 2.0 + 1) * (1-top_margin-bottom_margin)/(2*n_row) + top_margin
        x_positions = (np.arange(n_col) * 2.0 + 1) * (1-left_margin-right_margin)/(2*n_col) + left_margin
        all_centres = [np.array([x,y]) for x,y in itertools.product(x_positions, y_positions)]

        sign_mat = np.array([
            [-1, -1],
            [+1, -1],
            [+1, +1],
            [-1, +1]

        ])
        xy_size_vec = np.array([horizontal_fill/float(n_col), vertical_fill/float(n_row)]) / 2.0
        rectangles = [sign_mat *xy_size_vec + c for c in all_centres]
        return rectangles


    def _points_distance(self, pt1, pt2):
        x1 , y1  = pt1
        x2 , y2  = pt2
        return np.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

    def _score_targets(self,contour, im):

        area = cv2.contourArea(contour)
        perim = cv2.arcLength(contour,True)

        if perim == 0:
            return 0
        circul =  4 * np.pi * area / perim ** 2

        if circul < .8: # fixme magic number
            return 0
        return 1

    def _find_target_coordinates(self, img):
        '''
        Finds the coordinates of the three blobs on the given img with multi-attempt robust detection
        '''
        start_time = time.time() if self._enable_diagnostics else None
        
        # Try multiple attempts with different strategies
        for attempt in range(self._max_detection_attempts):
            logging.debug(f"Target detection attempt {attempt + 1}/{self._max_detection_attempts}")
            
            # Use frame averaging for noise reduction if enabled and we have buffered frames
            processed_img = self._prepare_image_for_detection(img, attempt)
            
            # Attempt detection on processed image
            result = self._single_detection_attempt(processed_img, attempt)
            
            if result is not None:
                # Success - log and return
                if self._enable_diagnostics:
                    processing_time = time.time() - start_time if start_time else None
                    self._log_successful_detection(processed_img, result, attempt, processing_time)
                return result
            
            # Failed attempt - add current image to buffer for potential averaging
            if self._enable_frame_averaging:
                self._update_frame_buffer(img)
        
        # All attempts failed
        if self._enable_diagnostics:
            processing_time = time.time() - start_time if start_time else None
            self._log_failed_detection(img, processing_time)
        
        logging.error(f"Target detection failed after {self._max_detection_attempts} attempts")
        return None
    
    def _prepare_image_for_detection(self, img, attempt):
        '''
        Prepare image for detection based on attempt number and available strategies
        '''
        if attempt == 0 or not self._enable_frame_averaging or len(self._frame_buffer) == 0:
            # First attempt or no averaging - use original image
            return img
        
        # Use frame averaging for noise reduction
        return self._create_averaged_frame(img)
    
    def _update_frame_buffer(self, img):
        '''
        Update the frame buffer for averaging, keeping only recent frames
        '''
        max_buffer_size = 3  # Keep last 3 frames for averaging
        
        # Convert to float for averaging if needed
        if img.dtype != np.float32:
            img_float = img.astype(np.float32)
        else:
            img_float = img.copy()
            
        self._frame_buffer.append(img_float)
        
        # Keep buffer size manageable
        if len(self._frame_buffer) > max_buffer_size:
            self._frame_buffer.pop(0)
    
    def _create_averaged_frame(self, current_img):
        '''
        Create an averaged frame from buffer + current image for noise reduction
        '''
        if len(self._frame_buffer) == 0:
            return current_img
        
        # Convert current image to float
        if current_img.dtype != np.float32:
            current_float = current_img.astype(np.float32)
        else:
            current_float = current_img.copy()
        
        # Average with buffered frames
        all_frames = self._frame_buffer + [current_float]
        averaged = np.mean(all_frames, axis=0)
        
        # Convert back to uint8
        return averaged.astype(np.uint8)
    
    def _single_detection_attempt(self, img, attempt):
        '''
        Perform a single detection attempt with progressive tolerance relaxation
        '''
        map = self._find_blobs(img, self._score_targets)
        bin = np.zeros_like(map)

        # Smart threshold selection: prioritize finding exactly 3 high-quality targets
        contours = []
        best_contours = []
        best_threshold = -1
        best_quality_score = -1
        optimal_threshold = -1
        
        for t in range(0, 255, 1):
            cv2.threshold(map, t, 255, cv2.THRESH_BINARY, bin)
            if CV_VERSION == 3:
                _, contours, h = cv2.findContours(bin, cv2.RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)
            else:
                contours, h = cv2.findContours(bin, cv2.RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)

            # Primary goal: find the first (lowest) threshold that gives exactly 3 targets
            if len(contours) == 3 and optimal_threshold == -1:
                # Verify these are high-quality circular targets
                quality_scores = [self._score_targets(c, img) for c in contours]
                if all(score > 0 for score in quality_scores):  # All targets are circular enough
                    optimal_threshold = t
                    best_contours = contours
                    best_threshold = t
                    break  # Use first good threshold, not maximum contours
            
            # Fallback: track the threshold with best quality targets (not just most contours)
            if len(contours) >= 3:
                # Score the quality of the top 3 contours by area (likely to be real targets)
                sorted_contours = sorted(contours, key=lambda c: cv2.contourArea(c), reverse=True)
                top_3_contours = sorted_contours[:3]
                quality_scores = [self._score_targets(c, img) for c in top_3_contours]
                avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0
                
                # Prefer higher quality over more contours
                if avg_quality > best_quality_score:
                    best_quality_score = avg_quality
                    best_contours = top_3_contours
                    best_threshold = t
        
        # Use results from optimal threshold or best quality fallback
        if optimal_threshold != -1:
            # Found exactly 3 targets at optimal threshold
            contours = best_contours
            threshold_used = optimal_threshold
            logging.debug(f"Found exactly 3 targets at optimal threshold {optimal_threshold} (attempt {attempt + 1})")
        elif len(best_contours) >= 3:
            # Use best quality targets as fallback
            contours = best_contours
            threshold_used = best_threshold
            logging.debug(f"Using 3 best quality targets from threshold {best_threshold} (attempt {attempt + 1}, quality score: {best_quality_score:.2f})")
        else:
            # No good targets found
            logging.debug(f"Could not find 3 quality targets on attempt {attempt + 1}. Found {len(best_contours)} targets at threshold {best_threshold}")
            return None  # Early return for this attempt
        
        if len(contours) < 3:
            logging.debug(f"Only found {len(contours)} targets on attempt {attempt + 1}")
            return None  # Early return for this attempt

        # Progressive diameter tolerance relaxation
        base_tolerance = 0.10
        tolerance_multiplier = 1.0 + (attempt * 0.5)  # Increase tolerance by 50% per attempt
        current_tolerance = min(base_tolerance * tolerance_multiplier, 0.30)  # Cap at 30%
        
        target_diams = [cv2.boundingRect(c)[2] for c in contours]
        mean_diam = np.mean(target_diams)
        mean_sd = np.std(target_diams)
        diameter_variation = mean_sd/mean_diam if mean_diam > 0 else 1.0

        if diameter_variation > current_tolerance:
            logging.debug(f"Diameter variation {diameter_variation:.3f} exceeds tolerance {current_tolerance:.3f} on attempt {attempt + 1}")
            return None  # Early return for this attempt

        # Success! Process the target coordinates
        src_points = []
        for c in contours:
            moms = cv2.moments(c)
            x , y = moms["m10"]/moms["m00"],  moms["m01"]/moms["m00"]
            src_points.append((x,y))

        a ,b, c = src_points
        pairs = [(a,b), (b,c), (a,c)]

        dists = [self._points_distance(*p) for p in pairs]
        # that is the AC pair
        hypo_vertices = pairs[np.argmax(dists)]

        # this is B : the only point not in (a,c)
        for sp in src_points:
            if not sp in hypo_vertices:
                break
        sorted_b = sp

        dist = 0
        for sp in src_points:
            if sorted_b is sp:
                continue
            # b-c is the largest distance, so we can infer what point is c
            if self._points_distance(sp, sorted_b) > dist:
                dist = self._points_distance(sp, sorted_b)
                sorted_c = sp

        # the remaining point is a
        sorted_a = [sp for sp in src_points if not sp is sorted_b and not sp is sorted_c][0]
        sorted_src_pts = np.array([sorted_a, sorted_b, sorted_c], dtype=np.float32)
        
        #sorted_src_pts will return something like this
        #[[1193.1302, 125.34195 ], [1209.0566, 857.9937  ], [  46.788918, 859.4524  ]]

        return sorted_src_pts
    
    def _log_successful_detection(self, img, result, attempt, processing_time):
        '''
        Log successful detection with multi-attempt context
        '''
        if not self._enable_diagnostics or not self._diagnostics:
            return
            
        target_coordinates = [(float(pt[0]), float(pt[1])) for pt in result]
        
        metadata = self._diagnostics.log_detection_attempt(
            image=img,
            targets_found=target_coordinates,
            expected_targets=3,
            threshold_used=None,  # Not available in success case
            circularity_scores=[],
            processing_time=processing_time
        )
        
        # Add multi-attempt specific metadata
        metadata['detection_attempts'] = attempt + 1
        metadata['used_frame_averaging'] = self._enable_frame_averaging and len(self._frame_buffer) > 0
        
        logging.info(f"Target detection SUCCESS on attempt {attempt + 1}: Found 3/3 targets")
        
        if self._save_success_images:
            self._diagnostics.save_detection_image(
                image=img,
                metadata=metadata,
                save_success=True,
                save_failed=False
            )
    
    def _log_failed_detection(self, img, processing_time):
        '''
        Log failed detection after all attempts
        '''
        if not self._enable_diagnostics or not self._diagnostics:
            return
            
        metadata = self._diagnostics.log_detection_attempt(
            image=img,
            targets_found=[],
            expected_targets=3,
            threshold_used=None,
            circularity_scores=[],
            processing_time=processing_time
        )
        
        # Add multi-attempt specific metadata
        metadata['detection_attempts'] = self._max_detection_attempts
        metadata['used_frame_averaging'] = self._enable_frame_averaging
        metadata['frame_buffer_size'] = len(self._frame_buffer)
        
        self._diagnostics.save_detection_image(
            image=img,
            metadata=metadata,
            save_success=False,
            save_failed=True
        )

    def _rois_from_img(self,img):
        '''
        Fit a ROI to the provided img
        '''
        
        reference_points = self._find_target_coordinates(img)
        
        # Handle graceful failure when target detection fails
        if reference_points is None:
            logging.warning("ROI building failed: could not detect required targets")
            return None, None
        
        #point 1 is the reference point at coords A,B; point 0 will be A,y and point 2 x,B
        #we then transform the ROIS on the assumption that those points are aligned perpendicularly in this way
        dst_points = np.array([(0,-1),
                               (0,0),
                               (-1,0)], dtype=np.float32)
                               
        wrap_mat = cv2.getAffineTransform(dst_points, reference_points)

        rectangles = self._make_grid(self._n_cols, self._n_rows,
                                     self._top_margin, self._bottom_margin,
                                     self._left_margin,self._right_margin,
                                     self._horizontal_fill, self._vertical_fill)

        shift = np.dot(wrap_mat, [1,1,0]) - reference_points[1] # point 1 is the ref which we have set at 0,0
        
        rois = []
        for i,r in enumerate(rectangles):
            r = np.append(r, np.zeros((4,1)), axis=1)
            mapped_rectangle = np.dot(wrap_mat, r.T).T
            mapped_rectangle -= shift
            ct = mapped_rectangle.reshape((1,4,2)).astype(np.int32)
            cv2.drawContours(img,[ct], -1, (255,0,0),1,LINE_AA)
            rois.append(ROI(ct, idx=i+1))
            
        #rois is an array of ROI objects
        #reference points is an array containing the abslolute coordinates of the three refs
        
        return reference_points, rois


