"""
Multi-stimulator system for sequential stimulator activation.
Allows multiple stimulators with individual date/time ranges within a single experiment.
"""

__author__ = "giorgio"

import logging

from ethoscope.hardware.interfaces.interfaces import DefaultInterface
from ethoscope.hardware.interfaces.optomotor import OptoMotor
from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable
from ethoscope.utils.scheduler import Scheduler

# Global flag to track if MultiStimulator has been logged before
_MULTISTIMULATOR_LOGGED = set()


class MultiStimulator(BaseStimulator):
    """
    A meta-stimulator that manages multiple stimulators with individual date/time ranges.
    Allows sequential activation of different stimulator types during an experiment.
    """

    _description = {
        "overview": "A meta-stimulator that manages multiple stimulators with individual date/time ranges",
        "hidden": True,
        "arguments": [
            {
                "type": "stimulator_sequence",
                "name": "stimulator_sequence",
                "description": "Sequence of stimulators with their configurations and date ranges",
                "default": [],
            }
        ],
    }

    # Reason: a run opens one hardware connection, from this attribute, before
    # the sequence is read, and every stimulator in the sequence shares it. It
    # must be the interface of the stimulators the node puts in a sequence
    # (ComposedStimulator); DefaultInterface's send() is a no-op, so with it no
    # stimulator in a sequence ever reached the module.
    _HardwareInterfaceClass = OptoMotor

    def __init__(
        self, hardware_connection, stimulator_sequence=None, roi_template_config=None
    ):
        """
        Initialize MultiStimulator with a sequence of stimulator configurations.

        Args:
            hardware_connection: The hardware interface connection
            stimulator_sequence: List of stimulator configurations, each containing:
                - class_name: Name of the stimulator class
                - arguments: Dictionary of arguments for the stimulator
                - date_range: Date/time range when this stimulator should be active
            roi_template_config: ROI template configuration
        """
        # Initialize with empty date_range since we manage our own scheduling
        super().__init__(
            hardware_connection, date_range="", roi_template_config=roi_template_config
        )

        self._stimulator_configs = stimulator_sequence or []
        self._active_stimulators = []
        self._hardware_connection = hardware_connection
        self._roi_template_config = roi_template_config
        self._stimulators = []
        self._initialized = False

        # Initialize all stimulators
        self._initialize_stimulators()

        # Track last active stimulator for logging
        self._last_active_stimulator = None

    def _initialize_stimulators(self):
        """
        Initialize all stimulators from the configuration sequence.
        """
        if self._initialized:
            logging.debug("Stimulators already initialized, skipping")
            return

        # Create a unique key for this configuration to prevent duplicate logging
        config_key = str(
            sorted(
                [
                    (c.get("class_name", ""), c.get("date_range", ""))
                    for c in self._stimulator_configs
                ]
            )
        )

        if config_key not in _MULTISTIMULATOR_LOGGED:
            logging.info(
                f"Initializing MultiStimulator with {len(self._stimulator_configs)} stimulator(s)"
            )
            _MULTISTIMULATOR_LOGGED.add(config_key)
        else:
            logging.debug(
                "MultiStimulator with same config already logged, creating instance silently"
            )

        # Reset stimulators list
        self._stimulators = []

        # Reason: a stimulator that is unknown or cannot be built raises rather
        # than being skipped. tracking.py turns the error into a refusal to start;
        # skipping it started a run that delivered less than the user asked for,
        # with only a log line to show for it.
        for config in self._stimulator_configs:
            class_name = config.get("class_name", "")
            arguments = config.get("arguments", {})
            date_range = config.get("date_range", "")

            StimulatorClass = self._stimulator_class(class_name)

            # Create stimulator instance with its specific date_range
            stimulator = StimulatorClass(
                hardware_connection=self._hardware_connection,
                date_range=date_range,
                roi_template_config=self._roi_template_config,
                **arguments,
            )

            self._stimulators.append(
                {
                    "instance": stimulator,
                    "class_name": class_name,
                    "date_range": date_range,
                    "scheduler": Scheduler(date_range),
                }
            )

            # Only log individual stimulator initialization if this is the first instance for this config
            if (
                config_key not in _MULTISTIMULATOR_LOGGED
                or len(_MULTISTIMULATOR_LOGGED) == 1
            ):
                logging.info(
                    f"Initialized stimulator {class_name} with date_range: {date_range}"
                )
            logging.debug(f"Stimulator config: {config}")

        self._initialized = True
        # Only log completion message for the first instance of this configuration
        if (
            config_key not in _MULTISTIMULATOR_LOGGED
            or len(_MULTISTIMULATOR_LOGGED) == 1
        ):
            logging.info(
                f"MultiStimulator initialization complete: {len(self._stimulators)} stimulator(s) ready"
            )

    def _stimulator_class(self, class_name):
        """
        Resolve a class named in the sequence.

        Args:
            class_name (str): The stimulator class name, as sent by the node.

        Returns:
            type: The stimulator class.

        Raises:
            ValueError: If the class is not a registered stimulator, is itself a
                MultiStimulator, or needs a hardware interface other than the
                connection the sequence shares.
        """
        # Reason: imported here, as the registry imports this module.
        from ethoscope.stimulators.registry import STIMULATOR_REGISTRY

        StimulatorClass = STIMULATOR_REGISTRY.get(class_name)
        if StimulatorClass is None or StimulatorClass is MultiStimulator:
            raise ValueError(f"Unknown stimulator class in sequence: {class_name!r}")

        # A stimulator that never delivers (DefaultInterface) fits any connection.
        interface = StimulatorClass._HardwareInterfaceClass
        if interface is not DefaultInterface and not issubclass(
            interface, self._HardwareInterfaceClass
        ):
            raise ValueError(
                f"{class_name} drives {interface.__name__}, but the stimulators "
                f"of a sequence share one {self._HardwareInterfaceClass.__name__} "
                f"connection"
            )
        return StimulatorClass

    def bind_tracker(self, tracker):
        """
        Bind tracker to all managed stimulators.

        Args:
            tracker: The tracker object to bind
        """
        super().bind_tracker(tracker)

        # Bind tracker to all individual stimulators
        for stimulator_info in self._stimulators:
            stimulator_info["instance"].bind_tracker(tracker)

    def bind_arena(self, rois):
        """
        Tell every stimulator of the sequence which ROIs the arena has.

        Args:
            rois (list): The arena's ROIs.
        """
        for stimulator_info in self._stimulators:
            stimulator_info["instance"].bind_arena(rois)

    def _decide(self):
        """
        Decide which stimulator(s) should be active and delegate to them.

        Returns:
            tuple: (interaction_result, result_dict)
        """
        if not self._stimulators:
            return HasInteractedVariable(False), {}

        # Find currently active stimulators based on their date ranges
        active_stimulators = []
        for stimulator_info in self._stimulators:
            if stimulator_info["scheduler"].check_time_range():
                active_stimulators.append(stimulator_info)

        # Log stimulator transitions
        current_active_names = [s["class_name"] for s in active_stimulators]
        if current_active_names != self._last_active_stimulator:
            if current_active_names:
                logging.info(f"Active stimulators: {', '.join(current_active_names)}")
            else:
                logging.info("No stimulators currently active")
            self._last_active_stimulator = current_active_names.copy()

        # If no stimulators are active, return no interaction
        if not active_stimulators:
            return HasInteractedVariable(False), {}

        # If multiple stimulators are active, use the first one (could be enhanced to support parallel execution)
        # For now, we implement a "first wins" policy when ranges overlap
        active_stimulator = active_stimulators[0]["instance"]

        # Delegate decision to the active stimulator
        try:
            interaction_result, result_dict = active_stimulator._decide()

            # Add metadata about which stimulator made the decision
            if isinstance(result_dict, dict):
                result_dict["active_stimulator"] = active_stimulators[0]["class_name"]

            return interaction_result, result_dict

        except Exception as e:
            logging.error(
                f"Error in stimulator {active_stimulators[0]['class_name']}: {e}"
            )
            return HasInteractedVariable(False), {}

    def _deliver(self, **kwargs):
        """
        Deliver stimulation using the hardware connection.

        Args:
            **kwargs: Arguments to pass to hardware interface
        """
        if self._hardware_connection is not None:
            # Remove metadata before sending to hardware
            hardware_kwargs = {
                k: v for k, v in kwargs.items() if k != "active_stimulator"
            }
            self._hardware_connection.send_instruction(hardware_kwargs)

    def get_active_stimulators(self):
        """
        Get list of currently active stimulator names.

        Returns:
            list: Names of currently active stimulators
        """
        active = []
        for stimulator_info in self._stimulators:
            if stimulator_info["scheduler"].check_time_range():
                active.append(stimulator_info["class_name"])
        return active

    def get_stimulator_info(self):
        """
        Get information about all configured stimulators.

        Returns:
            list: List of stimulator information dictionaries
        """
        info = []
        for stimulator_info in self._stimulators:
            info.append(
                {
                    "class_name": stimulator_info["class_name"],
                    "date_range": stimulator_info["date_range"],
                    "is_active": stimulator_info["scheduler"].check_time_range(),
                }
            )
        return info

    def get_stimulator_state(self, t=None):
        """
        Get state for MultiStimulator - delegates to active stimulator.

        Args:
            t: timestamp to check (None = current time)

        Returns:
            str: "inactive", "scheduled", or "stimulating"
        """
        # Find currently active stimulators
        active_stimulators = []
        for stimulator_info in self._stimulators:
            if stimulator_info["scheduler"].check_time_range(t):
                active_stimulators.append(stimulator_info)

        if not active_stimulators:
            return "inactive"

        # Use first active stimulator's state (follows same logic as _decide)
        return active_stimulators[0]["instance"].get_stimulator_state(t)
