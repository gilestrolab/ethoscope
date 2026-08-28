__author__ = "quentin"

import logging
import traceback

import numpy as np

from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.description import DescribedObject


class BaseROIBuilder(DescribedObject):

    def __init__(self):
        """
        Template to design ROIBuilders. Subclasses must implement a ``_rois_from_img`` method.
        """
        pass

    # How many times to resample the camera when the targets are not found.
    # Each pass costs six frames, so about a second at 5 fps. ROIs are built once
    # per experiment, so a few seconds spent here is cheap against a run that
    # fails to start.
    _MAX_ACQUISITION_PASSES = 4

    def _reference_image(self, camera):
        """Median of six freshly acquired frames.

        Taking the median rejects flies moving through the field, so the targets
        are what survives.
        """
        accum = []
        for i, (_, frame) in enumerate(camera):
            accum.append(frame)
            if i >= 5:
                break
        if not accum:
            return None
        return np.median(np.array(accum), 0).astype(np.uint8)

    def build(self, input):
        """
        Uses an input (image or camera) to build ROIs.
        When a camera is used, several frames are acquired and averaged to build a reference image.

        :param input: Either a camera object, or an image.
        :type input: :class:`~ethoscope.hardware.input.camera.BaseCamera` or :class:`~numpy.ndarray`
        :return: list(:class:`~ethoscope.core.roi.ROI`)
        """

        # Reason: the detector's own retries all ran against a single collapsed
        # image, so its three "attempts" only varied the threshold and averaged
        # that image with a stale copy of itself. The camera was sampled once,
        # which meant a fly parked on a target, or a transient reflection, made
        # the whole run fail with no way to recover.
        #
        # Measured over 197 archive frames with recorded target coordinates:
        # the detector refuses 65, and simply running it again on a different
        # frame of the same arena resolves 27 of them. That is the one thing the
        # old retry could not do. It is the same detector throughout, so its
        # precision is unchanged; only the input improves.
        is_array = isinstance(input, np.ndarray)
        # A caller who hands over a single image gets exactly one attempt; there
        # is nothing else to sample.
        passes = 1 if is_array else self._MAX_ACQUISITION_PASSES

        reference_points = rois = None
        last_error = None

        for attempt in range(passes):
            accum = np.copy(input) if is_array else self._reference_image(input)
            if accum is None:
                break

            try:
                reference_points, rois = self._rois_from_img(accum)
            except EthoscopeException as e:
                reference_points = rois = None
                last_error = e
            except Exception as e:
                if not is_array:
                    del input
                logging.error(traceback.format_exc())
                raise e

            if reference_points is not None and rois is not None:
                if attempt:
                    logging.info(f"Targets found on acquisition pass {attempt + 1}")
                break

            if attempt + 1 < passes:
                logging.warning(
                    f"No targets in acquisition pass {attempt + 1} of {passes}; "
                    "taking a fresh set of frames"
                )

        if reference_points is None or rois is None:
            logging.warning("ROI building failed gracefully, no targets detected")
            if not is_array:
                del input
            raise last_error or EthoscopeException(
                "ROI building failed: insufficient targets detected"
            )

        rois_w_no_value = [r for r in rois if r.value is None]

        if len(rois_w_no_value) > 0:
            rois = self._spatial_sorting(rois)
        else:
            rois = self._value_sorting(rois)

        return reference_points, rois

    def _rois_from_img(self, img):
        raise NotImplementedError

    def _spatial_sorting(self, rois):
        """
        returns a sorted list of ROIs objects it in ascending order based on the first value in the rectangle property
        """
        return sorted(rois, key=lambda x: x.rectangle[0], reverse=False)

    def _value_sorting(self, rois):
        """
        returns a sorted list of ROIs objects it in ascending order based on the .value property
        """
        return sorted(rois, key=lambda x: x.value, reverse=False)
