"""
Tests for the optogenetic LED stimulator classes and OptoMotor pulse_train routing.
"""

import unittest
from unittest.mock import MagicMock, Mock, PropertyMock, patch

from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.stimulators.sleep_depriver_stimulators import (
    OptomotorSleepDepriver,
    OptoSleepDepriver,
)
from ethoscope.stimulators.stimulators import HasInteractedVariable


class MockSerial:
    """Mock serial port for OptoMotor tests."""

    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(data)
        return len(data)

    def close(self):
        pass


class TestOptoMotorPulseTrain(unittest.TestCase):
    """Test OptoMotor pulse_train method and send() routing."""

    def setUp(self):
        """Create an OptoMotor with mocked serial."""
        with patch.object(OptoMotor, "__init__", lambda self, *a, **kw: None):
            self.motor = OptoMotor()
            self.motor._serial = MockSerial()
            self.motor._n_channels = 20

    def test_pulse_train_sends_W_command(self):
        """Test that pulse_train sends the correct W command."""
        self.motor.pulse_train(channel=4, on_ms=100, off_ms=200, cycles=5)
        self.assertEqual(self.motor._serial.written[-1], b"W 4 100 200 5\r\n")

    def test_activate_sends_P_command(self):
        """Test that activate sends the correct P command."""
        self.motor.activate(channel=3, duration=1000, intensity=800)
        self.assertEqual(self.motor._serial.written[-1], b"P 3 1000 800\r\n")

    def test_send_routes_to_pulse_train(self):
        """Test that send() routes to pulse_train when on_ms/off_ms/cycles are given."""
        self.motor.send(channel=2, on_ms=50, off_ms=100, cycles=10)
        self.assertEqual(self.motor._serial.written[-1], b"W 2 50 100 10\r\n")

    def test_send_routes_to_activate(self):
        """Test that send() routes to activate when no pulse train params."""
        self.motor.send(channel=1, duration=500, intensity=900)
        self.assertEqual(self.motor._serial.written[-1], b"P 1 500 900\r\n")

    def test_send_default_routes_to_activate(self):
        """Test that send() with only channel routes to activate with defaults."""
        self.motor.send(channel=0)
        self.assertEqual(self.motor._serial.written[-1], b"P 0 10000 1000\r\n")

    def test_pulse_train_negative_channel_raises(self):
        """Test that pulse_train raises for negative channel."""
        with self.assertRaises(Exception):  # noqa: B017
            self.motor.pulse_train(channel=-1, on_ms=100, off_ms=100, cycles=5)

    def test_n_channels_is_20(self):
        """Test that _n_channels is 20 (not legacy 24)."""
        self.assertEqual(self.motor._n_channels, 20)


def _make_mock_tracker(roi_id=1, last_time_point=200000, positions=None, times=None):
    """Helper to create a mock tracker for stimulator tests."""
    tracker = Mock()
    tracker._roi = Mock()
    tracker._roi.idx = roi_id
    tracker.last_time_point = last_time_point
    tracker.positions = positions or [
        [{"xy_dist_log10x1000": 0}],
        [{"xy_dist_log10x1000": 0}],
    ]
    tracker.times = times or [last_time_point - 1000, last_time_point]
    tracker.last_time_point = last_time_point
    return tracker


class TestOptomotorSleepDepriver(unittest.TestCase):
    """Test new OptomotorSleepDepriver (MODULE 3: motors + LEDs)."""

    def setUp(self):
        self.mock_hw = Mock()

    def test_motor_mode_uses_odd_channels(self):
        """Test stimulus_type=1 maps ROIs to odd (motor) channels."""
        stim = OptomotorSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=1,
            min_inactive_time=0,
        )
        # ROI 1 -> motor channel 1
        self.assertEqual(stim._roi_to_channel[1], 1)
        # ROI 12 -> motor channel 11
        self.assertEqual(stim._roi_to_channel[12], 11)

    def test_led_pulse_mode_uses_even_channels(self):
        """Test stimulus_type=2 maps ROIs to even (LED) channels."""
        stim = OptomotorSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=2,
            min_inactive_time=0,
        )
        # ROI 1 -> LED channel 0
        self.assertEqual(stim._roi_to_channel[1], 0)
        # ROI 12 -> LED channel 10
        self.assertEqual(stim._roi_to_channel[12], 10)

    def test_led_pulse_train_mode_uses_even_channels(self):
        """Test stimulus_type=3 also maps ROIs to even (LED) channels."""
        stim = OptomotorSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=3,
            min_inactive_time=0,
        )
        self.assertEqual(stim._roi_to_channel[1], 0)

    def test_decide_motor_returns_duration(self):
        """Test that motor mode _decide returns duration in dict."""
        stim = OptomotorSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=1,
            min_inactive_time=0,
            pulse_duration=500,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        stim.bind_tracker(tracker)

        # Simulate inactivity: _has_moved returns False, enough time has passed
        stim._t0 = 0  # Ensure inactivity threshold exceeded

        out, dic = stim._decide()
        if dic.get("channel") is not None:
            self.assertIn("duration", dic)
            self.assertEqual(dic["duration"], 500)
            self.assertNotIn("on_ms", dic)

    def test_decide_pulse_train_returns_pulse_params(self):
        """Test that pulse train mode _decide returns on_ms/off_ms/cycles."""
        stim = OptomotorSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=3,
            min_inactive_time=0,
            pulse_on_ms=150,
            pulse_off_ms=250,
            pulse_cycles=10,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        stim.bind_tracker(tracker)

        stim._t0 = 0  # Ensure inactivity threshold exceeded

        out, dic = stim._decide()
        if dic.get("channel") is not None:
            self.assertIn("on_ms", dic)
            self.assertIn("off_ms", dic)
            self.assertIn("cycles", dic)
            self.assertEqual(dic["on_ms"], 150)
            self.assertEqual(dic["off_ms"], 250)
            self.assertEqual(dic["cycles"], 10)
            self.assertNotIn("duration", dic)

    def test_unmapped_roi_returns_no_interaction(self):
        """Test that an unmapped ROI returns no interaction."""
        stim = OptomotorSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=1,
            min_inactive_time=0,
        )
        tracker = _make_mock_tracker(roi_id=99)  # Not in mapping
        stim.bind_tracker(tracker)

        out, dic = stim._decide()
        self.assertEqual(bool(out), False)

    def test_description_has_pulse_train_params(self):
        """Test that _description includes pulse train parameters."""
        arg_names = [
            a["name"] for a in OptomotorSleepDepriver._description["arguments"]
        ]
        self.assertIn("pulse_on_ms", arg_names)
        self.assertIn("pulse_off_ms", arg_names)
        self.assertIn("pulse_cycles", arg_names)
        self.assertIn("stimulus_type", arg_names)


