__author__ = 'quentin'


from ethoscope.interactors.interactors import BaseInteractor, HasInteractedVariable
from ethoscope.hardware.interfaces.interfaces import  DefaultInterface
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface
import time
import sys


class IsMovingInteractor(BaseInteractor):
    _hardwareInterfaceClass = DefaultInterface

    def __init__(self, hardware_interface, velocity_threshold=0.0060):
        self._velocity_threshold = velocity_threshold
        self._last_active = 0
        super(IsMovingInteractor,self).__init__(hardware_interface)

    def _interact(self, **kwargs):
        pass

    def _has_moved(self):

        positions = self._tracker.positions

        if len(positions ) <2 :
            return False
        tail_m = positions[-1]

        times = self._tracker.times
        last_time_for_position = times[-1]
        last_time = self._tracker.last_time_point

        # we assume no movement if the animal was not spotted
        if last_time != last_time_for_position:
            return False



        dt_s = abs(times[-1] - times[-2]) / 1000.0
        dist = 10.0 ** (tail_m["xy_dist_log10x1000"]/1000.0)
        velocity = dist / dt_s

        if velocity > self._velocity_threshold:
            return True
        return False

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
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0060},
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "min_inactive_time", "description": "The minimal time after which an inactive animal is awaken","default":120},
                                    {"type": "datetime", "name": "start_datetime", "description": "When sleep deprivation is to be started","default":0},
                                    {"type": "datetime", "name": "end_datetime", "description": "When sleep deprivation is to be ended","default":sys.maxsize}
                                   ]}

    _hardwareInterfaceClass = SleepDepriverInterface
    _roi_to_channel = {
            2:1,  4:2,  6:3,  8:4,  10:5,
            11:6, 13:7, 15:8, 17:9, 19:10
        }


    def __init__(self,
                 hardware_interface,
                 velocity_threshold=0.0060,
                 min_inactive_time=120, #s
                 start_datetime=0,
                 end_datetime=sys.maxsize,
                  ):
        self._inactivity_time_threshold_ms = min_inactive_time *1000 #so we use ms internally
        self._start_datetime= start_datetime
        self._end_datetime= end_datetime
        self._t0 = None

        super(SleepDepInteractor, self).__init__(hardware_interface,velocity_threshold)


    def _check_time_range(self):
        wall_clock_time = time.time()
        if self._end_datetime > wall_clock_time > self._start_datetime:
            return True
        return False


    def _run(self):

        roi_id= self._tracker._roi.idx
        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {"channel":0}

        if self._check_time_range() is False:
            return HasInteractedVariable(False), {"channel":channel}

        has_moved = self._has_moved()



        if self._t0 is None:
            self._t0 = now

        if not has_moved:
            if float(now - self._t0) > self._inactivity_time_threshold_ms:
                self._t0 = None

                return HasInteractedVariable(True), {"channel":channel}

        else:
            self._t0 = now

        return HasInteractedVariable(False), {"channel":channel}



