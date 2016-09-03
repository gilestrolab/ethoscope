__author__ = 'quentin'

from threading import Thread
import time
import collections

class   HardwareConnection(Thread):
    def __init__(self, interface_class, *args, **kwargs):
        """
        A class to build a connection to arbitrary hardware.
        It implements an instance of a :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface` which it uses to send instructions, asynchronously and  on demand.

        :param interface_class: the class to use a an interface to hardware (derives from :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface`)
        :type interface_class: class
        :param args: list of arguments passed the the hardware interface
        :param kwargs: list of keyword arguments passed the the hardware interface
        """
        self._interface_class = interface_class
        self._interface_args = args
        self._interface_kwargs = kwargs

        self._interface = interface_class(*args, **kwargs)
        self._instructions = collections.deque()
        self._connection_open = True
        super(HardwareConnection, self).__init__()
        self.start()
        
    def run(self):
        """
        Infinite loop that send instructions to the hardware interface
        Do not call directly, used the ``start()`` method instead.
        """
        while self._connection_open:
            time.sleep(.1)
            while len(self._instructions) > 0 and self._connection_open:
                instruc = self._instructions.popleft()
                ret = self._interface.send(**instruc)

    def send_instruction(self, instruction=None):
        """
        Stage an instruction to be sent to the hardware interface.
        Instructions will be parsed sequentially, but asynchronously from the main thread execution.
        :param instruction: a dictionary of keyword arguments ,matching those of ``interface_class.send()``.
        :type instruction: dict()
        """
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
        """
        Template class which is an abstract representation of an hardware interface.
        It must define, in :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface.__init__`,
        how the interface is connected, and in :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface.send`,
        how information are communicated to the hardware. In addition, derived classes must implement a
        :func:`~ethoscope.hardware.interfaces.interfaces.BaseInterface._warm_up`, method, which defines optionnal instructions
        passed to the hardware upon first connection (that is useful to experimenters that want to manually check their settings).

        :param do_warm_up:
        """
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
    """
    Class that implements a dummy interface that does nothing. This can be used to keep software consistency when
    no hardware is to be used.
    """
    def _warm_up(self):
        pass
    def send(self, **kwargs):
        pass
