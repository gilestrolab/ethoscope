"""
ROI-to-channel maps by module and arena.

ComposedStimulator used one map per stimulus type whatever the arena: valves
always got mAGO's 20-tube map, so on a 10-tube AGO arena ROIs 2, 4, 6, 8 and 10
were never stimulated. The maps are now chosen by what the module reports and
by the number of ROIs, and are the maps of the legacy classes written for each
layout (AGO, mAGO, OptoSleepDepriver, OptomotorSleepDepriver).

The tables below are written out by hand on purpose: they are what the manual
states.
"""

from unittest.mock import Mock

import pytest

from ethoscope.control.tracking import ControlThread
from ethoscope.stimulators.channel_maps import get_channel_map
from ethoscope.stimulators.composed_stimulator import ComposedStimulator
from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.sleep_depriver_stimulators import (
    AGO,
    OptomotorSleepDepriver,
    OptoSleepDepriver,
    mAGO,
)
from ethoscope.utils.debug import EthoscopeException

# --- 20-tube arena (two columns of ten: ROIs 1-10 and 11-20) ---
MOTORS_20 = {1: 1, 3: 3, 5: 5, 7: 7, 9: 9, 12: 11, 14: 13, 16: 15, 18: 17, 20: 19}
LEDS_10_OF_20 = {1: 0, 3: 2, 5: 4, 7: 6, 9: 8, 12: 10, 14: 12, 16: 14, 18: 16, 20: 18}
LEDS_20_OF_20 = {roi: roi - 1 for roi in range(1, 21)}
VALVES_20 = {1: 0, 3: 2, 5: 4, 7: 6, 9: 8, 11: 10, 13: 12, 15: 14, 17: 16, 19: 18}

# --- 10-tube arena (one column of ten long tubes) ---
EVEN_10 = {1: 0, 2: 10, 3: 2, 4: 12, 5: 4, 6: 14, 7: 6, 8: 16, 9: 8, 10: 18}
MOTORS_10 = {1: 1, 2: 11, 3: 3, 4: 13, 5: 5, 6: 15, 7: 7, 8: 17, 9: 9, 10: 19}

# What each firmware MODULE reports in its reply to T.
MODULES = {
    0: ("N20 Sleep Deprivation Module", {"motors": 10, "valves": 0, "leds": 0}),
    1: (
        "AGOSD Sleep Deprivation and Odour Arousal Module",
        {"motors": 10, "valves": 10, "leds": 0},
    ),
    2: ("AGO Odour Arousal Module", {"motors": 0, "valves": 10, "leds": 0}),
    3: (
        "mAGOLED Motor and Optogenetic LED Module",
        {"motors": 10, "valves": 0, "leds": 10},
    ),
    4: ("LED Optogenetic Module", {"motors": 0, "valves": 0, "leds": 20}),
}

REFUSED = None

# (module, action_type, n_rois) -> expected map, or REFUSED when the module has
# nothing to deliver that stimulus with.
EXPECTED = {
    (0, "motor_pulse", 20): MOTORS_20,
    (0, "motor_pulse", 10): MOTORS_10,
    (0, "led_pulse", 20): REFUSED,
    (0, "valve_pulse", 20): REFUSED,
    (1, "motor_pulse", 20): MOTORS_20,
    (1, "motor_pulse", 10): MOTORS_10,
    (1, "valve_pulse", 20): VALVES_20,
    (1, "valve_pulse", 10): EVEN_10,
    (1, "led_pulse", 20): REFUSED,
    (2, "valve_pulse", 20): VALVES_20,
    (2, "valve_pulse", 10): EVEN_10,
    (2, "motor_pulse", 10): REFUSED,
    (2, "led_pulse", 10): REFUSED,
    (3, "motor_pulse", 20): MOTORS_20,
    (3, "motor_pulse", 10): MOTORS_10,
    (3, "led_pulse", 20): LEDS_10_OF_20,
    (3, "led_pulse", 10): EVEN_10,
    (3, "led_pulse_train", 20): LEDS_10_OF_20,
    (3, "led_pulse_train", 10): EVEN_10,
    (3, "valve_pulse", 20): REFUSED,
    (4, "led_pulse", 20): LEDS_20_OF_20,
    (4, "led_pulse", 10): EVEN_10,
    (4, "led_pulse_train", 20): LEDS_20_OF_20,
    (4, "led_pulse_train", 10): EVEN_10,
    (4, "motor_pulse", 20): REFUSED,
    (4, "valve_pulse", 20): REFUSED,
}


def _connection(module):
    """A hardware connection to a module of the given firmware MODULE type."""
    name, capabilities = MODULES[module]
    hw = Mock()
    hw.interrogate.return_value = {
        "version": "FW-1.5;HW-11",
        "module": {"name": name, "type": module},
        "capabilities": dict(capabilities),
    }
    return hw


