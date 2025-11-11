__author__ = "quentin"
# flake8: noqa: E402
from collections import deque

import cv2

from .adaptive_bg_tracker import BackgroundModel

CV_VERSION = int(cv2.__version__.split(".")[0])

import logging
import os

import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial import distance

from ethoscope.core.data_point import DataPoint
from ethoscope.core.variables import HeightVariable
from ethoscope.core.variables import PhiVariable
from ethoscope.core.variables import WidthVariable
from ethoscope.core.variables import XPosVariable
from ethoscope.core.variables import YPosVariable
from ethoscope.trackers.trackers import BaseTracker
from ethoscope.trackers.trackers import NoPositionError


class ForegroundModel:

    def __init__(
        self,
        fg_data=None,
        visualise=False,
    ):
        """
        set the size of the statistical sample for the running average and the hard limits to populate the sample
        :param sample_size: the size of the sample used for the statiscal model
        :type sample_size: int
        :param normal_limits: a tuple indicating the limits to use to initially populate the sample
        :type normal_limits: tuple
        :param visualise: shows a real time graph of the characteristics of the sample
        :type visualise: bool
        :param tolerance: tolerance factor to be used to decide if contour is an outlier
        :type tolerance: float

        :return:
        """

        if fg_data is None:
            fg_data = {"sample_size": 400, "normal_limits": (50, 200), "tolerance": 0.8}
        self.sample_size = fg_data["sample_size"]
        self.normal_limits = fg_data["normal_limits"]
        self.tolerance = fg_data["tolerance"]
        self._visualise = visualise

        self.limited_pool = deque(maxlen=self.sample_size)
        self.total_pool = []

        if self._visualise:
            plt.ion()
            self.fig, (self.ax1, self.ax2) = plt.subplots(1, 2)
            self.fig.suptitle(
                f"Live analysis of contours - sample size {self.sample_size} - tolerance {self.tolerance}"
            )

    def _is_outlier(self, value, tolerance=0.7):
        """
        Not intended as statistical outlier (we don't compare against std)
        Anything bigger or smaller than tolerance * mean is excluded
        """
        return abs(value - np.mean(self.limited_pool)) > tolerance * np.mean(
            self.limited_pool
        )

    def is_contour_valid(self, contour, img):

        area = cv2.contourArea(contour)

        np.mean(self.limited_pool)
        np.std(self.limited_pool)

        self.total_pool.append(area)

        if self._visualise and len(self.total_pool) % 1000 == 0:

            # refresh plot every 1000 contours received
            self.ax1.clear()  # not sure why I need to clear the axis here. In principle it should not be necessary.
            self.ax2.clear()
            self.ax1.set_title("All contours")
            self.ax2.set_title("Within limits")

            self.bp1 = self.ax1.boxplot(self.total_pool)
            self.bp2 = self.ax2.boxplot(self.limited_pool)

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

        # ALWAYS enforce hard limits to prevent false positives
        if area < self.normal_limits[0] or area > self.normal_limits[1]:
            return False

        # The initial phase. This is not completely agnostic: we add everything to the training pool as long as it is within the reasonable limits
        # Limits are quite loose though and refinement happens during the actual tracking
        if len(self.limited_pool) < self.sample_size:
            self.limited_pool.append(area)
            return True

        # Once we have a running queue, we add everything that is not an outlier AND within hard limits
        if not self._is_outlier(area, tolerance=self.tolerance):
            self.limited_pool.append(area)
            return True

        else:
            return False


