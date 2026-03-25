from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.stimulators.sleep_depriver_stimulators import MiddleCrossingStimulator


class OptoMidlineCrossStimulator(MiddleCrossingStimulator):
    """
    Shine LED light when animals cross the midline.
    Uses MODULE 3 LED even-channel mapping (same as OptomotorSleepDepriver LEDs).
    """

    _description = {
        "overview": "A stimulator to shine LED light when animals cross the midline (MODULE 3/4 LED channels)",
        "hidden": True,
        "arguments": [
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.01,
                "name": "stimulus_probability",
                "description": "the probability to activate the LED when a beam cross was detected",
                "default": 1.0,
            },
            {
                "type": "date_range",
                "name": "date_range",
                "description": "Active time period",
                "default": "",
            },
        ],
    }
    _HardwareInterfaceClass = OptoMotor

    # LEDs on even channels (MODULE 3/4 layout)
    _roi_to_channel = {
        1: 0,
        3: 2,
        5: 4,
        7: 6,
        9: 8,
        12: 10,
        14: 12,
        16: 14,
        18: 16,
        20: 18,
    }
