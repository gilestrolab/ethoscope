from ethoscope.core.roi import ROI

__author__ = 'quentin'

import numpy as np

from ethoscope.utils.description import DescribedObject
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
            rois = self._rois_from_img(accum)
        except Exception as e:
            if not isinstance(input, np.ndarray):
                del input
            logging.error(traceback.format_exc(e))
            raise e

        rois_w_no_value = [r for r in rois if r.value is None]

        if len(rois_w_no_value) > 0:
            rois = self._spatial_sorting(rois)
        else:
            rois = self._value_sorting(rois)

        return rois



    def _rois_from_img(self,img):
        raise NotImplementedError

    def _spatial_sorting(self, rois):
        out = []
        for i, sr in enumerate(sorted(rois, lambda  a,b: a.rectangle[0] - b.rectangle[0])):
            if sr.value is None:
                sr.set_value(i)
            out.append(sr)
        return out

    def _value_sorting(self, rois):
        out = []
        for i, sr in enumerate(sorted(rois, lambda  a,b: a.value - b.value)):
            out.append(sr)
        return out


class DefaultROIBuilder(BaseROIBuilder):


    """
    The default ROI builder. It simply defines the entire image as a unique ROI.
    """


    def _rois_from_img(self,img):
        h, w = img.shape[0],img.shape[1]
        return[
            ROI(np.array([
                (   0,        0       ),
                (   0,        h -1    ),
                (   w - 1,    h - 1   ),
                (   w - 1,    0       )])
            , idx=1)]

