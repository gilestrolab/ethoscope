"""
Unit tests for stimulators/actions.py and stimulators/channel_maps.py.

Tests action classes, action registry, channel map generation,
and LED count-dependent mapping.
"""

import unittest

from ethoscope.stimulators.actions import (
    ACTION_REGISTRY,
    BaseAction,
    LEDPulseAction,
    LEDPulseTrainAction,
    MotorPulseAction,
    ValvePulseAction,
)
from ethoscope.stimulators.channel_maps import get_channel_map


# ===========================================================================
# BaseAction
# ===========================================================================


class TestBaseAction(unittest.TestCase):
    def test_build_instruction_raises(self):
        action = BaseAction()
        with self.assertRaises(NotImplementedError):
            action.build_instruction(0)

    def test_channel_type_is_none(self):
        self.assertIsNone(BaseAction.channel_type)


# ===========================================================================
# MotorPulseAction
# ===========================================================================


class TestMotorPulseAction(unittest.TestCase):
    def test_channel_type(self):
        self.assertEqual(MotorPulseAction.channel_type, "motor")

    def test_build_instruction(self):
        action = MotorPulseAction(pulse_duration=500)
        result = action.build_instruction(3)
        self.assertEqual(result, {"channel": 3, "duration": 500})

    def test_default_duration(self):
        action = MotorPulseAction()
        result = action.build_instruction(1)
        self.assertEqual(result["duration"], 1000)


# ===========================================================================
# LEDPulseAction
# ===========================================================================


class TestLEDPulseAction(unittest.TestCase):
    def test_channel_type(self):
        self.assertEqual(LEDPulseAction.channel_type, "led")

    def test_build_instruction(self):
        action = LEDPulseAction(pulse_duration=750)
        result = action.build_instruction(0)
        self.assertEqual(result, {"channel": 0, "duration": 750})


# ===========================================================================
# LEDPulseTrainAction
# ===========================================================================


class TestLEDPulseTrainAction(unittest.TestCase):
    def test_channel_type(self):
        self.assertEqual(LEDPulseTrainAction.channel_type, "led")

    def test_build_instruction(self):
        action = LEDPulseTrainAction(pulse_on_ms=150, pulse_off_ms=250, pulse_cycles=10)
        result = action.build_instruction(2)
        self.assertEqual(
            result, {"channel": 2, "on_ms": 150, "off_ms": 250, "cycles": 10}
        )

    def test_default_values(self):
        action = LEDPulseTrainAction()
        result = action.build_instruction(0)
        self.assertEqual(result["on_ms"], 100)
        self.assertEqual(result["off_ms"], 100)
        self.assertEqual(result["cycles"], 5)


# ===========================================================================
# ValvePulseAction
# ===========================================================================


class TestValvePulseAction(unittest.TestCase):
    def test_channel_type(self):
        self.assertEqual(ValvePulseAction.channel_type, "valve")

    def test_build_instruction(self):
        action = ValvePulseAction(pulse_duration=300)
        result = action.build_instruction(4)
        self.assertEqual(result, {"channel": 4, "duration": 300})

    def test_default_duration(self):
        action = ValvePulseAction()
        result = action.build_instruction(0)
        self.assertEqual(result["duration"], 500)


# ===========================================================================
# ACTION_REGISTRY
# ===========================================================================


class TestActionRegistry(unittest.TestCase):
    def test_all_keys(self):
        expected = {"motor_pulse", "led_pulse", "led_pulse_train", "valve_pulse"}
        self.assertEqual(set(ACTION_REGISTRY.keys()), expected)

    def test_values(self):
        self.assertIs(ACTION_REGISTRY["motor_pulse"], MotorPulseAction)
        self.assertIs(ACTION_REGISTRY["led_pulse"], LEDPulseAction)
        self.assertIs(ACTION_REGISTRY["led_pulse_train"], LEDPulseTrainAction)
        self.assertIs(ACTION_REGISTRY["valve_pulse"], ValvePulseAction)


# ===========================================================================
# get_channel_map
# ===========================================================================


class TestGetChannelMap(unittest.TestCase):
    def test_motor_returns_odd_channels(self):
        cmap = get_channel_map("motor")
        for roi_id, channel in cmap.items():
            self.assertEqual(channel % 2, 1, f"Motor ROI {roi_id} has even channel {channel}")

    def test_led_default_returns_even_channels(self):
        cmap = get_channel_map("led")
        for roi_id, channel in cmap.items():
            self.assertEqual(channel % 2, 0, f"LED ROI {roi_id} has odd channel {channel}")

    def test_led_20_leds_returns_20_channels(self):
        cmap = get_channel_map("led", led_count=20)
        self.assertEqual(len(cmap), 20)
        self.assertEqual(cmap[1], 0)
        self.assertEqual(cmap[20], 19)

    def test_led_10_leds_returns_10_channels(self):
        cmap = get_channel_map("led", led_count=10)
        self.assertEqual(len(cmap), 10)

    def test_led_none_count_returns_default(self):
        cmap = get_channel_map("led", led_count=None)
        self.assertEqual(len(cmap), 10)

    def test_valve_returns_even_channels(self):
        cmap = get_channel_map("valve")
        for roi_id, channel in cmap.items():
            self.assertEqual(channel % 2, 0, f"Valve ROI {roi_id} has odd channel {channel}")

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            get_channel_map("unknown")

    def test_returns_copy(self):
        """Returned map should be a copy, not the original."""
        cmap1 = get_channel_map("motor")
        cmap2 = get_channel_map("motor")
        cmap1[999] = 999
        self.assertNotIn(999, cmap2)


if __name__ == "__main__":
    unittest.main()