class MultiFlyTracker(BaseTracker):
    _description = {
        "overview": "An experimental tracker to monitor several animals per ROI.",
        "arguments": [],
    }

    def __init__(
        self,
        roi,
        data=None,
    ):
        """
        An adaptive background subtraction model to find position of multiple animals in one roi.

        Improved to handle different lighting conditions and uses consistent foreground model
        for all size validations.

        :param roi: Region of interest
        :param data: Configuration dictionary with tracking parameters
        :return:
        """

        if data is None:
            data = {
                "maxN": 50,
                "visualise": False,
                "fg_data": {
                    "sample_size": 400,
                    "normal_limits": (50, 200),
                    "tolerance": 0.8,
                },
                "adaptive_threshold": True,
                "min_fg_threshold": 10,
                "max_fg_threshold": 50,
            }
        self.maxN = data["maxN"]
        self._visualise = data["visualise"]

        # Adaptive thresholding parameters
        self._adaptive_threshold = data.get("adaptive_threshold", True)
        self._min_fg_threshold = data.get("min_fg_threshold", 10)
        self._max_fg_threshold = data.get("max_fg_threshold", 50)
        self._current_fg_threshold = 20  # Starting threshold

        self._previous_shape = None

        # FIXED: Remove conflicting _object_expected_size and rely entirely on ForegroundModel
        # The ForegroundModel already handles size validation through normal_limits
        # Calculate max area from foreground model limits instead
        fg_data = data.get("fg_data", {"normal_limits": (50, 200)})
        max_expected_area = fg_data["normal_limits"][1] * 2  # Allow 2x max normal size
        self._max_area_ratio = max_expected_area / (
            roi.polygon.shape[0] * roi.polygon.shape[1] * 0.5
        )  # Rough ROI area estimate

        self._smooth_mode = deque()
        self._smooth_mode_tstamp = deque()
        self._smooth_mode_window_dt = 30 * 1000  # miliseconds

        try:
            self._fg_model = ForegroundModel(
                fg_data=data["fg_data"], visualise=self._visualise
            )
        except Exception:
            # we roll to the default values
            self._fg_model = ForegroundModel()

        self._bg_model = BackgroundModel()

        self._max_m_log_lik = 6.0
        self._buff_grey = None
        self._buff_object = None
        self._buff_object_old = None
        self._buff_grey_blurred = None
        self._buff_fg = None
        self._buff_convolved_mask = None
        self._buff_fg_backup = None
        self._buff_fg_diff = None
        self._old_sum_fg = 0

        self.last_positions = np.zeros((self.maxN, 2))

        if self._visualise:
            self.multi_fly_tracker_window = "tracking_preview"
            cv2.namedWindow(self.multi_fly_tracker_window, cv2.WINDOW_AUTOSIZE)

        super().__init__(roi, data)

    def _pre_process_input_minimal(self, img, mask, t, darker_fg=True):
        """
        Receives the whole img, a mask describing the ROI and time t
        Returns a grey converted image in which the tracking routine should then look for objects
        Enhanced with adaptive preprocessing for different lighting conditions.
        """

        # Calculate blur radius from foreground model limits instead of hardcoded size
        # Use median expected size from normal_limits for blur calculation
        median_expected_area = np.mean(self._fg_model.normal_limits)
        median_diameter = 2 * np.sqrt(median_expected_area / np.pi)
        blur_rad = max(1, int(median_diameter / 4.0))

        # and should always be an odd number
        if blur_rad % 2 == 0:
            blur_rad += 1

        # creates a buffered grey image if does not exist yet
        if self._buff_grey is None:
            self._buff_grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            if mask is None:
                mask = np.ones_like(self._buff_grey) * 255

        # then copy the grey version of img into it
        cv2.cvtColor(img, cv2.COLOR_BGR2GRAY, self._buff_grey)

        # and apply gaussian blur with the radius specified above
        cv2.GaussianBlur(self._buff_grey, (blur_rad, blur_rad), 1.2, self._buff_grey)
        if darker_fg:
            cv2.subtract(255, self._buff_grey, self._buff_grey)

        # Adaptive image scaling based on lighting conditions
        mean = cv2.mean(self._buff_grey, mask)

        # Enhanced scaling for different lighting conditions
        if mean[0] > 150:  # Bright image
            # For bright images, use more aggressive normalization
            target_mean = 100.0
        elif mean[0] < 80:  # Dark image
            # For dark images, use gentler normalization
            target_mean = 140.0
        else:  # Normal lighting
            target_mean = 128.0

        scale = target_mean / mean[0]
        cv2.multiply(self._buff_grey, scale, dst=self._buff_grey)

        # Apply histogram equalization for very bright or very dark images
        if mean[0] > 180 or mean[0] < 60:
            self._buff_grey = cv2.equalizeHist(self._buff_grey)

        # applies the mask if exists
        if mask is not None:
            cv2.bitwise_and(self._buff_grey, mask, self._buff_grey)

        return self._buff_grey

    def _closest_node(self, node, nodes):
        """
        Find the closest distance between node and the vector of nodes
        Returns the value found and its index in nodes
        """
        d = distance.cdist([node], nodes)
        return d.min(), d.argmin()

    def _apply_morphological_filtering(self, fg_img):
        """
        Apply morphological operations to remove compression artifacts and noise.
        Enhanced to better handle large false positive regions.

        Args:
            fg_img: Foreground image to filter

        Returns:
            Filtered foreground image
        """
        # Calculate kernel size based on expected fly size
        median_expected_area = np.mean(self._fg_model.normal_limits)
        median_diameter = int(2 * np.sqrt(median_expected_area / np.pi))

        # More aggressive opening to break up large connected regions from compression artifacts
        opening_kernel_size = max(
            3, median_diameter // 4
        )  # Larger kernel to break connections
        opening_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (opening_kernel_size, opening_kernel_size)
        )

        # Smaller closing to avoid merging separate objects
        closing_kernel_size = max(2, median_diameter // 8)  # Much smaller closing
        closing_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (closing_kernel_size, closing_kernel_size)
        )

        # Apply more aggressive morphological opening first
        cv2.morphologyEx(fg_img, cv2.MORPH_OPEN, opening_kernel, dst=fg_img)

        # Then minimal closing to preserve individual objects
        cv2.morphologyEx(fg_img, cv2.MORPH_CLOSE, closing_kernel, dst=fg_img)

        # Additional filtering: remove very large connected components
        # Find connected components and filter by size
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            fg_img, connectivity=8
        )

        # Create filtered image
        filtered_img = np.zeros_like(fg_img)

        for i in range(1, num_labels):  # Skip background (label 0)
            area = stats[i, cv2.CC_STAT_AREA]

            # Only keep components within reasonable size range
            # Upper limit: 3x max normal size to handle edge cases
            max_reasonable_area = self._fg_model.normal_limits[1] * 3

            if self._fg_model.normal_limits[0] <= area <= max_reasonable_area:
                # Keep this component
                filtered_img[labels == i] = 255

        # Copy filtered result back to input
        fg_img[:] = filtered_img

        logging.debug(
            f"Applied enhanced morphological filtering: opening({opening_kernel_size}), closing({closing_kernel_size}), removed {num_labels-1-np.count_nonzero(np.unique(filtered_img))+1} large components"
        )

        return fg_img

    def _find_position(self, img, mask, t):
        """
        Middleman between the tracker and the actual tracking routine
        It cuts the portion defined by mask (i.e. the ROI), converts it to grey and passes it on to the actual tracking routine
        to look for the flies to track. The result of the tracking routine is a list of points describing the objects found in that ROI
        """

        grey = self._pre_process_input_minimal(img, mask, t)
        try:
            return self._track(img, grey, mask, t)
        except NoPositionError as e:
            self._bg_model.update(grey, t)
            raise NoPositionError from e

    def _track(self, img, grey, mask, t):
        """
        The tracking routine
        Runs once per ROI
        """

        if self._bg_model.bg_img is None:
            self._buff_fg = np.empty_like(grey)
            self._buff_object = np.empty_like(grey)
            self._buff_fg_backup = np.empty_like(grey)
            raise NoPositionError

        bg = self._bg_model.bg_img.astype(np.uint8)
        cv2.subtract(grey, bg, self._buff_fg)

        # Adaptive threshold based on image statistics
        if self._adaptive_threshold:
            # Calculate adaptive threshold based on foreground statistics
            fg_mean = (
                np.mean(self._buff_fg[self._buff_fg > 0])
                if np.any(self._buff_fg > 0)
                else 20
            )
            self._current_fg_threshold = max(
                self._min_fg_threshold, min(self._max_fg_threshold, int(fg_mean * 0.3))
            )

        cv2.threshold(
            self._buff_fg,
            self._current_fg_threshold,
            255,
            cv2.THRESH_TOZERO,
            dst=self._buff_fg,
        )

        # Apply morphological filtering to remove compression artifacts
        self._apply_morphological_filtering(self._buff_fg)

        self._buff_fg_backup = np.copy(self._buff_fg)

        n_fg_pix = np.count_nonzero(self._buff_fg)
        prop_fg_pix = n_fg_pix / (1.0 * grey.shape[0] * grey.shape[1])
        is_ambiguous = False

        # Use foreground-model-based max area calculation
        if prop_fg_pix > self._max_area_ratio:
            self._bg_model.increase_learning_rate()
            logging.debug(
                f"Too much foreground: {prop_fg_pix:.3f} > {self._max_area_ratio:.3f}"
            )
            raise NoPositionError

        if prop_fg_pix == 0:
            self._bg_model.increase_learning_rate()
            raise NoPositionError

        if CV_VERSION == 3:
            _, contours, hierarchy = cv2.findContours(
                self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
        else:
            contours, hierarchy = cv2.findContours(
                self._buff_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

        contours = [cv2.approxPolyDP(c, 1.2, True) for c in contours]

        valid_contours = []

        if len(contours) == 0:
            self._bg_model.increase_learning_rate()
            logging.debug(
                f"No contours detected (threshold: {self._current_fg_threshold})"
            )
            raise NoPositionError

        else:
            for c in contours:
                if self._fg_model.is_contour_valid(c, img):
                    valid_contours.append(c)

            # If no valid contours found but contours exist, log for debugging
            if len(valid_contours) == 0 and len(contours) > 0:
                areas = [cv2.contourArea(c) for c in contours]
                logging.debug(
                    f"No valid contours: found {len(contours)} contours with areas {areas}, limits: {self._fg_model.normal_limits}"
                )

        out_pos = []

        for _n_vc, vc in enumerate(valid_contours):

            # calculates the parameters to draw the centroid
            (x, y), (w, h), angle = cv2.minAreaRect(vc)

            # adjust the orientation for consistency
            if w < h:
                angle -= 90
                w, h = h, w
            angle = angle % 180

            # ignore if the ellipse is drawn outside the actual picture
            h_im = min(grey.shape)
            w_im = max(grey.shape)
            max_h = 2 * h_im
            if w > max_h or h > max_h:
                continue

            pos = x + 1.0j * y
            pos /= w_im

            cv2.ellipse(
                self._buff_fg, ((x, y), (int(w * 1.5), int(h * 1.5)), angle), 255, 1
            )

            # store the blob info in a list
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
            self._bg_model.increase_learning_rate()
            logging.debug(
                f"No valid positions found after processing {len(valid_contours)} valid contours"
            )
            raise NoPositionError

        # Limit to maxN detections to prevent false positives
        if len(out_pos) > self.maxN:
            # Sort by area (larger flies are more likely to be real)
            out_pos_with_area = [
                (pos, int(pos["w"]) * int(pos["h"])) for pos in out_pos
            ]  # w*h as area proxy
            out_pos_with_area.sort(key=lambda x: x[1], reverse=True)
            out_pos = [pos for pos, area in out_pos_with_area[: self.maxN]]
            logging.debug(
                f"Limited detections from {len(out_pos_with_area)} to {len(out_pos)}"
            )

        cv2.bitwise_and(self._buff_fg_backup, self._buff_fg, self._buff_fg_backup)

        if mask is not None:
            cv2.bitwise_and(self._buff_fg, mask, self._buff_fg)

        if is_ambiguous:
            self._bg_model.increase_learning_rate()
            self._bg_model.update(grey, t)

        else:
            self._bg_model.decrease_learning_rate()
            self._bg_model.update(grey, t, self._buff_fg)

        return out_pos


class HaarTracker(BaseTracker):

    _description = {
        "overview": "An experimental tracker to monitor several animals per ROI using a Haar Cascade.",
        "arguments": [],
    }

    def __init__(
        self,
        roi,
        data=None,
    ):
        """
        An adaptive background subtraction model to find position of one animal in one roi using a Haar Cascade.
        example of data
        """

        if data is None:
            data = {
                "maxN": 50,
                "cascade": "cascade.xml",
                "scaleFactor": 1.1,
                "minNeighbors": 3,
                "flags": 0,
                "minSize": (15, 15),
                "maxSize": (20, 20),
                "visualise": False,
            }
        if not os.path.exists(data["cascade"]):
            print("A valid xml cascade file could not be found.")
            raise

        self.fly_cascade = cv2.CascadeClassifier(data["cascade"])

        self._visualise = data["visualise"]
        self.maxN = data["maxN"]

        self._haar_prmts = {
            key: data[key]
            for key in ["scaleFactor", "minNeighbors", "flags", "minSize", "maxSize"]
        }

        self.last_positions = np.zeros((self.maxN, 2))

        if self._visualise:
            self._multi_fly_tracker_window = "tracking_preview"
            cv2.namedWindow(self._multi_fly_tracker_window, cv2.WINDOW_AUTOSIZE)

        super().__init__(roi, data)

    def _pre_process_input(self, img, mask=None):
        """ """

        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if mask is not None:
            cv2.bitwise_and(grey, mask, grey)

        return grey

    def _find_position(self, img, mask, t):
        """
        Middleman between the tracker and the actual tracking routine
        It cuts the portion defined by mask (i.e. the ROI), converts it to grey and passes it on to the actual tracking routine
        to look for the flies to track. The result of the tracking routine is a list of points describing the objects found in that ROI
        """

        grey = self._pre_process_input(img, mask)
        return self._track(img, grey, mask, t)

    def _track(self, img, grey, mask, t):
        """
        The tracking routine
        Runs once per ROI
        """
        pmts = self._haar_prmts
        flies = self.fly_cascade.detectMultiScale(
            img,
            scaleFactor=pmts["scaleFactor"],
            minNeighbors=pmts["minNeighbors"],
            flags=pmts["flags"],
            minSize=pmts["minSize"],
            maxSize=pmts["maxSize"],
        )

        out_pos = []

        for x, y, w, h in flies:
            # cv2.rectangle(img,(x,y),(x+w,y+h),(255,255,0),2)

            x = x + w / 2
            y = y + h / 2

            # store the blob info in a list
            x_var = XPosVariable(int(round(x)))
            y_var = YPosVariable(int(round(y)))
            w_var = WidthVariable(int(round(w)))
            h_var = HeightVariable(int(round(h)))
            phi_var = PhiVariable(0.0)

            out = DataPoint([x_var, y_var, w_var, h_var, phi_var])
            out_pos.append(out)

        # and show if asked
        if self._visualise:
            cv2.imshow(self._multi_fly_tracker_window, img)

        return out_pos
