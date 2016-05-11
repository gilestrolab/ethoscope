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
        while len(self._instructions) > 0 and self._connection_open:
            time.sleep(.1)
            instruc = self._instructions.popleft()
            ret = self._interface.send(**instruc)

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
