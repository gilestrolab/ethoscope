__author__ = 'quentin'

import numpy as np
import multiprocessing
from subprocess import call
from math import sqrt

from ethoscope.hardware_control.arduino_api import SleepDepriverInterface
from ethoscope.utils.description import DescribedObject

from ethoscope.tracking.trackers import BoolVariableBase

class HasInteractedVariable(BoolVariableBase):
    header_name = "has_interacted"


class BaseInteractorSync(DescribedObject):
    _tracker = None

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

    def _interact(self, kwargs):
        raise NotImplementedError

class SleepDepInteractor(BaseInteractorSync):
    def __init__(self, channel, sd_interface ):
        self._sleep_dep_interface = sd_interface
        self._t0 = None
        self._channel = channel

        self._distance_threshold = 1e-2
        self._inactivity_time_threshold = 90 # s

    def _interact(self, **kwargs):
        print "c=",self._channel
        self._sleep_dep_interface.deprive(**kwargs)

    def _run(self):
        positions = self._tracker.positions
        t = self._tracker.times

        if len(positions ) <2 :
            return False, {"channel":self._channel}
        tail_m = positions[-1]
        xy_m = complex(tail_m["x"] + 1j * tail_m["y"])

        tail_mm = positions[-2]

        xy_mm =complex(tail_mm["x"] + 1j * tail_mm["y"])

        if np.abs(xy_m - xy_mm) < self._distance_threshold:

            now = t[-1]
            if self._t0 is None:
                self._t0 = now

            else:
                if(now - self._t0) > self._inactivity_time_threshold:

                    self._t0 = None
                    return True, {"channel":self._channel}

        else:
            self._t0 = None

        return False, {"channel":self._channel}


class IsMovingInteractor(BaseInteractorSync):
    def __init__(self):

        self._last_active = 0

        self._speed_threshold = 0.0025


        # self._xor_speed_threshold = 0.175
        self._sleep_dt_threshold = 1000 * 60 * 5 * 1.
    def _interact(self, **kwargs):
        pass

    def _run(self):
        positions = self._tracker.positions
        t = self._tracker.times

        if len(positions ) <2 :
            return HasInteractedVariable(False),{}

        tail_m = positions[-1]
        dist = 10.0 ** (tail_m["xy_dist_log10x1000"]/1000.0)



        #speed = abs(xy_m - xy_mm) /  self._tracker._roi.longest_axis
        #dt = (t[-1] - t[-2]) /1000.0
        #speed /=dt
        # xor_diff = tail_m["xor_diff_x1000"] / 1000.0

        if  dist > self._speed_threshold:# or xor_diff > self._xor_speed_threshold :
            self._last_active = t[-1]
            return HasInteractedVariable(False), {}
        return HasInteractedVariable(True), {}

        # if self._tracker._roi.idx == 20:
        #
        #     p =  100 * (t[-1] - self._last_active )/ self._sleep_dt_threshold
        #     if p >0:
        #         print p
        # if(t[-1] - self._last_active) < self._sleep_dt_threshold:
        #
        #
        #     return HasInteractedVariable(False), {}
        #
        #
        # return HasInteractedVariable(True), {}




###Prototyping below ###########################
class BaseInteractor(DescribedObject):
    _tracker = None
    # this is not v elegant
    _subprocess = multiprocessing.Process()

    _target = None

    def __call__(self):

        if self._tracker is None:
            raise ValueError("No tracker bound to this interactor. Use `bind_tracker()` methods")

        interact, result  = self._run()

        if interact:
            self._interact_async(result)
        result["interact"] = interact

        return interact#, result


    def bind_tracker(self, tracker):
        self._tracker = tracker


    def _run(self):
        raise NotImplementedError

    def _interact_async(self, kwargs):

        # If the target is being run, we wait
        if self._subprocess.is_alive():
            return

        if self._target is None:
            return

        self._subprocess = multiprocessing.Process(target=self._target, kwargs = kwargs)

        self._subprocess.start()




class DefaultInteractor(BaseInteractor):
    description = {"overview": "The default sleep monitor arena with ten rows of two tubes.",
                    "arguments": []}
    def _run(self):
        out = HasInteractedVariable(False), {}
        return out, {}

