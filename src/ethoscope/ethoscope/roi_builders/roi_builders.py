from ethoscope.core.roi import ROI

__author__ = 'quentin'

import numpy as np

from ethoscope.utils.description import DescribedObject
from ethoscope.utils.debug import EthoscopeException
import logging
import traceback


class BaseROIBuilder(DescribedObject):

    def __init__(self):
        """
        Template to design ROIBuilders. Subclasses must implement a ``_rois_from_img`` method.
        """
        pass

    def build(self, input):
        """
        Uses an input (image or camera) to build ROIs.
        When a camera is used, several frames are acquired and averaged to build a reference image.

        :param input: Either a camera object, or an image.
        :type input: :class:`~ethoscope.hardware.input.camera.BaseCamera` or :class:`~numpy.ndarray`
        :return: list(:class:`~ethoscope.core.roi.ROI`)
        """

        accum = []
        if isinstance(input, np.ndarray):
            accum = np.copy(input)

        else:
            for i, (_, frame) in enumerate(input):
                accum.append(frame)
                if i  >= 5:
                    break

            accum = np.median(np.array(accum),0).astype(np.uint8)
        try:
            reference_points, rois = self._rois_from_img(accum)
            
            # Handle graceful failure when _rois_from_img returns None
            if reference_points is None or rois is None:
                logging.warning("ROI building failed gracefully, no targets detected")
                # Clean up input if it's not an array (i.e., if it's a camera object)
                if not isinstance(input, np.ndarray):
                    del input
                raise EthoscopeException("ROI building failed: insufficient targets detected")
            
        except EthoscopeException:
            # Re-raise EthoscopeException without modification (input already cleaned up above)
            raise
        except Exception as e:
            # Handle other exceptions
            if not isinstance(input, np.ndarray):
                del input
            logging.error(traceback.format_exc())
            raise e

        rois_w_no_value = [r for r in rois if r.value is None]

        if len(rois_w_no_value) > 0:
            rois = self._spatial_sorting(rois)
        else:
            rois = self._value_sorting(rois)

        return reference_points, rois



    def _rois_from_img(self,img):
        raise NotImplementedError

    def _spatial_sorting(self, rois):
        '''
        returns a sorted list of ROIs objects it in ascending order based on the first value in the rectangle property
        '''
        return sorted(rois, key=lambda x: x.rectangle[0], reverse=False)

    def _value_sorting(self, rois):
        '''
        returns a sorted list of ROIs objects it in ascending order based on the .value property
        '''
        return sorted(rois, key=lambda x: x.value, reverse=False)

