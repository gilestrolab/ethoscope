__author__ = 'quentin'


from ethoscope.interactors.interactors import BaseInteractor, HasInteractedVariable
from ethoscope.utils.scheduler import Scheduler
from ethoscope.hardware.interfaces.interfaces import  DefaultInterface
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface
import sys


class IsMovingInteractor(BaseInteractor):
    _hardwareInterfaceClass = DefaultInterface

    def __init__(self, hardware_interface=None, velocity_threshold=0.0060):
        """
        class implementing an interactor that decides whether an animal has moved though does nothing   accordingly.
        :param hardware_interface: a default hardware interface object
        :param velocity_threshold: Up to which velocity an animal is considered to be immobile
        :type velocity_threshold: float
        """
        self._velocity_threshold = velocity_threshold
        self._last_active = 0
        super(IsMovingInteractor,self).__init__(hardware_interface)

    def _has_moved(self):

        positions = self._tracker.positions

        if len(positions ) <2 :
            return False


        if len(positions[-1]) != 1:
            raise Exception("This interactor can only work with a single animal per ROI")
        tail_m = positions[-1][0]

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

    def _decide(self):
        has_moved = self._has_moved()
        t = self._tracker.times
        if  has_moved:# or xor_diff > self._xor_speed_threshold :
            self._last_active = t[-1]
            return HasInteractedVariable(False), {}
        return HasInteractedVariable(True), {}

class SleepDepInteractor(IsMovingInteractor):
    _description = {"overview": "An interactor to sleep deprive an animal using servo motor. See http://todo/fixme.html",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0060},
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "min_inactive_time", "description": "The minimal time after which an inactive animal is awaken","default":120},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}

    _hardwareInterfaceClass = SleepDepriverInterface
    _roi_to_channel = {
            1:1,  3:2,  5:3,  7:4,  9:5,
            12:6, 14:7, 16:8, 18:9, 20:10
        }
    def __init__(self,
                 hardware_interface,
                 velocity_threshold=0.0060,
                 min_inactive_time=120, #s
                 date_range=""
                  ):
        """
        A interactor to control a sleep depriver module

        :param hardware_interface: the sleep depriver module hardware interface
        :type hardware_interface: :class:`~ethoscope.hardawre.interfaces.sleep_depriver_interface.SleepDepriverInterface`
        :param velocity_threshold:
        :type velocity_threshold: float
        :param min_inactive_time: the minimal time without motion after which an animal should be disturbed (in seconds)
        :type min_inactive_time: float
        :return:
        """

        self._inactivity_time_threshold_ms = min_inactive_time *1000 #so we use ms internally

        self._t0 = None
        self._scheduler = Scheduler(date_range)
        super(SleepDepInteractor, self).__init__(hardware_interface,velocity_threshold)



    def _decide(self):

        roi_id= self._tracker._roi.idx
        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {"channel":0}

        if self._scheduler.check_time_range() is False:
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

class BaseStaticSleepDepInteractor(BaseInteractor):
    _hardwareInterfaceClass = SleepDepriverInterface
    _roi_to_channel = {
            1:1,  3:2,  5:3,  7:4,  9:5,
            12:6, 14:7, 16:8, 18:9, 20:10
        }
    def __init__(self,
                 hardware_interface,
                 date_range=""
                  ):
        """
        A interactor to control a sleep depriver module to perform static and systematic sleep deprivation by moving tubes every ``dt`` seconds.

        :param hardware_interface: the sleep depriver module hardware interface
        :type hardware_interface: :class:`~ethoscope.hardawre.interfaces.sleep_depriver_interface.SleepDepriverInterface`
        :param start_datetime: The unix time stamp of the start of the experiment
        :type start_datetime: int
        :param end_datetime: The unix time stamp of the end of the experiment
        :type end_datetime: int
        :return:
        """


        self._scheduler = Scheduler(date_range)
        #super(RandomSleepDepInteractor, self).__init__(hardware_interface,velocity_threshold)
        super(BaseStaticSleepDepInteractor,self).__init__(hardware_interface)

class SystematicSleepDepInteractor(BaseStaticSleepDepInteractor):
    _hardwareInterfaceClass = SleepDepriverInterface
    _description = {"overview": "An interactor to sleep deprive an animal using servo motor. See http://todo/fixme.html",
                    "arguments": [
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "dt", "description": "The time between two consecutive stimulation (in s)","default":120},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}

    def __init__(self,
                 hardware_interface,
                 dt=120,
                 date_range=""
                  ):
        """
        A interactor to control a sleep depriver module to perform static and systematic sleep deprivation by moving tubes every ``dt`` seconds.

        :param dt:
        :type dt: float

        :return:
        """
        self._t0 = 0
        self._dt = dt *1000 #so we use ms internally
        super(SystematicSleepDepInteractor,self).__init__(hardware_interface, date_range="")

    def _decide(self):
        roi_id= self._tracker._roi.idx
        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {"channel":0}

        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False), {"channel":channel}

        if float(now - self._t0) > self._dt:
                self._t0 = now # reset timer and deprive
                return HasInteractedVariable(True), {"channel":channel}

        return HasInteractedVariable(False), {"channel":channel}

class ExperimentalSleepDepInteractor(IsMovingInteractor):
    _description = {"overview": "An interactor to sleep deprive an animal using servo motor. See http://todo/fixme.html",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0060},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}

    _hardwareInterfaceClass = SleepDepriverInterface
    _roi_to_channel = {
            1:1,  3:2,  5:3,  7:4,  9:5,
            12:6, 14:7, 16:8, 18:9, 20:10
        }

    def __init__(self,
                 hardware_interface,
                 velocity_threshold=0.0060,
                 date_range=""
                  ):
        """
        A interactor to control a sleep depriver module

        :param hardware_interface: the sleep depriver module hardware interface
        :type hardware_interface: :class:`~ethoscope.hardawre.interfaces.sleep_depriver_interface.SleepDepriverInterface`
        :param velocity_threshold:
        :type velocity_threshold: float
        :param start_datetime: The unix time stamp of the start of the experiment
        :type start_datetime: int
        :param end_datetime: The unix time stamp of the end of the experiment
        :type end_datetime: int
        :return:
        """

        self._t0 = None
        self._scheduler = Scheduler(date_range)
        super(ExperimentalSleepDepInteractor, self).__init__(hardware_interface,velocity_threshold)




    def _decide(self):

        roi_id= self._tracker._roi.idx


        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {"channel":0}

        # this is where the magic happens. According to the channel, we wait different times.
        inactivity_time_threshold_ms = round( channel ** 1.7) * 20 * 1000


        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False), {"channel":channel}

        has_moved = self._has_moved()

        if self._t0 is None:
            self._t0 = now

        if not has_moved:
            if float(now - self._t0) > inactivity_time_threshold_ms:
                self._t0 = None

                return HasInteractedVariable(True), {"channel":channel}

        else:
            self._t0 = now

        return HasInteractedVariable(False), {"channel":channel}

