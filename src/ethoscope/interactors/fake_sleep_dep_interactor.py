__author__ = 'quentin'

from sleep_depriver_interactor import SleepDepInteractor, SystematicSleepDepInteractor
from ethoscope.hardware.interfaces.fake_sleep_dep_interface import FakeSleepDepriverInterface
from ethoscope.interactors.interactors import  HasInteractedVariable
import time
import sys

class FakeSleepDepInteractor(SleepDepInteractor):
    """
    A fake sleep depriver interface. It mimics the behaviour of
    :class:`~ethoscope.interactors.sleep_depriver_interactor.SleepDepInteractor`,
    but simply prints a message instead of moving a servo.
    """
    _description = {"overview": "A dummy interactor that simply print messages instead of moving tubes. For development only",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0060},
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "min_inactive_time", "description": "The minimal time after which an inactive animal is awaken","default":120},
                                    {"type": "datetime", "name": "start_datetime", "description": "When sleep deprivation is to be started","default":0},
                                    {"type": "datetime", "name": "end_datetime", "description": "When sleep deprivation is to be ended","default":sys.maxsize}
                                   ]}
    _hardwareInterfaceClass = FakeSleepDepriverInterface





class FakeSystematicSleepDepInteractor(SystematicSleepDepInteractor):
    """
    A fake sleep depriver interface. It mimics the behaviour of
    :class:`~ethoscope.interactors.sleep_depriver_interactor.SystematicSleepDepInteractor`,
    but simply prints a message instead of moving a servo.
    """

    _description = {"overview": "A dummy interactor that simply print messages instead of moving tubes. For development only. Mimics Systematic sleep deprivation ",
                    "arguments": [
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "dt", "description": "The time between two consecutive stimulation (in s)","default":120},
                                    {"type": "datetime", "name": "start_datetime", "description": "When sleep deprivation is to be started","default":0},
                                    {"type": "datetime", "name": "end_datetime", "description": "When sleep deprivation is to be ended","default":sys.maxsize}
                                   ]}

    def _check_time_range(self):
        wall_clock_time = int(time.time())
        if self._tracker._roi.idx ==1:
            print "-----------------------------------------"
            print wall_clock_time, self._start_datetime, self._end_datetime
            print wall_clock_time < self._end_datetime
            print self._end_datetime - wall_clock_time
            print wall_clock_time > self._start_datetime
            print wall_clock_time - self._start_datetime


        if  wall_clock_time < self._end_datetime:

            if self._tracker._roi.idx ==1:
                print " smaller than end time"
            if wall_clock_time > self._start_datetime:
                if self._tracker._roi.idx ==1:
                    print " larger than start time"

                if self._tracker._roi.idx ==1:
                    print "in range", wall_clock_time, self._start_datetime, self._end_datetime

                return True

        if self._tracker._roi.idx == 1:
            print "failed check", wall_clock_time, self._start_datetime, self._end_datetime
        return False


    def _decide(self):
        roi_id= self._tracker._roi.idx
        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            if roi_id==1:
                print "KE"
            return HasInteractedVariable(False), {"channel":0}

        if self._check_time_range() is False:
            if roi_id==1:
                print "out of time",time.time(), self._start_datetime, self._end_datetime

            return HasInteractedVariable(False), {"channel":channel}

        if float(now - self._t0) > self._dt:
                self._t0 = now # reset timer and deprive
                if roi_id==1:
                    print "INTERACTING"
                return HasInteractedVariable(True), {"channel":channel}

        return HasInteractedVariable(False), {"channel":channel}

    _hardwareInterfaceClass = FakeSleepDepriverInterface

