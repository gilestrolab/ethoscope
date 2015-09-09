__author__ = 'quentin'

from ethoscope.utils.description import DescribedObject
from ethoscope.core.variables import BaseBoolVariable
from ethoscope.hardware.interfaces.interfaces import DefaultInterface



class HasInteractedVariable(BaseBoolVariable):
    header_name = "has_interacted"


class BaseInteractor(DescribedObject):
    _tracker = None
    _hardwareInterfaceClass = None

    def __init__(self, hardware_interface):
        self._hardware_interface = hardware_interface

    def __call__(self):

        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")

        interact, result  = self._run()
        if interact == HasInteractedVariable(True):
            self._interact(**result)

        return interact, result


    def bind_tracker(self, tracker):
        self._tracker = tracker

    def _run(self):
        raise NotImplementedError

    def _interact(self, **kwargs):
        self._hardware_interface.interact(**kwargs)


class DefaultInteractor(BaseInteractor):
    description = {"overview": "The default sleep monitor arena with ten rows of two tubes.",
                    "arguments": []}
    _hardwareInterfaceClass = DefaultInterface
    def _run(self):
        out = HasInteractedVariable(False)
        return out, {}


