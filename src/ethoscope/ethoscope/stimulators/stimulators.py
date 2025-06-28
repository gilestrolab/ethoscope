__author__ = 'quentin'

from ethoscope.utils.description import DescribedObject
from ethoscope.core.variables import BaseIntVariable
from ethoscope.hardware.interfaces.interfaces import DefaultInterface
from ethoscope.utils.scheduler import Scheduler



class HasInteractedVariable(BaseIntVariable):
    """
    Custom variable to save whether the stimulator has sent instruction to its hardware interface. 0 means
     no interaction. Any positive integer describes a different interaction.
    """
    functional_type = "interaction"
    header_name = "has_interacted"



class   BaseStimulator(DescribedObject):
    _tracker = None
    _HardwareInterfaceClass = None

    def __init__(self, hardware_connection, date_range=""):
        """
        Template class to interact with the tracked animal in a real-time feedback loop.
        Derived classes must have an attribute ``_hardwareInterfaceClass`` defining the class of the
        :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface` object (not on object) that instances will
        share with one another. In addition, they must implement a ``_decide()`` method.

        :param hardware_connection: The hardware interface to use.
        :type hardware_connection: :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface`
        :param date_range: the start and stop date/time for the stimulator. Format described `here <https://github.com/gilestrolab/ethoscope/blob/master/user_manual/schedulers.md>`_
        :type date_range: str
        
        """

        self._scheduler = Scheduler(date_range)
        self._hardware_connection = hardware_connection

    def apply(self):
        """
        Apply this stimulator. This method will:

        1. check ``_tracker`` exists
        2. decide (``_decide``) whether to interact
        3. if 2. pass the interaction arguments to the hardware interface
        
        :return: whether a stimulator has worked, and a result dictionary
        """
        if self._tracker is None:
            raise ValueError("No tracker bound to this stimulator. Use `bind_tracker()` methods")

        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False) , {}
        interact, result  = self._decide()
        if interact > 0:
            self._deliver(**result)

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

    def _deliver(self, **kwargs):
        if self._hardware_connection is not None:
            self._hardware_connection.send_instruction(kwargs)


class DefaultStimulator(BaseStimulator):
    """
    Default interactor. Simply never interacts
    """
    _description = {"overview": "The default 'interactor'. To use when no hardware interface is to be used.",
                    "arguments": []}
    _HardwareInterfaceClass = DefaultInterface

    def _decide(self):
        out = HasInteractedVariable(False)
        return out, {}


