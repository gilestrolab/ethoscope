__author__ = "quentin"

import time
from ethoscope.utils.description import DescribedObject
from ethoscope.core.variables import BaseIntVariable
from ethoscope.hardware.interfaces.interfaces import DefaultInterface
from ethoscope.utils.scheduler import Scheduler


class HasInteractedVariable(BaseIntVariable):
    """
    Custom variable to save whether the stimulator has sent instruction to its hardware interface. 0 means
     no interaction. Any positive integer describes a different interaction.
    """

    functional_type = "interaction"
    header_name = "has_interacted"


class BaseStimulator(DescribedObject):
    _tracker = None
    _HardwareInterfaceClass = None

    def __init__(self, hardware_connection, date_range="", roi_template_config=None):
        """
        Template class to interact with the tracked animal in a real-time feedback loop.
        Derived classes must have an attribute ``_hardwareInterfaceClass`` defining the class of the
        :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface` object (not on object) that instances will
        share with one another. In addition, they must implement a ``_decide()`` method.

        :param hardware_connection: The hardware interface to use.
        :type hardware_connection: :class:`~ethoscope.hardware.interfaces.interfaces.BaseInterface`
        :param date_range: the start and stop date/time for the stimulator. Format described `here <https://github.com/gilestrolab/ethoscope/blob/master/user_manual/schedulers.md>`_
        :type date_range: str
        :param roi_template_config: ROI template configuration containing stimulator compatibility and mappings
        :type roi_template_config: dict

        """

        self._scheduler = Scheduler(date_range)
        self._hardware_connection = hardware_connection
        self._roi_template_config = roi_template_config

        # Apply template overrides for ROI-to-channel mappings if available
        self._apply_template_overrides()

    def apply(self):
        """
        Apply this stimulator. This method will:

        1. check ``_tracker`` exists
        2. decide (``_decide``) whether to interact
        3. if 2. pass the interaction arguments to the hardware interface

        :return: whether a stimulator has worked, and a result dictionary
        """
        if self._tracker is None:
            raise ValueError(
                "No tracker bound to this stimulator. Use `bind_tracker()` methods"
            )

        current_time = (
            time.time() * 1000
        )  # Convert to ms for consistency with tracker timestamps

        if self._scheduler.check_time_range() is False:
            self._track_interaction_state(False, current_time)
            return HasInteractedVariable(False), {}

        interact, result = self._decide()

        # Track interaction state for visual feedback
        self._track_interaction_state(interact, current_time)

        if interact > 0:
            self._deliver(**result)

        return interact, result

    def bind_tracker(self, tracker):
        """
        Link a tracker to this interactor

        :param tracker: a tracker object.
        :type tracker: :class:`~ethoscope.trackers.trackers.BaseTracker`
        """
        self._tracker = tracker

    def _decide(self):
        raise NotImplementedError

    def _deliver(self, **kwargs):
        if self._hardware_connection is not None:
            self._hardware_connection.send_instruction(kwargs)

    def get_stimulator_state(self, t=None):
        """
        Get comprehensive stimulator state combining schedule and interaction status.
        :param t: timestamp to check (None = current time)
        :return: "inactive", "scheduled", or "stimulating"
        :rtype: str
        """
        # First check scheduler state
        schedule_state = self._scheduler.get_schedule_state(t)
        if schedule_state == "inactive":
            return "inactive"

        # If scheduled, check if currently stimulating
        if hasattr(self, "_last_interaction_time") and hasattr(
            self, "_last_interaction_value"
        ):
            # Check if recent interaction occurred (within last few seconds)
            current_time = t if t is not None else time.time() * 1000  # Convert to ms
            time_since_interaction = current_time - self._last_interaction_time

            # Consider "stimulating" if interaction happened in last 2 seconds
            if time_since_interaction < 2000 and self._last_interaction_value > 0:
                return "stimulating"

        return "scheduled"

    def _track_interaction_state(self, interact, current_time):
        """
        Internal method to track interaction timing for state determination.
        Called from apply() method.
        :param interact: interaction result from _decide()
        :param current_time: current timestamp in milliseconds
        """
        self._last_interaction_time = current_time
        self._last_interaction_value = int(interact) if interact else 0

    def _apply_template_overrides(self):
        """
        Apply ROI template overrides for stimulator mappings if available.
        This allows templates to override default ROI-to-channel mappings.
        """
        if not self._roi_template_config:
            return

        stimulator_compatibility = self._roi_template_config.get(
            "stimulator_compatibility", {}
        )
        roi_mappings = stimulator_compatibility.get("roi_mappings", {})

        # Get the class name of this stimulator
        stimulator_class = self.__class__.__name__

        # Check if there's a specific mapping for this stimulator
        if stimulator_class in roi_mappings:
            mapping_config = roi_mappings[stimulator_class]

            # Handle complex mappings (like mAGO with motor/valve channels)
            if isinstance(mapping_config, dict):
                if "motor_channels" in mapping_config:
                    # Convert string keys to integers for motor channels
                    self._roi_to_channel_motor = {
                        int(k): v for k, v in mapping_config["motor_channels"].items()
                    }

                if "valve_channels" in mapping_config:
                    # Convert string keys to integers for valve channels
                    self._roi_to_channel_valves = {
                        int(k): v for k, v in mapping_config["valve_channels"].items()
                    }

                # If it's a simple mapping (direct ROI to channel)
                if not (
                    "motor_channels" in mapping_config
                    or "valve_channels" in mapping_config
                ):
                    # Convert string keys to integers for simple mapping
                    self._roi_to_channel = {
                        int(k): v for k, v in mapping_config.items()
                    }

        # Fallback to default mapping if stimulator not found but default exists
        elif "default" in roi_mappings:
            default_mapping = roi_mappings["default"]
            # Convert string keys to integers for default mapping
            self._roi_to_channel = {int(k): v for k, v in default_mapping.items()}


class DefaultStimulator(BaseStimulator):
    """
    Default interactor. Simply never interacts
    """

    _description = {
        "overview": "The default 'interactor'. To use when no hardware interface is to be used.",
        "arguments": [],
    }
    _HardwareInterfaceClass = DefaultInterface

    def _decide(self):
        out = HasInteractedVariable(False)
        return out, {}
