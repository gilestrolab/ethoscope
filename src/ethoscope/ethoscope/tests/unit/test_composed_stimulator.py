"""
Tests for the ComposedStimulator trigger/action architecture.

Tests triggers, actions, channel maps, and the ComposedStimulator integration.
"""

from unittest.mock import MagicMock, PropertyMock

import pytest

from ethoscope.stimulators.actions import (
    ACTION_REGISTRY,
    LEDPulseAction,
    LEDPulseTrainAction,
    MotorPulseAction,
    ValvePulseAction,
)
from ethoscope.stimulators.channel_maps import get_channel_map
from ethoscope.stimulators.composed_stimulator import ComposedStimulator
from ethoscope.stimulators.stimulators import HasInteractedVariable
from ethoscope.stimulators.triggers import (
    TRIGGER_REGISTRY,
    InactivityTrigger,
    MidlineCrossingTrigger,
    PeriodicTrigger,
    TimeRestrictedInactivityTrigger,
)

# --- Fixtures ---


def _make_mock_tracker(
    positions=None, times=None, last_time_point=0, roi_idx=1, roi_longest_axis=100.0
):
    """Create a mock tracker with configurable position/time data."""
    tracker = MagicMock()
    tracker.positions = positions or []
    tracker.times = times or []
    tracker.last_time_point = last_time_point

    roi = MagicMock()
    roi.idx = roi_idx
    roi.longest_axis = roi_longest_axis
    tracker._roi = roi

    return tracker


def _make_inactive_tracker(inactive_time_ms=200_000, roi_idx=1):
    """Create a tracker showing an inactive animal for the given duration.

    Note: xy_dist_log10x1000 encodes distance as log10(dist) * 1000.
    A value of -10000 means dist = 10^(-10) ~ 0 (effectively stationary).
    """
    pos_data = {"xy_dist_log10x1000": -10000, "x": 50}  # Near-zero distance
    positions = [[pos_data], [pos_data]]
    times = [0, inactive_time_ms]
    return _make_mock_tracker(
        positions=positions,
        times=times,
        last_time_point=inactive_time_ms,
        roi_idx=roi_idx,
    )


def _make_moving_tracker(roi_idx=1):
    """Create a tracker showing a moving animal."""
    pos1 = {"xy_dist_log10x1000": 3000, "x": 20}  # dist=10^3 = 1000
    pos2 = {"xy_dist_log10x1000": 3000, "x": 80}
    positions = [[pos1], [pos2]]
    times = [0, 100]  # 100ms apart
    return _make_mock_tracker(
        positions=positions,
        times=times,
        last_time_point=100,
        roi_idx=roi_idx,
    )


# --- Trigger Tests ---


class TestInactivityTrigger:
    def test_fires_after_inactivity(self):
        trigger = InactivityTrigger(min_inactive_time=120, stimulus_probability=1.0)
        tracker = _make_inactive_tracker(inactive_time_ms=200_000)
        trigger.bind_tracker(tracker)

        # First call sets _t0 at an early time
        trigger._t0 = 0  # Simulate prior initialization

        code, meta = trigger.check()
        assert code == 1  # Real stimulation

    def test_does_not_fire_when_moving(self):
        trigger = InactivityTrigger(min_inactive_time=120)
        tracker = _make_moving_tracker()
        trigger.bind_tracker(tracker)

        code, meta = trigger.check()
        assert code == 0  # No stimulation

    def test_does_not_fire_before_threshold(self):
        trigger = InactivityTrigger(min_inactive_time=120)
        tracker = _make_inactive_tracker(inactive_time_ms=50_000)  # Only 50s
        trigger.bind_tracker(tracker)

        code, meta = trigger.check()
        assert code == 0

    def test_ghost_stimulation_with_zero_probability(self):
        trigger = InactivityTrigger(min_inactive_time=120, stimulus_probability=0.0)
        tracker = _make_inactive_tracker(inactive_time_ms=200_000)
        trigger.bind_tracker(tracker)

        trigger._t0 = 0  # Simulate prior initialization

        code, meta = trigger.check()
        assert code == 2  # Ghost stimulation

    def test_invalid_probability_raises(self):
        with pytest.raises(ValueError):
            InactivityTrigger(stimulus_probability=1.5)

    def test_few_positions_returns_no_fire(self):
        trigger = InactivityTrigger(min_inactive_time=120)
        tracker = _make_mock_tracker(positions=[[{"xy_dist_log10x1000": 0}]])
        trigger.bind_tracker(tracker)

        code, meta = trigger.check()
        assert code == 0


