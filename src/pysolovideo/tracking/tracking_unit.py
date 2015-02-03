__author__ = 'quentin'



import interactors
from pysolovideo.tracking.trackers import DataPointBase, RelativeVariableBase
import copy

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

        last_position = copy.deepcopy(self._tracker.positions[-1])


        if not absolute:
            return last_position


        out =[]
        for k,i in last_position.data.items():
            out.append(i)
            if isinstance(i, RelativeVariableBase):
                out[-1].to_absolute(self.roi)
        out = DataPointBase(out)

        return out



    def __call__(self, t, img):
        data_row = self._tracker(t,img)

        if data_row is None:
            return
        # data_row["roi_value"] = self._roi.value
        # data_row["roi_idx"] = self._roi.idx
        # data_row["t"] = t
        # print len(data_row.data)
        interact, result = self._interactor()

        data_row.append(interact)
        # print len(data_row.data)
        return data_row
