import cv2
import numpy as np
from ethoscope.utils.debug import EthoscopeException

__author__ = 'quentin'


class ROI(object):

    def __init__(self, polygon, idx, value=None, orientation = None, regions=None):
        """
        Class to define a region of interest(ROI).
        Internally, ROIs are single polygons.
        At the moment, they cannot have any holes.
        The polygon defining the ROI is used to draw a mask to exclude off-target pixels (so cross-ROI info).

        :param polygon: An array of points
        :type polygon: :class:`~numpy.ndarray`
        :param idx: the index of this ROI
        :type idx: int
        :param value: an optional value to be save for this ROI (e.g. to define left and right side)
        :param orientation: Optional orientation Not implemented yet
        :param regions: Optional sub-regions within the ROI. Not implemented yet

        """

        # TODO if we do not need polygon, we can drop it
        self._polygon = np.array(polygon)
        if len(self._polygon.shape) == 2:
            self._polygon = self._polygon.reshape((self._polygon.shape[0],1,self._polygon.shape[1]))


        x,y,w,h = cv2.boundingRect(self._polygon)

        self._mask = np.zeros((h,w), np.uint8)
        cv2.drawContours(self._mask, [self._polygon], 0, 255,-1,offset=(-x,-y))

        self._rectangle = x,y,w,h
        # todo NOW! sort rois by value. if no values, left to right/ top to bottom!
        self._idx = idx

        if value is None:
            self._value = self._idx
        else:
            self._value = value

    @property
    def idx(self):
        """
        :return: The index of this ROI
        :rtype: int
        """
        return self._idx

    def bounding_rect(self):
        raise NotImplementedError


    def mask(self):
        """
        :return: The mask as a single chanel, `uint8` image.
        :rtype: :class:`~numpy.ndarray`
        """
        return self._mask

    @property
    def offset(self):
        """
        :return: the x,y offset of the ROI compared to the frame it was build on.
        :rtype: (int,int)
        """
        x,y,w,h = self._rectangle
        return x,y

    @property
    def polygon(self):
        """
        :return: the internal polygon defining the ROI.
        :rtype: :class:`~numpy.ndarray`
        """
        return self._polygon


    @property
    def longest_axis(self):
        """
        :return: the value of the longest axis (w or h)
        :rtype: float
        """
        x,y,w,h = self._rectangle
        return float(max(w, h))

    @property
    def rectangle(self):
        """
        :return: The upright bounding rectangle to the ROI formatted (x,y,w,h). Where x and y are to coordinates of the top left corner
        :rtype: (int,int,int,int)
        """
        return self._rectangle

    def get_feature_dict(self):
        """
        :return: A dictionary of freatures for this roi. It containes the folowing fields:

        * "x"
        * "y"
        * "w"
        * "h"
        * "value"
        * "idx"

        :rtype: dict
        """
        x,y,w,h = self._rectangle
        return {"x":x,
                "y":y,
                "w":w,
                "h":h,
                "value":self._value,
                "idx":self.idx
        }





    def set_value(self, new_val):
        """
        :param new_val: assign a nex value to a ROI
        """
        self._value = new_val

    @property
    def value(self):
        """
        :return: the value of a ROI
        """
        return self._value

    def apply(self,img):
        """
        Cut an image where the ROI is defined.

        :param img: An image. Typically either one or three channels `uint8`.
        :type img: :class:`~numpy.ndarray`
        :return: a tuple containing the resulting cropped image and the associated mask (both have the same dimension).
        :rtype: (:class:`~numpy.ndarray`, :class:`~numpy.ndarray`)
        """
        x,y,w,h = self._rectangle



        try:
            out = img[y : y + h, x : x +w]
        except:
            raise EthoscopeException("Error whilst slicing region of interest %s" % str(self.get_feature_dict()), img)

        if out.shape[0:2] != self._mask.shape:
            raise EthoscopeException("Error whilst slicing region of interest. Possibly, the region out of the image: %s" % str(self.get_feature_dict()), img )

        return out, self._mask