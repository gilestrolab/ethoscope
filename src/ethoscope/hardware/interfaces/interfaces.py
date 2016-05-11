__author__ = 'quentin'

from threading import Thread
import time
import collections

class HardwareConnection(Thread):
    def __init__(self, interface_class, *args, **kwargs):
        self._interface = interface_class(*args, **kwargs)
        self._instructions = collections.deque()
        self._connection_open = True
        super(HardwareConnection, self).__init__()
        self.start()
    def run(self):
        while self._connection_open:
            time.sleep(.1)
            while len(self._instructions) > 0:
                instruc = self._instructions.popleft()
                ret = self._interface.send(instruc)

    def send_instruction(self, instruction=None):
        if instruction is None:
            instruction = {}
        if not isinstance(instruction, dict):
            raise Exception("instructions should be dictionaries")
        self._instructions.append(instruction)

    def stop(self, error=None):
        self._connection_open = False
    def __del__(self):
        self.stop()

class BaseInterface(object):
    def __init__(self):
        self._warm_up()

    def _warm_up(self):
        raise NotImplementedError
    def send(self, **kwargs):
        """
        Method to request hardware interface to interact with the physical world.
        :param kwargs: keywords arguments
        """
        raise NotImplementedError

class DefaultInterface(BaseInterface):
    def _warm_up(self):
        pass
    def send(self, **kwargs):
        pass

# class BaseInterface(object):
#
#     def __init__(self):
#         """
#         A template class to interface hardware. It must implement two methods: ``_warm_up()`` and ``interact()``
#         Typically, several :class:`~ethoscope.interactors.interactors.BaseInteractor` will share a single hardware interface.
#         When possible, hardware interfaces are also responsible for checking, at initialisation, that hardware is reachable.
#         :return:
#         """
#         self._warm_up()
#     def _warm_up(self):
#         raise NotImplementedError
#
#     def interact(self, **kwargs):
#         """
#         Method to request hardware interface to interact with the physical world.
#         Typically called by an :class:`~ethoscope.interactors.interactors.BaseInteractor`.
#
#         :param kwargs: keywords arguments
#         """
#         raise NotImplementedError
#
#
# class DefaultInterface(object):
#     """
#     A default dummy interface that does nothing.
#     """
#     def _warm_up(self):
#         pass
#     def interact(self):
#         pass
