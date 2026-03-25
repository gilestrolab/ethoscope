"""
Stimulus action classes for the ComposedStimulator.

Each action encapsulates WHAT stimulus to deliver (hardware command),
independent of WHEN to deliver it (trigger logic). Actions build instruction
dicts that are passed to the OptoMotor hardware interface.
"""

from ethoscope.hardware.interfaces.optomotor import OptoMotor


class BaseAction:
    """Abstract stimulus action for ComposedStimulator."""

    _HardwareInterfaceClass = OptoMotor
    _description = {}
    channel_type = None  # "motor", "led", or "valve"

    def build_instruction(self, channel):
        """
        Build the hardware instruction dict for delivering this stimulus.

        Args:
            channel (int): The hardware channel to activate.

        Returns:
            dict: Keyword arguments for OptoMotor.send()
        """
        raise NotImplementedError


class MotorPulseAction(BaseAction):
    """Deliver a motor pulse (P command)."""

    channel_type = "motor"

    def __init__(self, pulse_duration=1000):
        self._pulse_duration = int(pulse_duration)

    def build_instruction(self, channel):
        return {"channel": channel, "duration": self._pulse_duration}


class LEDPulseAction(BaseAction):
    """Deliver a single LED pulse (P command)."""

    channel_type = "led"

    def __init__(self, pulse_duration=1000):
        self._pulse_duration = int(pulse_duration)

    def build_instruction(self, channel):
        return {"channel": channel, "duration": self._pulse_duration}


class LEDPulseTrainAction(BaseAction):
    """Deliver an LED pulse train (W command)."""

    channel_type = "led"

    def __init__(self, pulse_on_ms=100, pulse_off_ms=100, pulse_cycles=5):
        self._on_ms = int(pulse_on_ms)
        self._off_ms = int(pulse_off_ms)
        self._cycles = int(pulse_cycles)

    def build_instruction(self, channel):
        return {
            "channel": channel,
            "on_ms": self._on_ms,
            "off_ms": self._off_ms,
            "cycles": self._cycles,
        }


class ValvePulseAction(BaseAction):
    """Deliver a valve/odour pulse (P command)."""

    channel_type = "valve"

    def __init__(self, pulse_duration=500):
        self._pulse_duration = int(pulse_duration)

    def build_instruction(self, channel):
        return {"channel": channel, "duration": self._pulse_duration}


# Registry mapping action_type string values to classes
ACTION_REGISTRY = {
    "motor_pulse": MotorPulseAction,
    "led_pulse": LEDPulseAction,
    "led_pulse_train": LEDPulseTrainAction,
    "valve_pulse": ValvePulseAction,
}
