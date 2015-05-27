__author__ = 'quentin'



import interactors
from pysolovideo.tracking.trackers import DataPoint, RelativeVariableBase

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

        if len(self._tracker.positions) < 1:
            return None
        last_position = self._tracker.positions[-1]


        if not absolute:
            return last_position

        out =[]
        for k,i in last_position.items():
            if isinstance(i, RelativeVariableBase):
                out.append(i.to_absolute(self.roi))
            else:
                out.append(i)

        out = DataPoint(out)
        return out



    def __call__(self, t, img):

        data_row = self._tracker(t,img)

        if data_row is None:
            return

        interact, result = self._interactor()

        # TODO data_row should have some result
        data_row.append(interact)

        return data_row
