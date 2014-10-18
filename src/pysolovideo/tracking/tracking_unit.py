__author__ = 'quentin'



import interactors
import numpy as np

class TrackingUnit(object):
    def __init__(self, tracking_algo_class, roi, interactor=None):
        self._tracker = tracking_algo_class(roi)
        self._roi = roi

        if interactor is not None:
            self._interactor= interactor
        else:
            self._interactor = interactors.DefaultInteractor()

        self._interactor.bind_tracker(self._tracker)

    @property
    def interactor(self):
        return self._interactor

    @property
    def roi(self):
        return self._roi
    def get_last_position(self,absolute=False):
        last_position = self._tracker.positions[-1]

        if np.isnan(last_position[0]):
            return last_position
        if not absolute:
            return last_position

        out = np.copy(last_position)

        out[0:2] = out[0:2] * self._roi.longest_axis

        out[0] = out[0] + self._roi.offset
        return out



    def __call__(self, t, img):
        self._tracker(t,img)









