__author__ = 'quentin'



import interactors


class TrackingUnit(object):
    def __init__(self, tracking_algo_class, roi, interactor=None):
        self._tracker = tracking_algo_class()
        self._roi = roi

        if interactor is not None:
            self._interactor= interactor
        else:
            self._interactor = interactors.DefaultInteractor()

        self._interactor.bind_tracker(self._tracker)

    def __call__(self, t, img):
        img, mask = self._roi(img)
        position = self._tracker(t,img, mask)
        self._interactor()
        return position







