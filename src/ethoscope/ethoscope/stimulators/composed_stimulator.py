"""
ComposedStimulator — configurable trigger + action stimulator.

Replaces the flat list of monolithic stimulator classes with a two-step
selection model: users choose a trigger condition (WHEN to stimulate) and
a stimulus action (WHAT to deliver), and this class wires them together.

All mAGO-based hardware uses the same OptoMotor interface; the channel
mapping is chosen automatically from the action's channel_type, what the
module reports it drives, and the arena's number of ROIs (channel_maps.py).
"""

import inspect
import logging

from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.stimulators.actions import ACTION_REGISTRY
from ethoscope.stimulators.channel_maps import get_channel_map
from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable
from ethoscope.stimulators.triggers import TRIGGER_REGISTRY, ScheduledTrigger

# The count, in the module's reply to T, of what each channel type drives.
_CAPABILITY_OF = {"motor": "motors", "led": "leds", "valve": "valves"}


def _module_capabilities(hardware_connection, action_type):
    """
    Read what the attached module drives, and check it can deliver the stimulus.

    Args:
        hardware_connection: The run's HardwareConnection.
        action_type (str): The stimulus, a key of ACTION_REGISTRY.

    Returns:
        dict: The counts the module reports, e.g. ``{"motors": 10, "valves": 0,
        "leds": 10}``; empty when the module did not answer, in which case the
        default maps are used.

    Raises:
        ValueError: If the module reports none of what the stimulus drives.
            Sent anyway, a motor pulse on an LED module lights the LEDs on the
            motor channels, and an LED pulse on a valve module opens valves.
    """
    try:
        reply = hardware_connection.interrogate()
    except Exception as e:
        logging.warning(f"Could not interrogate module: {e}. Using default maps.")
        return {}

    capabilities = reply.get("capabilities") if isinstance(reply, dict) else None
    if not isinstance(capabilities, dict):
        logging.warning(
            "The module did not report its capabilities. Using default maps."
        )
        return {}
    capabilities = {k: v for k, v in capabilities.items() if isinstance(v, int)}

    needed = _CAPABILITY_OF[ACTION_REGISTRY[action_type].channel_type]
    if capabilities.get(needed) == 0:
        module = reply.get("module")
        name = module.get("name") if isinstance(module, dict) else None
        raise ValueError(
            f"The attached module ({name or 'unnamed'}) has no {needed}, so it "
            f"cannot deliver a {action_type.replace('_', ' ')}. It drives "
            f"{capabilities.get('motors', 0)} motors, "
            f"{capabilities.get('valves', 0)} valves and "
            f"{capabilities.get('leds', 0)} LEDs."
        )

    logging.info(f"Module reports {capabilities}")
    return capabilities


