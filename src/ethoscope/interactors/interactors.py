__author__ = 'quentin'

import multiprocessing
from ethoscope.utils.description import DescribedObject
from ethoscope.core.variables import BoolVariableBase
from ethoscope.hardware.interfaces.interfaces import DefaultInterface



class HasInteractedVariable(BoolVariableBase):
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
        if interact:
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


#
# ###Prototyping below ###########################
# class BaseInteractorAsync(BaseInteractor):
#     _tracker = None
#     # this is not v elegant
#     _subprocess = multiprocessing.Process()
#     _target = None
#
#     def __call__(self):
#         if self._tracker is None:
#             raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")
#         interact, result  = self._run()
#
#         if interact:
#             self._interact_async(result)
#         result["interact"] = interact
#         return interact#, result
#
#
#     def _interact_async(self, kwargs):
#         # If the target is being run, we wait
#         if self._subprocess.is_alive():
#             return
#         if self._target is None:
#             return
#         self._subprocess = multiprocessing.Process(target=self._target, kwargs = kwargs)
#         self._subprocess.start()
#
#


