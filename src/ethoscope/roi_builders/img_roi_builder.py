import cv
import cv2
import numpy as np
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI


class ImgMaskROIBuilder(BaseROIBuilder):
    """
    Class to build rois from greyscale image file.
    Each continuous region is used as a ROI.
    The greyscale value inside the ROI determines it's value.

    IMAGE HERE

    """


    def __init__(self, mask_path):
        self._mask = cv2.imread(mask_path, cv2.CV_LOAD_IMAGE_GRAYSCALE)
        super(ImgMaskROIBuilder,self).__init__()


    def _rois_from_img(self, img):

        if len(self._mask.shape) == 3:
            self._mask = cv2.cvtColor(self._mask, cv2.COLOR_BGR2GRAY)

        contours, hiera = cv2.findContours(np.copy(self._mask), cv.CV_RETR_EXTERNAL, cv.CV_CHAIN_APPROX_SIMPLE)

        rois = []
        for i,c in enumerate(contours):
            tmp_mask = np.zeros_like(self._mask)
            cv2.drawContours(tmp_mask, [c],0, 1)

            value = int(np.median(self._mask[tmp_mask > 0]))

            rois.append(ROI(c, i+1, value))

        return rois