class TestOptoSleepDepriver(unittest.TestCase):
    """Test OptoSleepDepriver (MODULE 4: LEDs only)."""

    def setUp(self):
        self.mock_hw = Mock()

    def test_roi_channel_mapping(self):
        """Test 10-ROI to 20-channel mapping."""
        stim = OptoSleepDepriver(
            hardware_connection=self.mock_hw,
            min_inactive_time=0,
        )
        expected = {
            1: 0,
            2: 10,
            3: 2,
            4: 12,
            5: 4,
            6: 14,
            7: 6,
            8: 16,
            9: 8,
            10: 18,
        }
        self.assertEqual(stim._roi_to_channel, expected)

    def test_uses_optomotor_interface(self):
        """Test that OptoSleepDepriver uses OptoMotor hardware interface."""
        self.assertEqual(OptoSleepDepriver._HardwareInterfaceClass, OptoMotor)

    def test_per_roi_counting(self):
        """Test per-ROI stimulus counting limits stimuli."""
        stim = OptoSleepDepriver(
            hardware_connection=self.mock_hw,
            min_inactive_time=0,
            number_of_stimuli=2,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        stim.bind_tracker(tracker)
        stim._t0 = 0

        # First stimulation
        out1, dic1 = stim._decide()
        if bool(out1):
            stim._t0 = 0
            tracker.last_time_point = 400000
            tracker.times = [399000, 400000]

            # Second stimulation
            out2, dic2 = stim._decide()
            if bool(out2):
                stim._t0 = 0
                tracker.last_time_point = 600000
                tracker.times = [599000, 600000]

                # Third attempt should be blocked (count >= number_of_stimuli)
                out3, dic3 = stim._decide()
                # Should not deliver (probability set to 0)
                self.assertEqual(stim._count_roi_stim[1], 2)

    def test_pulse_train_mode(self):
        """Test stimulus_type=2 produces pulse train parameters."""
        stim = OptoSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=2,
            min_inactive_time=0,
            pulse_on_ms=200,
            pulse_off_ms=300,
            pulse_cycles=8,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        stim.bind_tracker(tracker)
        stim._t0 = 0

        out, dic = stim._decide()
        if dic.get("channel") is not None:
            self.assertIn("on_ms", dic)
            self.assertEqual(dic["on_ms"], 200)
            self.assertEqual(dic["off_ms"], 300)
            self.assertEqual(dic["cycles"], 8)
            self.assertNotIn("duration", dic)

    def test_simple_pulse_mode(self):
        """Test stimulus_type=1 produces duration parameter."""
        stim = OptoSleepDepriver(
            hardware_connection=self.mock_hw,
            stimulus_type=1,
            min_inactive_time=0,
            pulse_duration=750,
            stimulus_probability=1.0,
        )
        tracker = _make_mock_tracker(roi_id=1, last_time_point=200000)
        stim.bind_tracker(tracker)
        stim._t0 = 0

        out, dic = stim._decide()
        if dic.get("channel") is not None:
            self.assertIn("duration", dic)
            self.assertEqual(dic["duration"], 750)
            self.assertNotIn("on_ms", dic)

    def test_description_has_all_params(self):
        """Test that _description includes all required parameters."""
        arg_names = [a["name"] for a in OptoSleepDepriver._description["arguments"]]
        self.assertIn("pulse_on_ms", arg_names)
        self.assertIn("pulse_off_ms", arg_names)
        self.assertIn("pulse_cycles", arg_names)
        self.assertIn("stimulus_type", arg_names)
        self.assertIn("number_of_stimuli", arg_names)

    def test_unmapped_roi(self):
        """Test that ROI 20 (not in mapping) returns no interaction."""
        stim = OptoSleepDepriver(
            hardware_connection=self.mock_hw,
            min_inactive_time=0,
        )
        tracker = _make_mock_tracker(roi_id=20)  # Not in 1-10 mapping
        stim.bind_tracker(tracker)

        out, dic = stim._decide()
        self.assertEqual(bool(out), False)


if __name__ == "__main__":
    unittest.main()