def _arena(n_rois):
    return [Mock(idx=i) for i in range(1, n_rois + 1)]


@pytest.mark.parametrize(
    "module,action_type,n_rois", sorted(EXPECTED), ids=lambda v: str(v)
)
def test_module_and_arena_pick_the_map(module, action_type, n_rois):
    expected = EXPECTED[(module, action_type, n_rois)]
    hw = _connection(module)

    if expected is REFUSED:
        with pytest.raises(ValueError, match="has no"):
            ComposedStimulator(hw, action_type=action_type)
        return

    stim = ComposedStimulator(hw, action_type=action_type)
    stim.bind_arena(_arena(n_rois))
    assert stim._roi_to_channel == expected


@pytest.mark.parametrize(
    "action_type,n_rois,expected",
    [
        ("motor_pulse", 20, MOTORS_20),
        ("motor_pulse", 10, MOTORS_10),
        ("led_pulse", 20, LEDS_10_OF_20),
        ("led_pulse", 10, EVEN_10),
        ("valve_pulse", 20, VALVES_20),
        ("valve_pulse", 10, EVEN_10),
    ],
)
def test_a_module_that_does_not_answer_gets_the_default_maps(
    action_type, n_rois, expected
):
    hw = Mock()
    hw.interrogate.return_value = {}
    stim = ComposedStimulator(hw, action_type=action_type)
    stim.bind_arena(_arena(n_rois))
    assert stim._roi_to_channel == expected


def test_before_the_arena_is_known_the_20_tube_layout_is_used():
    stim = ComposedStimulator(_connection(2), action_type="valve_pulse")
    assert stim._roi_to_channel == VALVES_20


def test_the_refusal_names_the_module_and_what_it_has():
    with pytest.raises(ValueError) as err:
        ComposedStimulator(_connection(4), action_type="motor_pulse")
    message = str(err.value)
    assert "LED Optogenetic Module" in message
    assert "motors" in message
    assert "20 LEDs" in message


# --- The maps are the legacy classes' maps ---


def test_20_tube_motors_are_mago_and_optomotor_motors():
    assert get_channel_map("motor") == mAGO._roi_to_channel_motor
    assert get_channel_map("motor") == OptomotorSleepDepriver._roi_to_channel_motor


def test_20_tube_valves_are_mago_valves():
    assert get_channel_map("valve", n_rois=20) == mAGO._roi_to_channel_valves


def test_20_tube_10_led_map_is_optomotor_leds():
    assert (
        get_channel_map("led", led_count=10, n_rois=20)
        == OptomotorSleepDepriver._roi_to_channel_led
    )


def test_10_tube_valves_are_ago_valves():
    assert get_channel_map("valve", n_rois=10) == AGO._roi_to_channel_valves


def test_10_tube_leds_are_opto_sleep_depriver_leds():
    assert (
        get_channel_map("led", led_count=20, n_rois=10)
        == OptoSleepDepriver._roi_to_channel
    )


def test_10_tube_motors_sit_beside_the_valve_connectors():
    # No legacy class drove motors on a 10-tube arena. Motor connector Mk
    # (channel 2k-1) sits next to Vk (channel 2k-2), so each ROI gets the motor
    # beside its valve/LED.
    valves = get_channel_map("valve", n_rois=10)
    motors = get_channel_map("motor", n_rois=10)
    assert motors == {roi: ch + 1 for roi, ch in valves.items()}


# --- The arena reaches the stimulators ---


def test_tracking_tells_every_stimulator_the_arena():
    rois = _arena(10)
    stimulators = ControlThread._build_stimulators(
        ControlThread,
        rois,
        _connection(2),
        ComposedStimulator,
        {"action_type": "valve_pulse"},
    )
    assert len(stimulators) == 10
    assert all(s._roi_to_channel == EVEN_10 for s in stimulators)


def test_tracking_refuses_a_stimulus_the_module_cannot_deliver():
    with pytest.raises(EthoscopeException, match="has no"):
        ControlThread._build_stimulators(
            ControlThread,
            _arena(20),
            _connection(4),
            ComposedStimulator,
            {"action_type": "motor_pulse"},
        )


def test_a_sequence_passes_the_arena_to_its_stimulators():
    sequence = [
        {
            "class_name": "ComposedStimulator",
            "arguments": {"action_type": "valve_pulse"},
            "date_range": "",
        }
    ]
    multi = MultiStimulator(_connection(2), stimulator_sequence=sequence)
    multi.bind_arena(_arena(10))
    assert multi._stimulators[0]["instance"]._roi_to_channel == EVEN_10
