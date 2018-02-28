from ethoscope.stimulators.sleep_depriver_stimulators import MiddleCrossingStimulator
from ethoscope.hardware.interfaces.optomotor import OptoMotor


class OptoMidlineCrossStimulator (MiddleCrossingStimulator):
    _description = {"overview": "A stimulator to shine light when animals cross the midline",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.01, "name": "p", "description": "the probability to move the tube when a beam cross was detected","default":1.0},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}
    _HardwareInterfaceClass = OptoMotor
    _roi_to_channel = {
        1: 1,
        3: 3,
        5: 5,
        7: 7,
        9: 9,
        12: 23,
        14: 21,
        16: 19,
        18: 17,
        20: 15
    }


class MotoMidlineCrossStimulator (MiddleCrossingStimulator):
    _description = {"overview": "A stimulator to turn gear motor when animals cross the midline",
                    "arguments": [
                                    {"type": "number", "min": 0.0, "max": 1.0, "step":0.01, "name": "p", "description": "the probability to move the tube when a beam cross was detected","default":1.0},
                                    {"type": "date_range", "name": "date_range",
                                     "description": "A date and time range in which the device will perform (see http://tinyurl.com/jv7k826)",
                                     "default": ""}
                                   ]}
    _HardwareInterfaceClass = OptoMotor
    _roi_to_channel = {1:0, 3:2, 5:4, 7:6, 9:8,
                       12:22, 14:20, 16:18, 18:16, 20:14}
    _duration = 2000 #ms

    def _decide(self):
        out = super(MotoMidlineCrossStimulator, self)._decide()
        out["duration"] = self._duration
