__author__ = 'quentin'



import interactors

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

        out = last_position


        out["x"] *= self._roi.longest_axis
        out["y"] *= self._roi.longest_axis
        out["h"] *= self._roi.longest_axis
        out["w"] *= self._roi.longest_axis
        ox, oy = self._roi.offset

        out["x"] += ox
        out["y"] += oy

        return out



    def __call__(self, t, img):
        data_row = self._tracker(t,img)
        if data_row is not None:
            data_row["roi_value"] = self._roi.value
            if data_row is None:
                return

                #fixme this should be handled by tracking units themeselves
            # if self._interactor is not None:
            #     interactor_columns = self._interactor()
            #     interactor_columns.index=data_row.index
            #         #
            #     data_row = pd.concat([data_row, interactor_columns], axis=1)

            return data_row

        # TODO interactor here
        return data_row










