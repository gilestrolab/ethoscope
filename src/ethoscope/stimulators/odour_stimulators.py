__author__ = 'quentin'

import logging
from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable
from ethoscope.utils.scheduler import Scheduler
from ethoscope.hardware.interfaces.interfaces import  DefaultInterface
from ethoscope.hardware.interfaces.odour_delivery_device import OdourDelivererInterface, OdourDepriverInterface, OdourDelivererFlushedInterface
from ethoscope.hardware.interfaces.odour_delivery_device import OdourDelivererInterface, OdourDepriverInterface
from . import sleep_depriver_stimulators
import random

class HasChangedSideStimulator(BaseStimulator):
    _HardwareInterfaceClass = DefaultInterface

    def __init__(self, hardware_connection=None, middle_line=0.50):
        """
        class implementing a stimulator that decides whether an animal has change side in its ROI.
        :param hardware_connection: a default hardware interface object
        :param middle_line: the x position defining the line to be crossed (from 0 to 1, relative to ROI)
        :type middle_line: float
        """
        self._middle_line = middle_line
        #self._last_active = 0
        super(HasChangedSideStimulator, self).__init__(hardware_connection)

    def _has_changed_side(self):
        positions = self._tracker.positions

        if len(positions ) <2 :
            return False

        w = float(self._tracker._roi.get_feature_dict()["w"])
        if len(positions[-1]) != 1:
            raise Exception("This stimulator can only work with a single animal per ROI")
        x0 = positions[-1][0]["x"] / w
        xm1 = positions[-2][0]["x"] / w


        if x0 > self._middle_line:
            current_region = 2
        else:
            current_region = 1

        if xm1 > self._middle_line:
            past_region = 2
        else:
            past_region = 1

        if self._tracker._roi == 1:
            logging.warning(str((x0, xm1, current_region, past_region)))

        if current_region != past_region:
            # we return the current region as 1 or 2 if it has changed
            return current_region
        else:
            # no change => 0
            return 0

    def _decide(self):
        has_changed = self._has_changed_side()

        if  has_changed:
            return HasInteractedVariable(True), {}
        return HasInteractedVariable(False), {}

class DynamicOdourDeliverer(HasChangedSideStimulator):
    _description = {"overview": "A stimulator to deliver an odour according to which side the animal of its ROI is in",
                    "arguments": [
                                {"type": "date_range", "name": "date_range",
                                 "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                 "default": ""}
                                   ]}

    _HardwareInterfaceClass =  OdourDelivererInterface
    _roi_to_channel = {
            1:1,  2:2,  3:3,  4:4,  5:5,
            6:6, 7:7, 8:8, 9:9, 10:10
        }
    _side_to_pos = {1:1, 2:2 }
    def __init__(self,
                 hardware_connection,
                 date_range=""
                 ):
        """
        A stimulator to control a sleep depriver module

        :param hardware_connection: the sleep depriver module hardware interface
        :type hardware_connection: :class:`~ethoscope.hardawre.interfaces.`
        :return:
        """

        self._t0 = None
        self._scheduler = Scheduler(date_range)
        super(DynamicOdourDeliverer, self).__init__(hardware_connection)



    def _decide(self):
        roi_id= self._tracker._roi.idx
        try:
            channel = self._roi_to_channel[roi_id]
        except KeyError:
            return HasInteractedVariable(False), {}

        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False), {}

        has_changed_side = self._has_changed_side()

        if has_changed_side == 0:
            return HasInteractedVariable(False), {}
        pos = self._side_to_pos[has_changed_side]
        return HasInteractedVariable(pos), {"channel":channel, "pos" : self._side_to_pos[has_changed_side]}