class TestMidlineCrossingTrigger:
    def test_fires_on_crossing(self):
        trigger = MidlineCrossingTrigger(stimulus_probability=1.0)

        # Position: animal was at x=20 (left of center), now at x=80 (right of center)
        # roi width=100, so midline is at x=50
        pos1 = {"x": 20}
        pos2 = {"x": 80}
        tracker = _make_mock_tracker(
            positions=[[pos1], [pos2]],
            times=[0, 100],
            last_time_point=100_000,  # Well past refractory period
        )
        trigger.bind_tracker(tracker)

        code, meta = trigger.check()
        assert code == 1

    def test_does_not_fire_no_crossing(self):
        trigger = MidlineCrossingTrigger(stimulus_probability=1.0)

        # Both positions on same side of midline
        pos1 = {"x": 20}
        pos2 = {"x": 30}
        tracker = _make_mock_tracker(
            positions=[[pos1], [pos2]],
            times=[0, 100],
            last_time_point=100_000,
        )
        trigger.bind_tracker(tracker)

        code, meta = trigger.check()
        assert code == 0

    def test_refractory_period(self):
        trigger = MidlineCrossingTrigger(
            stimulus_probability=1.0, refractory_period_s=60
        )

        pos1 = {"x": 20}
        pos2 = {"x": 80}
        tracker = _make_mock_tracker(
            positions=[[pos1], [pos2]],
            times=[0, 100],
            last_time_point=100_000,
        )
        trigger.bind_tracker(tracker)

        # First crossing fires
        code, _ = trigger.check()
        assert code == 1

        # Second check within refractory period
        tracker.last_time_point = 110_000  # Only 10s later
        code, _ = trigger.check()
        assert code == 0

    def test_too_few_positions(self):
        trigger = MidlineCrossingTrigger()
        tracker = _make_mock_tracker(
            positions=[[{"x": 50}]], times=[0], last_time_point=100_000
        )
        trigger.bind_tracker(tracker)

        code, _ = trigger.check()
        assert code == 0


class TestPeriodicTrigger:
    def test_fires_at_interval(self):
        trigger = PeriodicTrigger(interval_seconds=60)
        tracker = _make_mock_tracker(last_time_point=61_000)  # 61s
        trigger.bind_tracker(tracker)

        code, _ = trigger.check()
        assert code == 1

    def test_does_not_fire_before_interval(self):
        trigger = PeriodicTrigger(interval_seconds=60)
        tracker = _make_mock_tracker(last_time_point=61_000)
        trigger.bind_tracker(tracker)

        # First check fires
        trigger.check()

        # Immediately after, should not fire
        tracker.last_time_point = 62_000
        code, _ = trigger.check()
        assert code == 0


# --- Action Tests ---


class TestActions:
    def test_motor_pulse(self):
        action = MotorPulseAction(pulse_duration=1500)
        result = action.build_instruction(channel=3)
        assert result == {"channel": 3, "duration": 1500}
        assert action.channel_type == "motor"

    def test_led_pulse(self):
        action = LEDPulseAction(pulse_duration=500)
        result = action.build_instruction(channel=2)
        assert result == {"channel": 2, "duration": 500}
        assert action.channel_type == "led"

    def test_led_pulse_train(self):
        action = LEDPulseTrainAction(pulse_on_ms=100, pulse_off_ms=200, pulse_cycles=10)
        result = action.build_instruction(channel=4)
        assert result == {
            "channel": 4,
            "on_ms": 100,
            "off_ms": 200,
            "cycles": 10,
        }
        assert action.channel_type == "led"

    def test_valve_pulse(self):
        action = ValvePulseAction(pulse_duration=300)
        result = action.build_instruction(channel=0)
        assert result == {"channel": 0, "duration": 300}
        assert action.channel_type == "valve"


# --- Channel Map Tests ---


class TestChannelMaps:
    def test_motor_map(self):
        m = get_channel_map("motor")
        assert m[1] == 1  # ROI 1 -> channel 1
        assert m[3] == 3
        assert m[12] == 11
        assert m[20] == 19
        assert len(m) == 10

    def test_led_map(self):
        m = get_channel_map("led")
        assert m[1] == 0  # ROI 1 -> channel 0
        assert m[3] == 2
        assert m[12] == 10
        assert len(m) == 10

    def test_valve_map(self):
        m = get_channel_map("valve")
        assert m[1] == 0
        assert m[11] == 10  # mAGO valve numbering
        assert len(m) == 10

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown channel_type"):
            get_channel_map("unknown")


# --- Registry Tests ---


class TestRegistries:
    def test_trigger_registry(self):
        assert set(TRIGGER_REGISTRY.keys()) == {
            "inactivity",
            "midline_crossing",
            "periodic",
            "time_restricted",
        }

    def test_action_registry(self):
        assert set(ACTION_REGISTRY.keys()) == {
            "motor_pulse",
            "led_pulse",
            "led_pulse_train",
            "valve_pulse",
        }


# --- ComposedStimulator Integration Tests ---


