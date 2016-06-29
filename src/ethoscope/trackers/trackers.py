__author__ = 'quentin'

from collections import deque

from ethoscope.utils.description  import DescribedObject
from ethoscope.core.variables import *


class NoPositionError(Exception):
    """
    Used to abort tracking. When it is raised within the ``_find_position`` method, data is inferred from previous position.
    """
    pass

class BaseTracker(DescribedObject):
    # data_point = None
    def __init__(self, roi,data=None):
        """
        Template class for video trackers.
        A video tracker locate animal in a ROI.
        Derived class must implement the ``_find_position`` method.

        :param roi: The Region Of Interest the the tracker will use to locate the animal.
        :type roi: :class:`~ethoscope.rois.roi_builders.ROI`
        :param data: An optional data set. For instance, it can be used for pre-trained algorithms

        :return:
        """
        self._positions = deque()
        self._times =deque()
        self._data = data
        self._roi = roi
        self._last_non_inferred_time = 0
        self._last_time_point = 0
        self._max_history_length = 250 * 1000  # in milliseconds

        # self._max_history_length = 500   # in milliseconds
        # if self.data_point is None:
        #     raise NotImplementedError("Trackers must have a DataPoint object.")

    def track(self, t, img):
        """
        Locate the animal in a image, at a given time.

        :param t: time in ms
        :type t: int
        :param img: the whole frame.
        :type img: :class:`~numpy.ndarray`
        :return: The position of the animal at time ``t``
        :rtype: :class:`~ethoscope.core.data_point.DataPoint`
        """

        sub_img, mask = self._roi.apply(img)
        self._last_time_point = t
        try:

            points = self._find_position(sub_img,mask,t)
            if not isinstance(points, list):
                raise Exception("tracking algorithms are expected to return a LIST of DataPoints")

            if len(points) ==0:
                return []

            # point = self.normalise_position(point)
            self._last_non_inferred_time = t

            for p in points:
                p.append(IsInferredVariable(False))

        except NoPositionError:
            if len(self._positions) == 0:
                return []
            else:

                points = self._infer_position(t)

                if len(points) ==0:
                    return []
                for p in points:
                    p.append(IsInferredVariable(True))

        self._positions.append(points)
        self._times.append(t)


        if len(self._times) > 2 and (self._times[-1] - self._times[0]) > self._max_history_length:
            self._positions.popleft()
            self._times.popleft()
        return points

    def _infer_position(self, t, max_time=30 * 1000):
        if len(self._times) == 0:
            return []
        if t - self._last_non_inferred_time  > max_time:
            return []

        return self._positions[-1]


    @property
    def positions(self):
        """
        :return: The last few positions found by the tracker.\
            Positions are kept for a certain duration defined by the ``_max_history_length`` attribute.
        :rtype: :class:`~collection.deque`
        """
        return self._positions

    def xy_pos(self, i):
        return self._positions[i][0]

    @property
    def last_time_point(self):
        """
        :return: The last time point that the tracker used.\
            This is updated even when position is inferred/no animal is found
        :rtype: int
        """
        return self._last_time_point

    @property
    def times(self):
        """
        :return: The last few time points corresponding to :class:`~ethoscope.trackers.trackers.BaseTracker.positions`.
        :rtype: :class:`~collection.deque`
        """
        return self._times

    def _find_position(self,img, mask,t):
        raise NotImplementedError


