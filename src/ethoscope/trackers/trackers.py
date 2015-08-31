__author__ = 'quentin'

from collections import deque

from ethoscope.utils.description  import DescribedObject
from ethoscope.core.variables import *


class NoPositionError(Exception):
    pass

class BaseTracker(DescribedObject):
    # data_point = None
    def __init__(self, roi,data=None):
        self._positions = deque()
        self._times =deque()
        self._data = data
        self._roi = roi
        self._last_non_inferred_time = 0
        self._max_history_length = 250 * 1000  # in milliseconds
        # self._max_history_length = 500   # in milliseconds
        # if self.data_point is None:
        #     raise NotImplementedError("Trackers must have a DataPoint object.")

    def __call__(self, t, img):
        sub_img, mask = self._roi(img)
        try:

            point = self._find_position(sub_img,mask,t)

            if point is None:
                return None

            # point = self.normalise_position(point)
            self._last_non_inferred_time = t

            point.append(IsInferredVariable(False))

        except NoPositionError:
            if len(self._positions) == 0:
                return None
            else:

                point = self._infer_position(t)

                if point is None:
                    return None

                point.append(IsInferredVariable(True))

        self._positions.append(point)
        self._times.append(t)


        if len(self._times) > 2 and (self._times[-1] - self._times[0]) > self._max_history_length:
            self._positions.popleft()
            self._times.popleft()


        return point

    def _infer_position(self, t, max_time=30 * 1000):
        if len(self._times) == 0:
            return None
        if t - self._last_non_inferred_time  > max_time:
            return None

        return self._positions[-1]


    @property
    def positions(self):
        return self._positions

    def xy_pos(self, i):
        return self._positions[i][0]

    @property
    def times(self):
        return self._times

    def _find_position(self,img, mask,t):
        raise NotImplementedError


