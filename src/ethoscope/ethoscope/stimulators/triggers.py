"""
Trigger conditions for the ComposedStimulator.

Each trigger encapsulates the behavioral logic for deciding WHEN to stimulate,
independent of WHAT stimulus to deliver. Triggers are bound to a tracker and
called via check() to determine if a stimulus should fire.
"""

import logging
import random

from ethoscope.utils.scheduler import DailyScheduleError, DailyScheduler


class BaseTrigger:
    """Abstract trigger condition for ComposedStimulator."""

    _description = {}

    def __init__(self):
        self._tracker = None

    def bind_tracker(self, tracker):
        """Bind a tracker to this trigger for accessing animal position data."""
        self._tracker = tracker

    def check(self):
        """
        Evaluate the trigger condition.

        Returns:
            tuple: (interaction_code, metadata) where interaction_code is:
                0 = no trigger
                1 = real trigger (should deliver stimulus)
                2 = ghost trigger (decision made but no delivery, for controls)
        """
        raise NotImplementedError


class InactivityTrigger(BaseTrigger):
    """
    Fire when animal is inactive for min_inactive_time seconds.

    Logic extracted from IsMovingStimulator._has_moved() and SleepDepStimulator._decide().
    """

    def __init__(
        self,
        velocity_correction_coef=3.0e-3,
        min_inactive_time=120,
        stimulus_probability=1.0,
    ):
        super().__init__()
        self._velocity_correction_coef = float(velocity_correction_coef)
        self._inactivity_time_threshold_ms = float(min_inactive_time) * 1000
        self._t0 = None

        p = float(stimulus_probability)
        if not 0 <= p <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        self._p = p

    def _has_moved(self):
        """Check if the animal has moved. Extracted from IsMovingStimulator."""
        positions = self._tracker.positions

        if len(positions) < 2:
            return False

        if len(positions[-1]) != 1:
            raise Exception(
                "This stimulator can only work with a single animal per ROI"
            )
        tail_m = positions[-1][0]

        times = self._tracker.times
        last_time_for_position = times[-1]
        last_time = self._tracker.last_time_point

        # Assume no movement if the animal was not spotted
        if last_time != last_time_for_position:
            return False

        dt_s = abs(times[-1] - times[-2]) / 1000.0
        dist = 10.0 ** (tail_m["xy_dist_log10x1000"] / 1000.0)
        velocity = dist / dt_s

        velocity_corrected = velocity * dt_s / self._velocity_correction_coef

        if velocity_corrected > 1.0:
            return True
        return False

    def check(self):
        now = self._tracker.last_time_point
        has_moved = self._has_moved()

        if self._t0 is None:
            self._t0 = now

        if not has_moved:
            if float(now - self._t0) > self._inactivity_time_threshold_ms:
                if random.uniform(0, 1) <= self._p:
                    self._t0 = None
                    return 1, {}
                else:
                    self._t0 = None
                    return 2, {}
        else:
            self._t0 = now

        return 0, {}


class MidlineCrossingTrigger(BaseTrigger):
    """
    Fire when animal crosses the ROI midline.

    Logic extracted from MiddleCrossingStimulator._decide().
    """

    def __init__(self, stimulus_probability=1.0, refractory_period_s=60):
        super().__init__()
        self._refractory_period_ms = float(refractory_period_s) * 1000
        self._last_stimulus_time = 0

        p = float(stimulus_probability)
        if not 0 <= p <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        self._p = p

    def check(self):
        now = self._tracker.last_time_point

        if now - self._last_stimulus_time < self._refractory_period_ms:
            return 0, {}

        positions = self._tracker.positions

        if len(positions) < 2:
            return 0, {}

        if len(positions[-1]) != 1:
            raise Exception(
                "This stimulator can only work with a single animal per ROI"
            )

        roi_w = float(self._tracker._roi.longest_axis)
        x_t_zero = positions[-1][0]["x"] / roi_w - 0.5
        x_t_minus_one = positions[-2][0]["x"] / roi_w - 0.5

        # XOR detects sign change = midline crossing
        if (x_t_zero > 0) ^ (x_t_minus_one > 0):
            if random.uniform(0, 1) < self._p:
                self._last_stimulus_time = now
                return 1, {}
            else:
                self._last_stimulus_time = now
                return 2, {}

        return 0, {}


class PeriodicTrigger(BaseTrigger):
    """
    Fire at regular intervals regardless of behavior.

    Useful for constitutive optogenetic protocols.
    """

    def __init__(self, interval_seconds=60, stimulus_probability=1.0):
        super().__init__()
        self._interval_ms = float(interval_seconds) * 1000
        self._last_fire_time = 0

        p = float(stimulus_probability)
        if not 0 <= p <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        self._p = p

    def check(self):
        now = self._tracker.last_time_point

        if now - self._last_fire_time >= self._interval_ms:
            self._last_fire_time = now
            if random.uniform(0, 1) <= self._p:
                return 1, {}
            else:
                return 2, {}

        return 0, {}


class TimeRestrictedInactivityTrigger(BaseTrigger):
    """
    Inactivity trigger that only operates during specified daily windows.

    Combines InactivityTrigger logic with DailyScheduler for sleep restriction.
    """

    def __init__(
        self,
        velocity_correction_coef=3.0e-3,
        min_inactive_time=120,
        stimulus_probability=1.0,
        daily_duration_hours=8,
        interval_hours=24,
        daily_start_time="09:00:00",
    ):
        super().__init__()
        self._inactivity_trigger = InactivityTrigger(
            velocity_correction_coef=velocity_correction_coef,
            min_inactive_time=min_inactive_time,
            stimulus_probability=stimulus_probability,
        )

        try:
            self._daily_scheduler = DailyScheduler(
                daily_duration_hours=daily_duration_hours,
                interval_hours=interval_hours,
                daily_start_time=daily_start_time,
            )
        except DailyScheduleError as e:
            logging.error(f"Invalid daily schedule configuration: {e}")
            raise

    def bind_tracker(self, tracker):
        super().bind_tracker(tracker)
        self._inactivity_trigger.bind_tracker(tracker)

    def check(self):
        if not self._daily_scheduler.is_active_period():
            return 0, {}

        return self._inactivity_trigger.check()


# Registry mapping trigger_type string values to classes
TRIGGER_REGISTRY = {
    "inactivity": InactivityTrigger,
    "midline_crossing": MidlineCrossingTrigger,
    "periodic": PeriodicTrigger,
    "time_restricted": TimeRestrictedInactivityTrigger,
}
