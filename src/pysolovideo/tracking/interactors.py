__author__ = 'quentin'


class BaseInteractor(object):
    _tracker = None

    def __call__(self):
        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")
        self._run()

    def _run(self):
        raise NotImplementedError

    def bind_tracker(self, tracker):
        self._tracker = tracker


class DefaultInteractor(BaseInteractor):

    def _run(self):
        # does NOTHING
        pass

