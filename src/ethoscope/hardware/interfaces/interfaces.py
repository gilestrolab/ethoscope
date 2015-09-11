__author__ = 'quentin'


class BaseInterface(object):

    def __init__(self):
        """
        A template class to interface hardware. It must implement two methods: ``_warm_up()`` and ``interact()``
        Typically, several :class:`~ethoscope.interactors.interactors.BaseInteractor` will share a single hardware interface.
        When possible, hardware interfaces are also responsible for checking, at initialisation, that hardware is reachable.
        :return:
        """
        self._warm_up()
    def _warm_up(self):
        raise NotImplementedError

    def interact(self, **kwargs):
        """
        Method to request hardware interface to interact with the physical world.
        Typically called by an :class:`~ethoscope.interactors.interactors.BaseInteractor`.

        :param kwargs: keywords arguments
        """
        raise NotImplementedError


class DefaultInterface(object):
    """
    A default dummy interface that does nothing.
    """
    def _warm_up(self):
        pass
    def interact(self):
        pass
