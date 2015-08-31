import numpy as np
from ethoscope.interactors.interactors import BaseInteractorSync, HasInteractedVariable
from ethoscope.hardware.output.sleep_depriver import  SleepDepriverInterface
import time
import sys

__author__ = 'quentin'


class IsMovingInteractor(BaseInteractorSync):

    def __init__(self, speed_threshold=0.0025):
        self._speed_threshold = speed_threshold
        self._last_active = 0

    def _interact(self, **kwargs):
        pass

    def _has_moved(self):
        positions = self._tracker.positions


        if len(positions ) <2 :
            return HasInteractedVariable(False),{}

        tail_m = positions[-1]
        dist = 10.0 ** (tail_m["xy_dist_log10x1000"]/1000.0)

        has_moved = (dist > self._speed_threshold)
        return has_moved

    def _run(self):
        has_moved = self._has_moved()
        t = self._tracker.times
        if  has_moved:# or xor_diff > self._xor_speed_threshold :
            self._last_active = t[-1]
            return HasInteractedVariable(False), {}
        return HasInteractedVariable(True), {}




class SleepDepInteractor(IsMovingInteractor):
    description = {"overview": "An interactor to sleep deprive an animal using servo motor. See http://todo/fixme.html",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0025},
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "min_inactive_time", "description": "The minimal time after which an inactive animal is awaken","default":120},
                                    {"type": "datetime", "name": "start_datetime", "description": "When sleep deprivation is to be started","default":0},
                                    {"type": "datetime", "name": "end_datetime", "description": "When sleep deprivation is to be ended","default":sys.maxsize}
                                   ]}

    def __init__(self,
                 velocity_threshold=0.0025,
                 min_inactive_time=120, #s
                 start_datetime=0,
                 end_datetime=sys.maxsize,
                  ):
        self._inactivity_time_threshold = min_inactive_time

        self._start_datetime= start_datetime
        self._end_datetime= end_datetime

        self._channel = self._tracker._roi.idx
        #self._sleep_dep_interface = SleepDepriverInterface(velocity_threshold)
        self._t0 = None

        super(SleepDepInteractor, self).__init__(velocity_threshold)

    def _interact(self, **kwargs):
        #self._sleep_dep_interface.deprive(**kwargs)
        pass

    def _check_time_range(self):
        wall_clock_time = time.time()
        if self._end_datetime > wall_clock_time > self._start_datetime:
            return True
        return False


    def _run(self):
        if self._check_time_range() is False:
            return False, {"channel":self._channel}

        has_moved = self._has_moved()
        times = self._tracker.times
        if has_moved:
            now = times[-1]
            if self._t0 is None:
                self._t0 = now
            else:
                if(now - self._t0) > self._inactivity_time_threshold:
                    self._t0 = None
                    return True, {"channel":self._channel}
        else:
            self._t0 = None

        return False, {"channel":self._channel}




