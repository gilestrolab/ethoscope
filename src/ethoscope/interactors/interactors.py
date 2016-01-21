__author__ = 'quentin'

from ethoscope.utils.description import DescribedObject
from ethoscope.core.variables import BaseIntVariable
from ethoscope.hardware.interfaces.interfaces import DefaultInterface
import time


class HasInteractedVariable(BaseIntVariable):
    """
    Custom variable to save whether the interactor has sent instruction to its hardware interface.
    0 means no interaction. Any positive integer describes a different interaction.
    """
    functional_type = "interaction"
    header_name = "has_interacted"

class SimpleScheduler(object):
    def __init__(self, start_time, end_time):
        """
        Class to schedule interators. `SimpleScheduler` objects are meant to be instantiated as member variables in
        Interactors. They also check for inconsistencies in the time schedule.

        :param start_time: When is the first valid time (in unix timestamp)
        :type start_time: int
        :param end_time: When is the last valid time (in unix timestamp)
        :type end_time: int

        """


        end_time = int(end_time)
        start_time = int(start_time )


        wall_clock_time = time.time()
        self._start_datetime = start_time
        self._end_datetime = end_time

        if(wall_clock_time > end_time):
            raise Exception("You cannot end experiment in the past. Current time is %i, end time is %i" % (wall_clock_time, end_time))

        if(start_time > end_time):
            raise Exception("This experiment is scheduled to stop BEFORE it starts, Start time is %i, end time is %i" % (start_time, end_time))

    def check_time_range(self):

        wall_clock_time = time.time()
        if self._end_datetime > wall_clock_time > self._start_datetime:
            return True
        return False


class   BaseInteractor(DescribedObject):
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


