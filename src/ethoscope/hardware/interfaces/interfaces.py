__author__ = 'quentin'


class BaseInterface(object):
    def __init__(self):
        self._warm_up()
    def _warm_up(self):
        raise NotImplementedError
    def interact(self):
        raise NotImplementedError


class DefaultInterface(object):
    def _warm_up(self):
        pass
    def interact(self):
        pass
