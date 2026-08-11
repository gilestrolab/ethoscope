"""
Trigger conditions for the ComposedStimulator.

Each trigger encapsulates the behavioral logic for deciding WHEN to stimulate,
independent of WHAT stimulus to deliver. Triggers are bound to a tracker and
called via check() to determine if a stimulus should fire.

Time restriction is not a trigger in its own right: ScheduledTrigger wraps any
other trigger and gates it to a recurring daily window, so it composes with all
current and future triggers.
"""

import collections
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


class MovementBoutTrigger(BaseTrigger):
    """
    Shared machinery for triggers that watch bouts of movement or stillness.

    Holds the per-frame movement test and the probability draw. The two
    polarities score bouts differently and so implement their own check():
    stillness is all-or-nothing (a sleeping animal really does produce no
    moving frame at all), whereas activity is graded — see ActivityTrigger.

    Movement logic extracted from IsMovingStimulator._has_moved() and
    SleepDepStimulator._decide().
    """

    def __init__(
        self,
        velocity_correction_coef=3.0e-3,
        stimulus_probability=1.0,
    ):
        super().__init__()
        self._velocity_correction_coef = float(velocity_correction_coef)

        p = float(stimulus_probability)
        if not 0 <= p <= 1.0:
            raise ValueError("Probability must be between 0.0 and 1.0")
        self._p = p

    def _draw(self):
        """Resolve a met condition into a real (1) or ghost (2) interaction."""
        if random.uniform(0, 1) <= self._p:
            return 1, {}
        return 2, {}

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


class InactivityTrigger(MovementBoutTrigger):
    """
    Fire when the animal is inactive for min_inactive_time seconds.

    All-or-nothing: a single moving frame restarts the clock. That is the
    established sleep-deprivation criterion and is left unchanged.
    """

    def __init__(
        self,
        velocity_correction_coef=3.0e-3,
        min_inactive_time=120,
        stimulus_probability=1.0,
    ):
        super().__init__(
            velocity_correction_coef=velocity_correction_coef,
            stimulus_probability=stimulus_probability,
        )
        self._bout_threshold_ms = float(min_inactive_time) * 1000
        self._t0 = None

    def check(self):
        now = self._tracker.last_time_point

        if self._t0 is None:
            self._t0 = now

        if not self._has_moved():
            if float(now - self._t0) > self._bout_threshold_ms:
                self._t0 = None
                return self._draw()
        else:
            # The bout was broken: restart the clock.
            self._t0 = now

        return 0, {}


class ActivityTrigger(MovementBoutTrigger):
    """
    Fire when the animal has been active for most of the last min_active_time
    seconds.

    Not the literal mirror of InactivityTrigger. Requiring *every* frame of the
    window to register as moving looks symmetric but is not: a sleeping animal
    genuinely produces no moving frame for minutes, whereas a walking animal
    dips below the velocity threshold constantly. Measured on 20 flies over
    three days, continuous 120 s movement bouts occur zero times, which is why
    that setting delivered no stimuli at all.

    Instead the window is cut into short bins, each scored active if the animal
    moved *at all* within it, and the trigger fires once at least
    activity_threshold of the bins are active. Binning is what keeps the rule
    independent of camera frame rate: "moved at all in 10 s" saturates, whereas
    a fraction-of-frames average concentrates towards the mean as the frame rate
    rises, so the same setting fired 14x less often at 4 fps than at 2.4 fps.
    It also reuses the criterion InactivityTrigger already applies, one bin wide.
    """

    # Aim for _TARGET_BINS bins per window, but never let a bin fall below
    # _MIN_BIN_S: below that it stops saturating and we are back to counting
    # frames. Windows shorter than ~60 s therefore get coarse threshold steps.
    _MIN_BIN_S = 5.0
    _MAX_BIN_S = 10.0
    _TARGET_BINS = 12

    def __init__(
        self,
        velocity_correction_coef=3.0e-3,
        min_active_time=120,
        activity_threshold=0.85,
        stimulus_probability=1.0,
    ):
        super().__init__(
            velocity_correction_coef=velocity_correction_coef,
            stimulus_probability=stimulus_probability,
        )

        window_s = float(min_active_time)
        if window_s <= 0:
            raise ValueError("min_active_time must be greater than 0")

        threshold = float(activity_threshold)
        if not 0 < threshold <= 1.0:
            raise ValueError("activity_threshold must be between 0.0 and 1.0")
        self._threshold = threshold

        bin_s = min(self._MAX_BIN_S, max(self._MIN_BIN_S, window_s / self._TARGET_BINS))
        self._n_bins = max(2, int(round(window_s / bin_s)))
        self._bin_ms = window_s * 1000.0 / self._n_bins

        self._bins = collections.deque(maxlen=self._n_bins)
        self._bin_start = None
        self._bin_active = False

    @property
    def _window_ms(self):
        return self._bin_ms * self._n_bins

    def check(self):
        now = self._tracker.last_time_point
        moved = self._has_moved()

        if self._bin_start is None:
            self._bin_start = now

        # A gap longer than the whole window leaves nothing worth keeping, and
        # bounds the loop below to _n_bins iterations.
        if now - self._bin_start > self._window_ms:
            self._bins.clear()
            self._bin_start = now
            self._bin_active = False

        # Close every bin the clock has moved past. A bin that saw no frame at
        # all — a tracking gap — closes inactive, which is the honest reading.
        while now - self._bin_start >= self._bin_ms:
            self._bins.append(self._bin_active)
            self._bin_start += self._bin_ms
            self._bin_active = False

        self._bin_active = self._bin_active or moved

        if len(self._bins) < self._n_bins:
            return 0, {}

        if sum(self._bins) / self._n_bins >= self._threshold:
            # Reason: demand a fresh window after firing, otherwise a long bout
            # re-fires on every subsequent frame.
            self._bins.clear()
            return self._draw()

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


class ScheduledTrigger(BaseTrigger):
    """
    Gate any trigger to a recurring daily window.

    Wraps an inner trigger and suppresses it outside the active period, so that
    time restriction composes with every trigger rather than being a trigger of
    its own.
    """

    def __init__(
        self,
        trigger,
        daily_duration_hours=8,
        interval_hours=24,
        daily_start_time="09:00:00",
    ):
        super().__init__()
        self._trigger = trigger

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
        self._trigger.bind_tracker(tracker)

    def check(self):
        if not self._daily_scheduler.is_active_period():
            return 0, {}

        return self._trigger.check()


class TimeRestrictedInactivityTrigger(ScheduledTrigger):
    """
    Deprecated: an InactivityTrigger pre-wrapped in a daily schedule.

    Kept so that configurations saved with trigger_type="time_restricted" keep
    working. New configurations should pick any trigger and set time_restricted.
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
        super().__init__(
            InactivityTrigger(
                velocity_correction_coef=velocity_correction_coef,
                min_inactive_time=min_inactive_time,
                stimulus_probability=stimulus_probability,
            ),
            daily_duration_hours=daily_duration_hours,
            interval_hours=interval_hours,
            daily_start_time=daily_start_time,
        )


# Registry mapping trigger_type string values to classes
TRIGGER_REGISTRY = {
    "inactivity": InactivityTrigger,
    "activity": ActivityTrigger,
    "midline_crossing": MidlineCrossingTrigger,
    "periodic": PeriodicTrigger,
    # Deprecated: superseded by the time_restricted modifier on any trigger.
    "time_restricted": TimeRestrictedInactivityTrigger,
}
