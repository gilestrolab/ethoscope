import cv2
import numpy as np

from ethoscope.utils.debug import EthoscopeException

try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

__author__ = "quentin"


class ROI:

    def __init__(
        self, polygon, idx, value=None, orientation=None, regions=None, hierarchy=None
    ):
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
        :param regions: Optional sub-regions within the ROI.
        :param hierarchy: The hierarchy of subregions in the ROI
        """

        # TODO if we do not need polygon, we can drop it
        self._polygon = np.array(polygon)
        if len(self._polygon.shape) == 2:
            self._polygon = self._polygon.reshape(
                (self._polygon.shape[0], 1, self._polygon.shape[1])
            )

        x, y, w, h = cv2.boundingRect(self._polygon)

        self._mask = np.zeros((h, w), np.uint8)
        cv2.drawContours(self._mask, [self._polygon], 0, 255, -1, offset=(-x, -y))

        self._rectangle = x, y, w, h
        # todo NOW! sort rois by value. if no values, left to right/ top to bottom!
        self._idx = idx

        if value is None:
            self._value = self._idx
        else:
            self._value = value

        if regions is None:
            self._regions = self._polygon
        else:
            if CV_VERSION == 3:
                _, self._regions, self._hierarchy = cv2.findContours(
                    np.copy(self._polygon), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
                )
            else:
                self._regions, self._hierarchy = cv2.findContours(
                    np.copy(self._polygon), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
                )

    @property
    def idx(self):
        """
        :return: The index of this ROI
        :rtype: int
        """
        return self._idx

    def bounding_rect(self):
        raise NotImplementedError

    @property
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
        x, y, w, h = self._rectangle
        return x, y

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
        x, y, w, h = self._rectangle
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
        x, y, w, h = self._rectangle
        return {"x": x, "y": y, "w": w, "h": h, "value": self._value, "idx": self.idx}

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

    def apply(self, img):
        """
        Cut an image where the ROI is defined.

        :param img: An image. Typically either one or three channels `uint8`.
        :type img: :class:`~numpy.ndarray`
        :return: a tuple containing the resulting cropped image and the associated mask (both have the same dimension).
        :rtype: (:class:`~numpy.ndarray`, :class:`~numpy.ndarray`)
        """
        x, y, w, h = self._rectangle

        img_h, img_w = img.shape[0:2]

        # Clamp x, y, w, h to image boundaries
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(img_w, x + w)
        y2 = min(img_h, y + h)

        # Adjust w and h based on clamping
        w_clamped = x2 - x1
        h_clamped = y2 - y1

        if w_clamped <= 0 or h_clamped <= 0:
            raise EthoscopeException(
                "Error whilst slicing region of interest. Clamped region has zero or negative width/height: %s"
                % str(self.get_feature_dict()),
                img,
            )

        try:
            out = img[y1:y2, x1:x2]
        except Exception as e:
            raise EthoscopeException(
                "Error whilst slicing region of interest %s: %s"
                % (str(self.get_feature_dict()), str(e)),
                img,
            )

        # Ensure output dimensions match expected clamped dimensions
        if out.shape[0:2] != (h_clamped, w_clamped):
            raise EthoscopeException(
                "Error whilst slicing region of interest. Output shape mismatch after clamping: %s"
                % str(self.get_feature_dict()),
                img,
            )

        # Adjust mask to match the clamped output dimensions
        # Calculate the offset into the original mask based on clamping
        mask_x_offset = max(0, x - x1)  # How much was clipped from left
        mask_y_offset = max(0, y - y1)  # How much was clipped from top

        # Crop the mask to match the clamped output dimensions
        mask_x_end = mask_x_offset + w_clamped
        mask_y_end = mask_y_offset + h_clamped

        # Ensure we don't exceed mask boundaries
        mask_x_end = min(mask_x_end, self._mask.shape[1])
        mask_y_end = min(mask_y_end, self._mask.shape[0])

        adjusted_mask = self._mask[mask_y_offset:mask_y_end, mask_x_offset:mask_x_end]

        # Final safety check: ensure mask and output have identical dimensions
        if adjusted_mask.shape != out.shape[0:2]:
            # Fallback: create a full mask if adjustment failed
            adjusted_mask = np.ones(out.shape[0:2], dtype=np.uint8) * 255

        return out, adjusted_mask

    @property
    def regions(self):
        """
        :return: the regions of a ROI
        """
        return self._regions

    def hierachy(self):
        """
        :return: the hierarchy of regions in a ROI
        """
        return self._hierarchy