class DynamicOdourSleepDepriver(sleep_depriver_stimulators.SleepDepStimulator):
    _description = {
        "overview": "An stimulator to sleep deprive an animal using servo motor. See http://todo/fixme.html",
        "arguments": [
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.0001, "name": "velocity_correction_coef",
             "description": "Velocity correction coef", "default": 3.0e-3 / 2},
            {"type": "number", "min": 2.0, "max": 10.0, "step": 0.5, "name": "stimulus_duration",
             "description": "How long to send the puff of odour for", "default": 5.0},
            {"type": "number", "min": 1, "max": 3600 * 12, "step": 1, "name": "min_inactive_time",
             "description": "The minimal time after which an inactive animal is awaken", "default": 120},
            {"type": "date_range", "name": "date_range",
             "description": "A date  and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
             "default": ""}
        ]}

    _HardwareInterfaceClass =  OdourDepriverInterface
    _roi_to_channel = {
            1:1,  2:2,  3:3,  4:4,  5:5,
            6:6, 7:7, 8:8, 9:9, 10:10
        }

    def __init__(self,
                 hardware_connection,
                 velocity_correction_coef=3.0e-3 / 2,
                 min_inactive_time=120,  # s
                 stimulus_duration=5,  #s
                 date_range=""
                 ):
        """
        A stimulator to control an odour sleep depriver module.

        :param hardware_connection: the sleep depriver module hardware interface
        :type hardware_connection: :class:`~ethoscope.hardawre.interfaces.sleep_depriver_interface.SleepDepriverInterface`
        :param velocity_correction_coef: correct velocity by this coefficient to make it fps-inveriant. 1 => walking
        :type velocity_correction_coef: float
        :param stimulus_duration: how long the odour delivery takes place for
        :type stimulus_duration: float
        :param min_inactive_time: the minimal time without motion after which an animal should be disturbed (in seconds)
        :type min_inactive_time: float
        :return:
        """
        self._stimulus_duration = stimulus_duration
        super(DynamicOdourSleepDepriver, self).__init__(hardware_connection, velocity_correction_coef, min_inactive_time, date_range)

    def _decide(self):
        decide, args = super(DynamicOdourSleepDepriver, self)._decide()
        args["stimulus_duration"] = self._stimulus_duration

        return decide, args



class MiddleCrossingOdourStimulator(sleep_depriver_stimulators.MiddleCrossingStimulator):
    _description = {"overview": "A stimulator to send odour to an animal as it crosses the midline",
                    "arguments": [
                        {"type": "number", "min": 0.0, "max": 1.0, "step": 0.01, "name": "p",
                         "description": "the probability to move the tube when a beam cross was detected",
                         "default": 1.0},
                        {"type": "number", "min": 0.0, "max": 300, "step": 1, "name": "refractory_period",
                         "description": "cannot send two stimuli if they are not separated from, at least, this duration",
                         "default": 120},
                        {"type": "number", "min": 2.0, "max": 10.0, "step": 0.5, "name": "stimulus_duration",
                         "description": "How long to send the puff of odour for", "default": 5.0},
                        {"type": "date_range", "name": "date_range",
                         "description": "A date and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                         "default": ""}
                    ]}

    _HardwareInterfaceClass = OdourDepriverInterface

    _roi_to_channel = {
            1:1,  2:2,  3:3,  4:4,  5:5,
            6:6, 7:7, 8:8, 9:9, 10:10
        }



    def __init__(self,
                 hardware_connection,
                 p=1.0,
                 refractory_period = 300,
                 stimulus_duration = 5,
                 date_range=""
                 ):

        super(MiddleCrossingOdourStimulator, self).__init__(hardware_connection, p=p, date_range=date_range)
        self._refractory_period = refractory_period
        self._stimulus_duration = stimulus_duration


    def _decide(self):
        decide, args = super(MiddleCrossingOdourStimulator, self)._decide()
        args["stimulus_duration"] = self._stimulus_duration

        return decide, args

class MiddleCrossingOdourStimulatorFlushed(MiddleCrossingOdourStimulator):
    _description = {"overview": "A stimulator to send odour to an animal as it crosses the midline, and then flush it",
                    "arguments": [
                        {"type": "number", "min": 0.0, "max": 1.0, "step": 0.01, "name": "p",
                         "description": "the probability to move the tube when a beam cross was detected",
                         "default": 1.0},
                        {"type": "number", "min": 0.0, "max": 300, "step": 1, "name": "refractory_period",
                         "description": "cannot send two stimuli if they are not separated from, at least, this duration",
                         "default": 120},
                        {"type": "number", "min": 2.0, "max": 10.0, "step": 0.5, "name": "stimulus_duration",
                         "description": "How long to send the puff of odour for", "default": 5.0},
                        {"type": "number", "min": 2.0, "max": 60.0, "step": 0.5, "name": "flush_duration",
                         "description": "How long to flush odour for", "default": 10.0},
                        {"type": "date_range", "name": "date_range",
                         "description": "A date and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                         "default": ""}
                    ]}

    _HardwareInterfaceClass = OdourDelivererFlushedInterface
    _roi_to_channel = {
            1:1,  2:2,  3:3,  4:4,  5:5,
            6:6, 7:7, 8:8, 9:9, 10:10
        }

    def __init__(self,
                 hardware_connection,
                 p=1.0,
                 refractory_period = 300,
                 stimulus_duration = 5,
                 flush_duration=10,
                 date_range=""
                 ):

        super(MiddleCrossingOdourStimulator, self).__init__(hardware_connection, p=p, date_range=date_range)
        self._refractory_period = refractory_period
        self._stimulus_duration = stimulus_duration
        self._flush_duration = flush_duration


    def _decide(self):
        decide, args = super(MiddleCrossingOdourStimulator, self)._decide()
        args["stimulus_duration"] = self._stimulus_duration
        args["flush_duration"] = self._flush_duration

        return decide, args