class ComposedStimulator(BaseStimulator):
    """
    Configurable stimulator that composes a trigger condition with a stimulus action.

    This is the recommended stimulator for all mAGO-based hardware. Users select:
    1. A trigger condition (inactivity, activity, midline crossing, periodic)
    2. A stimulus action (motor pulse, LED pulse, LED pulse train, valve pulse)

    Any trigger can additionally be restricted to a recurring daily window by
    setting time_restricted, which wraps it in a ScheduledTrigger.

    The ComposedStimulator handles channel mapping automatically based on the
    selected action type, the attached module and the arena, and refuses a
    stimulus the module has nothing to deliver with.
    """

    _HardwareInterfaceClass = OptoMotor

    _description = {
        "overview": "Configurable stimulator: choose a trigger condition and stimulus action independently",
        "arguments": [
            # --- Trigger selection ---
            {
                "type": "select",
                "name": "trigger_type",
                "description": "What triggers the stimulus",
                "default": "inactivity",
                "options": [
                    {"value": "inactivity", "label": "Inactivity (sleep deprivation)"},
                    {"value": "activity", "label": "Activity (sustained movement)"},
                    {"value": "midline_crossing", "label": "Midline crossing"},
                    {"value": "periodic", "label": "Periodic (constitutive)"},
                ],
                "section": "Trigger",
            },
            # --- Trigger-specific arguments ---
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.0001,
                "name": "velocity_correction_coef",
                "description": "Velocity correction coefficient",
                "default": 3.0e-3,
                "depends_on": {
                    "trigger_type": ["inactivity", "activity", "time_restricted"],
                },
                "section": "Trigger",
            },
            {
                "type": "number",
                "min": 1,
                "max": 3600 * 12,
                "step": 1,
                "name": "min_inactive_time",
                "description": "Minimal inactivity time before stimulation (s)",
                "default": 120,
                "depends_on": {
                    "trigger_type": ["inactivity", "time_restricted"],
                },
                "section": "Trigger",
            },
            {
                "type": "number",
                "min": 10,
                "max": 3600,
                "step": 1,
                "name": "min_active_time",
                "description": "Activity window before stimulation (s)",
                "default": 120,
                "depends_on": {
                    "trigger_type": ["activity"],
                },
                "section": "Trigger",
            },
            {
                "type": "number",
                "min": 0.05,
                "max": 1.0,
                "step": 0.05,
                "name": "activity_threshold",
                "description": "Fraction of the window the animal must be active for",
                "default": 0.85,
                "depends_on": {
                    "trigger_type": ["activity"],
                },
                "section": "Trigger",
            },
            {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.01,
                "name": "stimulus_probability",
                "description": "Probability the stimulus will be delivered",
                "default": 1.0,
                "depends_on": {
                    "trigger_type": [
                        "inactivity",
                        "activity",
                        "midline_crossing",
                        "periodic",
                        "time_restricted",
                    ],
                },
                "section": "Trigger",
            },
            {
                "type": "number",
                "min": 1,
                "max": 3600,
                "step": 1,
                "name": "refractory_period_s",
                "description": "Minimum seconds between stimulations",
                "default": 60,
                "depends_on": {"trigger_type": ["midline_crossing"]},
                "section": "Trigger",
            },
            {
                "type": "number",
                "min": 1,
                "max": 86400,
                "step": 1,
                "name": "interval_seconds",
                "description": "Seconds between periodic stimulations",
                "default": 60,
                "depends_on": {"trigger_type": ["periodic"]},
                "section": "Trigger",
            },
            # --- Action selection ---
            {
                "type": "select",
                "name": "action_type",
                "description": "What stimulus to deliver",
                "default": "motor_pulse",
                "options": [
                    {"value": "motor_pulse", "label": "Motor pulse"},
                    {"value": "led_pulse", "label": "LED pulse"},
                    {"value": "led_pulse_train", "label": "LED pulse train"},
                    {"value": "valve_pulse", "label": "Valve/odour pulse"},
                ],
                "section": "Stimulus",
            },
            # --- Action-specific arguments ---
            {
                "type": "number",
                "min": 50,
                "max": 10000,
                "step": 50,
                "name": "pulse_duration",
                "description": "Pulse duration (ms)",
                "default": 1000,
                "depends_on": {
                    "action_type": ["motor_pulse", "led_pulse", "valve_pulse"],
                },
                "section": "Stimulus",
            },
            {
                "type": "number",
                "min": 10,
                "max": 10000,
                "step": 10,
                "name": "pulse_on_ms",
                "description": "LED ON duration per cycle (ms)",
                "default": 100,
                "depends_on": {"action_type": ["led_pulse_train"]},
                "section": "Stimulus",
            },
            {
                "type": "number",
                "min": 10,
                "max": 10000,
                "step": 10,
                "name": "pulse_off_ms",
                "description": "LED OFF duration per cycle (ms)",
                "default": 100,
                "depends_on": {"action_type": ["led_pulse_train"]},
                "section": "Stimulus",
            },
            {
                "type": "number",
                "min": 1,
                "max": 1000,
                "step": 1,
                "name": "pulse_cycles",
                "description": "Number of ON/OFF cycles",
                "default": 5,
                "depends_on": {"action_type": ["led_pulse_train"]},
                "section": "Stimulus",
            },
            # --- Timing: when the stimulator is live at all. Cross-cutting, so it
            #     comes last rather than sitting among the trigger's own settings. ---
            {
                "type": "date_range",
                "name": "date_range",
                "description": "Active time period",
                "default": "",
                "section": "Timing",
            },
            {
                "type": "boolean",
                "name": "time_restricted",
                "description": "Restrict stimulation to a daily time window",
                "default": False,
                "section": "Timing",
            },
            {
                "type": "number",
                "min": 1,
                "max": 24,
                "step": 0.5,
                "name": "daily_duration_hours",
                "description": "Hours active per day",
                "default": 8,
                "depends_on": {"time_restricted": [True]},
                "section": "Timing",
            },
            {
                "type": "number",
                "min": 1,
                "max": 168,
                "step": 0.5,
                "name": "interval_hours",
                "description": "Hours between active periods",
                "default": 24,
                "depends_on": {"time_restricted": [True]},
                "section": "Timing",
            },
            {
                "type": "str",
                "name": "daily_start_time",
                "description": "Daily start time (HH:MM:SS)",
                "default": "09:00:00",
                "depends_on": {"time_restricted": [True]},
                "section": "Timing",
            },
        ],
    }

    def __init__(
        self,
        hardware_connection,
        trigger_type="inactivity",
        action_type="motor_pulse",
        # Inactivity / activity trigger args
        velocity_correction_coef=3.0e-3,
        min_inactive_time=120,
        min_active_time=120,
        activity_threshold=0.85,
        stimulus_probability=1.0,
        # Midline crossing trigger args
        refractory_period_s=60,
        # Periodic trigger args
        interval_seconds=60,
        # Time restriction: applies to any trigger
        time_restricted=False,
        daily_duration_hours=8,
        interval_hours=24,
        daily_start_time="09:00:00",
        # Action args
        pulse_duration=1000,
        pulse_on_ms=100,
        pulse_off_ms=100,
        pulse_cycles=5,
        # Standard args
        date_range="",
        roi_template_config=None,
    ):
        trigger_cls = TRIGGER_REGISTRY.get(trigger_type)
        if trigger_cls is None:
            raise ValueError(
                f"Unknown trigger_type: {trigger_type!r}. "
                f"Options: {list(TRIGGER_REGISTRY.keys())}"
            )

        # Reason: dispatching on trigger_type with an if/elif chain fails open —
        # a trigger whose branch is missing would be built with all defaults and
        # silently discard the user's parameters. Matching against the trigger's
        # own signature instead means a new trigger wires itself up.
        candidate_args = {
            "velocity_correction_coef": velocity_correction_coef,
            "min_inactive_time": min_inactive_time,
            "min_active_time": min_active_time,
            "activity_threshold": activity_threshold,
            "stimulus_probability": stimulus_probability,
            "refractory_period_s": refractory_period_s,
            "interval_seconds": interval_seconds,
            "daily_duration_hours": daily_duration_hours,
            "interval_hours": interval_hours,
            "daily_start_time": daily_start_time,
        }
        accepted = inspect.signature(trigger_cls.__init__).parameters
        trigger_kwargs = {k: v for k, v in candidate_args.items() if k in accepted}

        self._trigger = trigger_cls(**trigger_kwargs)

        # Time restriction is a modifier, not a trigger: it wraps whatever was
        # selected. The deprecated "time_restricted" trigger_type already embeds
        # its own scheduler, so it must not be wrapped a second time.
        if time_restricted and trigger_type != "time_restricted":
            self._trigger = ScheduledTrigger(
                self._trigger,
                daily_duration_hours=daily_duration_hours,
                interval_hours=interval_hours,
                daily_start_time=daily_start_time,
            )

        # Build action
        action_cls = ACTION_REGISTRY.get(action_type)
        if action_cls is None:
            raise ValueError(
                f"Unknown action_type: {action_type!r}. "
                f"Options: {list(ACTION_REGISTRY.keys())}"
            )

        action_kwargs = {}
        if action_type in ("motor_pulse", "led_pulse", "valve_pulse"):
            action_kwargs = {"pulse_duration": pulse_duration}
        elif action_type == "led_pulse_train":
            action_kwargs = {
                "pulse_on_ms": pulse_on_ms,
                "pulse_off_ms": pulse_off_ms,
                "pulse_cycles": pulse_cycles,
            }

        self._action = action_cls(**action_kwargs)

        # The module's capabilities choose the channel map, and say whether it
        # can deliver this stimulus at all.
        self._capabilities = _module_capabilities(hardware_connection, action_type)

        # The arena is not known yet: until bind_arena(), the 20-tube layout.
        self._n_rois = None
        self._roi_to_channel = self._channel_map()

        logging.info(
            f"ComposedStimulator initialized: trigger={trigger_type}, "
            f"time_restricted={bool(time_restricted)}, action={action_type}, "
            f"channels={self._action.channel_type}, "
            f"mapped_rois={len(self._roi_to_channel)}"
        )

        super().__init__(hardware_connection, date_range, roi_template_config)

    def _channel_map(self):
        """Return the ROI-to-channel map for this stimulus, module and arena."""
        return get_channel_map(
            self._action.channel_type,
            led_count=self._capabilities.get("leds"),
            n_rois=self._n_rois,
        )

    def bind_arena(self, rois):
        """
        Choose the channel map for the arena's layout (10 or 20 tubes).

        Args:
            rois (list): The arena's ROIs.
        """
        self._n_rois = len(rois)
        self._roi_to_channel = self._channel_map()
        if self._n_rois not in (10, 20):
            logging.warning(
                f"No channel map is made for an arena of {self._n_rois} ROIs; "
                f"using the {'10' if self._n_rois <= 10 else '20'}-tube layout."
            )
        logging.info(
            f"ComposedStimulator: {self._action.channel_type} channels for "
            f"{self._n_rois} ROIs: {self._roi_to_channel}"
        )

    def bind_tracker(self, tracker):
        """Bind tracker to both the stimulator and the trigger."""
        super().bind_tracker(tracker)
        self._trigger.bind_tracker(tracker)

    def _decide(self):
        roi_id = self._tracker._roi.idx

        channel = self._roi_to_channel.get(roi_id)
        if channel is None:
            return HasInteractedVariable(False), {}

        interaction_code, _metadata = self._trigger.check()

        if interaction_code == 1:
            instruction = self._action.build_instruction(channel)
            logging.info(
                f"ComposedStimulator: stimulus on channel {channel} " f"(ROI {roi_id})"
            )
            return HasInteractedVariable(1), instruction
        elif interaction_code == 2:
            logging.info(f"ComposedStimulator: ghost stimulus (ROI {roi_id})")
            return HasInteractedVariable(2), {}

        return HasInteractedVariable(0), {}
