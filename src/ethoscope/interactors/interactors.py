__author__ = 'quentin'

from ethoscope.utils.description import DescribedObject
from ethoscope.core.variables import BaseBoolVariable
from ethoscope.hardware.interfaces.interfaces import DefaultInterface



class HasInteractedVariable(BaseBoolVariable):
    """
    Custom variable to save whether the interactor has sent instruction to its hardware interface.
    """
    header_name = "has_interacted"


class BaseInteractor(DescribedObject):
    _tracker = None
    _hardwareInterfaceClass = None

    def __init__(self, hardware_interface):
        """
        Template class to interact with the tracked animal in a real-time feedback loop.
        Derived classes must have an attribute ``_hardwareInterfaceClass`` defining the class of the
        :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface` object (not on object) that instances will
        share with one another.

        In addition, they must implement a ``_decide()`` method.


        :param hardware_interface: The hardware interface to use.
        :type hardware_interface: :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface`
        """

        self._hardware_interface = hardware_interface

    def apply(self):
        """
        Apply this interactor. This method will:

        1. check ``_tracker`` exists
        2. decide (``_decide``) whether to interact
        3. if 2. pass the interaction arguments to the hardware interface
        :return:
        """

        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")

        interact, result  = self._decide()
        if interact == HasInteractedVariable(True):
            self._interact(**result)

        return interact, result


    def bind_tracker(self, tracker):
        """
        Link a tracker to this interactor

        :param tracker: a tracker object.
        :type tracker: :class:`~ethoscope.trackers.trackers.BaseTracker`
        """
        self._tracker = tracker

    def _decide(self):
        raise NotImplementedError

    def _interact(self, **kwargs):
        self._hardware_interface.interact(**kwargs)


class DefaultInteractor(BaseInteractor):
    """
    Default interactor. Simply never interacts
    """
    _description = {"overview": "The default 'interactor'. To use when no hardware interface is to be used.",
                    "arguments": []}
    _hardwareInterfaceClass = DefaultInterface

    def _decide(self):
        out = HasInteractedVariable(False)
        return out, {}