class TestComposedStimulator:
    def test_inactivity_motor_pulse(self):
        """Basic integration: inactivity trigger + motor pulse action."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="inactivity",
            action_type="motor_pulse",
            min_inactive_time=120,
            pulse_duration=1000,
        )

        tracker = _make_inactive_tracker(inactive_time_ms=200_000, roi_idx=1)
        stim.bind_tracker(tracker)
        stim._trigger._t0 = 0  # Simulate prior initialization

        interact, result = stim._decide()
        assert int(interact) == 1
        assert result["channel"] == 1  # ROI 1 -> motor channel 1
        assert result["duration"] == 1000

    def test_inactivity_led_pulse_train(self):
        """Inactivity trigger + LED pulse train action."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="inactivity",
            action_type="led_pulse_train",
            min_inactive_time=120,
            pulse_on_ms=50,
            pulse_off_ms=100,
            pulse_cycles=3,
        )

        tracker = _make_inactive_tracker(inactive_time_ms=200_000, roi_idx=3)
        stim.bind_tracker(tracker)
        stim._trigger._t0 = 0  # Simulate prior initialization

        interact, result = stim._decide()
        assert int(interact) == 1
        assert result["channel"] == 2  # ROI 3 -> LED channel 2
        assert result["on_ms"] == 50
        assert result["off_ms"] == 100
        assert result["cycles"] == 3

    def test_no_stimulation_when_moving(self):
        """No stimulation when animal is moving."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="inactivity",
            action_type="motor_pulse",
        )

        tracker = _make_moving_tracker(roi_idx=1)
        stim.bind_tracker(tracker)

        interact, result = stim._decide()
        assert int(interact) == 0

    def test_unmapped_roi_returns_false(self):
        """ROI not in channel map returns no interaction."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="inactivity",
            action_type="motor_pulse",
        )

        # ROI 99 doesn't exist in any channel map
        tracker = _make_inactive_tracker(roi_idx=99)
        stim.bind_tracker(tracker)

        interact, result = stim._decide()
        assert not interact

    def test_periodic_trigger(self):
        """Periodic trigger fires at intervals."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="periodic",
            action_type="led_pulse",
            interval_seconds=30,
            pulse_duration=500,
        )

        tracker = _make_mock_tracker(
            positions=[], times=[], last_time_point=31_000, roi_idx=1
        )
        stim.bind_tracker(tracker)

        interact, result = stim._decide()
        assert int(interact) == 1
        assert result["channel"] == 0  # ROI 1 -> LED channel 0
        assert result["duration"] == 500

    def test_valve_action_uses_valve_channels(self):
        """Valve action uses the valve channel map."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="periodic",
            action_type="valve_pulse",
            interval_seconds=30,
            pulse_duration=300,
        )

        # ROI 11 exists in valve map but not in motor/led maps
        tracker = _make_mock_tracker(
            positions=[], times=[], last_time_point=31_000, roi_idx=11
        )
        stim.bind_tracker(tracker)

        interact, result = stim._decide()
        assert int(interact) == 1
        assert result["channel"] == 10  # ROI 11 -> valve channel 10
        assert result["duration"] == 300

    def test_invalid_trigger_type_raises(self):
        with pytest.raises(ValueError, match="Unknown trigger_type"):
            ComposedStimulator(
                hardware_connection=MagicMock(),
                trigger_type="nonexistent",
            )

    def test_invalid_action_type_raises(self):
        with pytest.raises(ValueError, match="Unknown action_type"):
            ComposedStimulator(
                hardware_connection=MagicMock(),
                action_type="nonexistent",
            )

    def test_description_has_required_fields(self):
        desc = ComposedStimulator._description
        assert "overview" in desc
        assert "arguments" in desc

        arg_names = [a["name"] for a in desc["arguments"]]
        assert "trigger_type" in arg_names
        assert "action_type" in arg_names

        # Check select-type args have options
        for arg in desc["arguments"]:
            if arg["type"] == "select":
                assert "options" in arg
                assert len(arg["options"]) > 0
                for opt in arg["options"]:
                    assert "value" in opt
                    assert "label" in opt

    def test_midline_crossing_with_motor(self):
        """Midline crossing trigger + motor pulse."""
        hw = MagicMock()
        stim = ComposedStimulator(
            hardware_connection=hw,
            trigger_type="midline_crossing",
            action_type="motor_pulse",
            pulse_duration=800,
        )

        pos1 = {"x": 20, "xy_dist_log10x1000": 0}
        pos2 = {"x": 80, "xy_dist_log10x1000": 0}
        tracker = _make_mock_tracker(
            positions=[[pos1], [pos2]],
            times=[0, 100],
            last_time_point=100_000,
            roi_idx=1,
        )
        stim.bind_tracker(tracker)

        interact, result = stim._decide()
        assert int(interact) == 1
        assert result["channel"] == 1  # ROI 1 -> motor channel 1
        assert result["duration"] == 800
