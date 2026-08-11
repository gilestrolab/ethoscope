"""
ComposedStimulator — configurable trigger + action stimulator.

Replaces the flat list of monolithic stimulator classes with a two-step
selection model: users choose a trigger condition (WHEN to stimulate) and
a stimulus action (WHAT to deliver), and this class wires them together.

All mAGO-based hardware uses the same OptoMotor interface; the channel
mapping is derived automatically from the action's channel_type.
"""

import inspect
import logging

from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.stimulators.actions import ACTION_REGISTRY
from ethoscope.stimulators.channel_maps import get_channel_map
from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable
from ethoscope.stimulators.triggers import TRIGGER_REGISTRY, ScheduledTrigger


class ComposedStimulator(BaseStimulator):
    """
    Configurable stimulator that composes a trigger condition with a stimulus action.

    This is the recommended stimulator for all mAGO-based hardware. Users select:
    1. A trigger condition (inactivity, activity, midline crossing, periodic)
    2. A stimulus action (motor pulse, LED pulse, LED pulse train, valve pulse)

    Any trigger can additionally be restricted to a recurring daily window by
    setting time_restricted, which wraps it in a ScheduledTrigger.

    The ComposedStimulator handles channel mapping automatically based on the
    selected action type.
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

        # Interrogate module to get actual capabilities for channel map selection
        led_count = None
        try:
            module_info = hardware_connection.interrogate()
            led_count = module_info.get("capabilities", {}).get("leds")
            logging.info(
                f"Module reports {led_count} LEDs, "
                f"{module_info.get('capabilities', {}).get('motors')} motors"
            )
        except Exception as e:
            logging.warning(
                f"Could not interrogate module: {e}. Using default channel map."
            )

        # Derive channel map from action's channel type and module capabilities
        self._roi_to_channel = get_channel_map(
            self._action.channel_type, led_count=led_count
        )

        logging.info(
            f"ComposedStimulator initialized: trigger={trigger_type}, "
            f"time_restricted={bool(time_restricted)}, action={action_type}, "
            f"channels={self._action.channel_type}, "
            f"mapped_rois={len(self._roi_to_channel)}"
        )

        super().__init__(hardware_connection, date_range, roi_template_config)

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
