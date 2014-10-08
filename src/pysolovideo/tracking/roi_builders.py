__author__ = 'quentin'


import numpy as np
import cv2
import cv
# from pysolovideo.utils.memoisation import memoised_property


class ROI(object):

    def __init__(self, polygon, value=None, orientation = None, regions=None):

        # TODO if we do not need polygon, we can drop it
        self._polygon = np.array(polygon)
        self._value = value

        x,y,w,h = cv2.boundingRect(self._polygon)

        self._mask = np.zeros((h,w), np.uint8)
        cv2.drawContours(self._mask, [polygon], 0, 255,-1,offset=(-x,-y))

        self._rectangle = x,y,w,h

    def bounding_rect(self):
        raise NotImplementedError


    def mask(self):

        return


    @property
    def value(self):
        return self._value

    def __call__(self,img):
        x,y,w,h = self._rectangle
        out = img[y : y + h, x : x +w]

        assert(out.shape[0:2] == self._mask.shape)

        return out, self._mask


class BaseROIBuilder(object):

    def __call__(self, camera):
        for _, frame in camera:
            rois = self._rois_from_img(frame)
            # TODO here, we should make an average of a few frames
            break
        rois = self._sort_rois(rois)
        return rois


    def _sort_rois(self, rois):
        # TODO Implement the left to right/top to bottom sorting algo
        return rois

    def _rois_from_img(self,img):
        raise NotImplementedError



class DefaultROIBuilder(BaseROIBuilder):

    def _rois_from_img(self,img):
        h, w = img.shape[0],img.shape[1]
        return[
            ROI([
                (   0,        0       ),
                (   0,        w -1    ),
                (   h - 1,    w - 1   ),
                (   h - 1,    0       )]
        )]




class ImgMaskROIBuilder(BaseROIBuilder):
    """
    Initialised with an grey-scale image file.
    Each continuous region is used as a ROI.
    The colour of the ROI determines it's index
    """


    def __init__(self, mask_path):
        self._mask = cv2.imread(mask_path, cv2.CV_LOAD_IMAGE_GRAYSCALE)

    def _rois_from_img(self,img):
        if len(self._mask.shape) == 3:
            self._mask = cv2.cvtColor(self._mask, cv2.COLOR_BGR2GRAY)



        contours, hiera = cv2.findContours(np.copy(self._mask), cv.CV_RETR_EXTERNAL, cv.CV_CHAIN_APPROX_SIMPLE)

        rois = []
        for c in contours:
            tmp_mask = np.zeros_like(self._mask)
            cv2.drawContours(tmp_mask, [c],0, 1)

            value = int(np.median(self._mask[tmp_mask > 0]))

            rois.append(ROI(c, value))
        return rois


