import cv2

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

try:
    from cv2 import CV_LOAD_IMAGE_GRAYSCALE as IMG_READ_FLAG_GREY
    from cv import CV_RETR_EXTERNAL as RETR_EXTERNAL
    from cv import CV_CHAIN_APPROX_SIMPLE as CHAIN_APPROX_SIMPLE
except ImportError:
    from cv2 import IMREAD_GRAYSCALE as IMG_READ_FLAG_GREY
    from cv2 import RETR_EXTERNAL, CHAIN_APPROX_SIMPLE

import numpy as np
from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.core.roi import ROI


class ImgMaskROIBuilder(BaseROIBuilder):

    def __init__(self, mask_path):
        """
        Class to build rois from greyscale image file.
        Each continuous region is used as a ROI.
        The greyscale value inside the ROI determines it's value.

        IMAGE HERE

        """


        self._mask = cv2.imread(mask_path, IMG_READ_FLAG_GREY)

        super(ImgMaskROIBuilder,self).__init__()


    def _rois_from_img(self, img):

        if len(self._mask.shape) == 3:
            self._mask = cv2.cvtColor(self._mask, cv2.COLOR_BGR2GRAY)
        if CV_VERSION == 3:
            _, contours, hiera = cv2.findContours(np.copy(self._mask), RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)
        else:
            contours, hiera = cv2.findContours(np.copy(self._mask), RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)

        rois = []
        for i,c in enumerate(contours):
            tmp_mask = np.zeros_like(self._mask)
            cv2.drawContours(tmp_mask, [c],0, 1)

            value = int(np.median(self._mask[tmp_mask > 0]))

            rois.append(ROI(c, i+1, value))

        return rois