__author__ = 'quentin'


import numpy as np


class ROI(object):

    def __init__(self, polygon, orientation = None, regions=None):
        self._polygon = np.array(polygon)

    def bounding_rect(self):
        raise NotImplementedError

    def __call__(self,img):
        # TODO should return the bounding rectangle and the mask. Mask can be memoized/ cached (joblib)
        return img, None


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

