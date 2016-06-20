__author__ = 'quentin'

from threading import Thread
import time
import collections

class   HardwareConnection(Thread):
    def __init__(self, interface_class, *args, **kwargs):
        self._interface_class = interface_class
        self._interface_args = args
        self._interface_kwargs = kwargs

        self._interface = interface_class(*args, **kwargs)
        self._instructions = collections.deque()
        self._connection_open = True
        super(HardwareConnection, self).__init__()
        self.start()
    def run(self):
        while self._connection_open:
            time.sleep(.1)
            while len(self._instructions) > 0 and self._connection_open:
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

    def __getstate__(self):
        return {
                "interface_class": self._interface_class,
                "interface_args": self._interface_args,
                "interface_kwargs": self._interface_kwargs}

    def __setstate__(self, state):
        kwargs = state["interface_kwargs"]
        kwargs["do_warm_up"] = False
        self.__init__(state["interface_class"],
                      *state["interface_args"], **kwargs)


class BaseInterface(object):
    def __init__(self, do_warm_up = True):
        if do_warm_up:
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
