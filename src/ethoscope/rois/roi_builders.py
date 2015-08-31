__author__ = 'quentin'

import numpy as np
import cv2


from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.description import DescribedObject



class ROI(object):
    __global_idx = 1
    def __init__(self, polygon, value=None, orientation = None, regions=None):

        # TODO if we do not need polygon, we can drop it
        self._polygon = np.array(polygon)
        if len(self._polygon.shape) == 2:
            self._polygon = self._polygon.reshape((self._polygon.shape[0],1,self._polygon.shape[1]))


        x,y,w,h = cv2.boundingRect(self._polygon)

        self._mask = np.zeros((h,w), np.uint8)
        cv2.drawContours(self._mask, [self._polygon], 0, 255,-1,offset=(-x,-y))

        self._rectangle = x,y,w,h
        # todo NOW! sort rois by value. if no values, left to right/ top to bottom!

        self._idx = self.__global_idx
        if value is None:
            self._value = self._idx
        else:
            self._value = value

        ROI.__global_idx +=1
    def __del__(self):
        ROI.__global_idx -=1

    @property
    def idx(self):
        return self._idx
    def bounding_rect(self):
        raise NotImplementedError


    def mask(self):
        return self._mask

    @property
    def offset(self):
        x,y,w,h = self._rectangle
        return x,y

    @property
    def polygon(self):
        return self._polygon


    @property
    def longest_axis(self):
        x,y,w,h = self._rectangle
        return float(max(w, h))
    @property
    def rectangle(self):
        return self._rectangle

    def get_feature_dict(self):
        x,y,w,h = self._rectangle
        return {"x":x,
                "y":y,
                "w":w,
                "h":h,
                "value":self._value,
                "idx":self.idx
        }





    def set_value(self, new_val):
        self._value = new_val

    @property
    def value(self):
        return self._value

    def __call__(self,img):
        x,y,w,h = self._rectangle



        try:
            out = img[y : y + h, x : x +w]
        except:
            raise EthoscopeException("Error whilst slicing region of interest %s" % str(self.get_feature_dict()), img)

        if out.shape[0:2] != self._mask.shape:
            raise EthoscopeException("Error whilst slicing region of interest. Possibly, the region out of the image: %s" % str(self.get_feature_dict()), img )

        return out, self._mask


class BaseROIBuilder(DescribedObject):

    def __call__(self, camera):

        accum = []
        if isinstance(camera, np.ndarray):
            accum = np.copy(camera)

        else:
            for i, (_, frame) in enumerate(camera):
                accum.append(frame)
                if i  >= 5:
                    break

            accum = np.median(np.array(accum),0).astype(np.uint8)
        try:

            rois = self._rois_from_img(accum)
        except Exception as e:
            if not isinstance(camera, np.ndarray):
                del camera
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

    def _rois_from_img(self,img):
        h, w = img.shape[0],img.shape[1]
        return[
            ROI([
                (   0,        0       ),
                (   0,        h -1    ),
                (   w - 1,    h - 1   ),
                (   w - 1,    0       )]
        )]

