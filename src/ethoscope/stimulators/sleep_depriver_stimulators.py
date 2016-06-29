__author__ = 'quentin'


from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable

from ethoscope.hardware.interfaces.interfaces import  DefaultInterface
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface
import sys


class IsMovingStimulator(BaseStimulator):
    _HardwareInterfaceClass = DefaultInterface

    def __init__(self, hardware_connection=None, velocity_threshold=0.0060, date_range = ""):
        """
        class implementing an stimulator that decides whether an animal has moved though does nothing   accordingly.
        :param hardware_connection: a default hardware interface object
        :param velocity_threshold: Up to which velocity an animal is considered to be immobile
        :type velocity_threshold: float
        """
        self._velocity_threshold = velocity_threshold
        self._last_active = 0
        super(IsMovingStimulator, self).__init__(hardware_connection, date_range)

    def _has_moved(self):

        positions = self._tracker.positions

        if len(positions ) <2 :
            return False


        if len(positions[-1]) != 1:
            raise Exception("This stimulator can only work with a single animal per ROI")
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

class SleepDepStimulator(IsMovingStimulator):
    _description = {"overview": "A stimulator to sleep deprive an animal using servo motor. See http://todo/fixme.html",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0060},
                                    {"type": "number", "min": 1, "max": 3600*12, "step":1, "name": "min_inactive_time", "description": "The minimal time after which an inactive animal is awaken","default":120},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}

    _HardwareInterfaceClass = SleepDepriverInterface
    _roi_to_channel = {
            1:1,  3:2,  5:3,  7:4,  9:5,
            12:6, 14:7, 16:8, 18:9, 20:10
        }
    def __init__(self,
                 hardware_connection,
                 velocity_threshold=0.0060,
                 min_inactive_time=120,  #s
                 date_range=""
                 ):
        """
        A stimulator to control a sleep depriver module.

        :param hardware_connection: the sleep depriver module hardware interface
        :type hardware_connection: :class:`~ethoscope.hardawre.interfaces.sleep_depriver_interface.SleepDepriverInterface`
        :param velocity_threshold:
        :type velocity_threshold: float
        :param min_inactive_time: the minimal time without motion after which an animal should be disturbed (in seconds)
        :type min_inactive_time: float
        :return:
        """

        self._inactivity_time_threshold_ms = min_inactive_time *1000 #so we use ms internally
        self._t0 = None
        super(SleepDepStimulator, self).__init__(hardware_connection, velocity_threshold, date_range=date_range)



    def _decide(self):
        roi_id= self._tracker._roi.idx
        now =  self._tracker.last_time_point

        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {}

        has_moved = self._has_moved()


        if self._t0 is None:
            self._t0 = now

        if not has_moved:
            if float(now - self._t0) > self._inactivity_time_threshold_ms:
                self._t0 = None
                return HasInteractedVariable(True), {"channel":channel}
        else:
            self._t0 = now
        return HasInteractedVariable(False), {}

class ExperimentalSleepDepStimulator(SleepDepStimulator):
    _description = {"overview": "An stimulator to sleep deprive an animal using servo motor. See http://todo/fixme.html",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.0001, "name": "velocity_threshold", "description": "The minimal velocity that counts as movement","default":0.0060},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}

    _HardwareInterfaceClass = SleepDepriverInterface
    _roi_to_channel = {
            1:1,  3:2,  5:3,  7:4,  9:5,
            12:6, 14:7, 16:8, 18:9, 20:10
        }

    def __init__(self,
                 hardware_connection,
                 velocity_threshold=0.0060,
                 date_range=""
                 ):
        """
        A stimulator to control a sleep depriver module.
        This is an experimental version where each channel has a different inactivity_time_threshold.

        :param hardware_connection: the sleep depriver module hardware interface
        :type hardware_connection: :class:`~ethoscope.hardawre.interfaces.sleep_depriver_interface.SleepDepriverInterface`
        :param velocity_threshold:
        :type velocity_threshold: float
        :return:
        """

        self._t0 = None

        # the inactive time depends on the chanel here
        super(ExperimentalSleepDepStimulator, self).__init__(hardware_connection, velocity_threshold, 0, date_range)
        self._inactivity_time_threshold_ms = None

    # here we override bind tracker so that we also define inactive time for this stimulator
    def bind_tracker(self, tracker):
        self._tracker = tracker

        roi_id = self._tracker._roi.idx
        try:
            channel = self._roi_to_channel[roi_id]
            self._inactivity_time_threshold_ms = round(channel ** 1.7) * 20 * 1000
        except KeyError:
            pass

