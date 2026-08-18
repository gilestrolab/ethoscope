import datetime
import json
import logging
import os
import re
import time

from ethoscope.utils.description import DescribedObject


class DateRangeError(Exception):
    pass


class DailyScheduleError(Exception):
    pass


class TimedStopError(Exception):
    pass


class Scheduler:
    def __init__(self, in_str):
        """
        Class to express time constrains.
        It parses a formated string to define a list of allowed time range.
        Then it can be used to assess if a date and time is within a valid range.
        This is useful to control stimulators and other utilities.

        :param in_str: A formatted string. Format described `here <https://github.com/gilestrolab/ethoscope/blob/master/user_manual/schedulers.md>`_
        :type in_str: str
        """
        date_range_str = in_str.split(",")
        self._date_ranges = []
        for drs in date_range_str:
            dr = self._parse_date_range(drs)

            self._date_ranges.append(dr)
        self._check_date_ranges(self._date_ranges)

    def _check_date_ranges(self, ranges):
        all_dates = []
        for start, end in ranges:
            all_dates.append(start)
            all_dates.append(end)

        for i in range(0, len(all_dates) - 1):
            if (all_dates[i + 1] - all_dates[i]) <= 0:
                raise DateRangeError("Some date ranges overlap")
        pass

    def check_time_range(self, t=None):
        """
        Check whether a unix timestamp is within the allowed range.
        :param t: the time to test. When ``None``, the system time is used
        :type t: float
        :return: ``True`` if the time was in range, ``False`` otherwise
        :rtype: bool
        """
        if t is None:
            t = time.time()
        return self._in_range(t)

    def get_schedule_state(self, t=None):
        """
        Get the current scheduling state for visual feedback.
        :param t: the time to test. When ``None``, the system time is used
        :type t: float
        :return: ``"scheduled"`` if within range, ``"inactive"`` if outside range
        :rtype: str
        """
        if t is None:
            t = time.time()
        return "scheduled" if self._in_range(t) else "inactive"

    def _in_range(self, t):
        for r in self._date_ranges:
            if r[1] > t > r[0]:
                return True
        return False

    def _parse_date_range(self, date_range_str):
        self._start_date = 0
        self._stop_date = float("inf")
        dates = re.split(r"\s*>\s*", date_range_str)

        if len(dates) > 2:
            raise DateRangeError(" found several '>' symbol. Only one is allowed")
        date_strs = []
        for d in dates:
            date_strs.append(self._parse_date(d))

        if len(date_strs) == 1:
            # start_date
            if date_strs[0] is None:
                out = (0, float("inf"))
            else:
                out = (date_strs[0], float("inf"))

        elif len(date_strs) == 2:
            d1, d2 = date_strs
            if d1 is None:
                if d2 is None:
                    raise DateRangeError("Data range cannot inclue two None dates")
                out = (0, d2)
            elif d2 is None:
                out = (d1, float("inf"))
            else:
                out = (d1, d2)
        else:
            raise Exception("Unexpected date string")
        if out[0] >= out[1]:
            raise DateRangeError(
                f"Error in date {date_range_str}, the end date appears to be in the past"
            )
        return out

    def _parse_date(self, date_str):
        pattern = re.compile(
            r"^\s*(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\s*$"
        )
        if re.match(r"^\s*$", date_str):
            return None
        if not re.match(pattern, date_str):
            raise DateRangeError(f"{date_str} not match the expected pattern")
        datestr = re.match(pattern, date_str).groupdict()["date"]
        try:
            return time.mktime(
                datetime.datetime.strptime(datestr, "%Y-%m-%d %H:%M:%S").timetuple()
            )
        except (ValueError, OverflowError) as e:
            raise DateRangeError(f"Invalid date format: {datestr} ({str(e)})") from e


class DailyScheduler:
    """
    Enhanced scheduler for daily time-restricted operations.

    This scheduler supports operations that run for N hours per day at specified intervals,
    designed for sleep restriction experiments that inherit from mAGO stimulators.
    """

    def __init__(
        self,
        daily_duration_hours,
        interval_hours=24,
        daily_start_time="00:00:00",
        state_file_path=None,
    ):
        """
        Initialize daily scheduler for time-restricted operations.

        Args:
            daily_duration_hours (float): Total hours active per day
            interval_hours (float): Hours between the start of active periods
            daily_start_time (str): Daily start time in HH:MM:SS format
            state_file_path (str): Path to state persistence file (optional)

        Example:
            # 8 hours active every 24 hours starting at 9 AM
            DailyScheduler(8, 24, "09:00:00")

            # 4 hours active every 12 hours (twice daily) starting at 6 AM
            DailyScheduler(4, 12, "06:00:00")
        """
        if daily_duration_hours <= 0 or daily_duration_hours > 24:
            raise DailyScheduleError("daily_duration_hours must be between 0 and 24")

        if interval_hours <= 0 or interval_hours > 168:  # Max 1 week
            raise DailyScheduleError("interval_hours must be between 0 and 168")

        if daily_duration_hours > interval_hours:
            raise DailyScheduleError(
                "daily_duration_hours cannot exceed interval_hours"
            )

        self._daily_duration_hours = daily_duration_hours
        self._interval_hours = interval_hours
        self._daily_start_time = daily_start_time
        self._state_file_path = state_file_path

        # Parse start time
        self._start_time_seconds = self._parse_time_string(daily_start_time)

        # State tracking
        self._state = self._load_state() if state_file_path else {}

        logging.info(
            f"DailyScheduler initialized: {daily_duration_hours}h active every {interval_hours}h starting at {daily_start_time}"
        )

    def _parse_time_string(self, time_str):
        """
        Parse time string in HH:MM:SS format to seconds since midnight.

        Args:
            time_str (str): Time in HH:MM:SS format

        Returns:
            int: Seconds since midnight
        """
        try:
            time_obj = datetime.time.fromisoformat(time_str)
            return time_obj.hour * 3600 + time_obj.minute * 60 + time_obj.second
        except ValueError as e:
            raise DailyScheduleError(
                f"Invalid time format: {time_str}. Expected HH:MM:SS"
            ) from e

    def _daily_start_timestamp(self, t):
        """
        The configured start time, as a timestamp, on the local day holding `t`.

        Anchored to the LOCAL wall clock. Reason: this used to be computed as
        `int(t // 86400) * 86400 + start_seconds`, which counts days from the
        UTC epoch — so "09:00:00" was applied as 09:00 UTC and an experiment
        configured for 09:00 in London actually ran 10:00-18:00 through BST.
        Building a local datetime rather than adding seconds to midnight also
        keeps the start at 09:00 on the 23 h and 25 h days DST produces.

        Args:
            t (float): Unix timestamp identifying the day.

        Returns:
            float: Unix timestamp of the daily start time on that day.
        """
        dt = datetime.datetime.fromtimestamp(t)
        return dt.replace(
            hour=self._start_time_seconds // 3600,
            minute=(self._start_time_seconds % 3600) // 60,
            second=self._start_time_seconds % 60,
            microsecond=0,
        ).timestamp()

    def _load_state(self):
        """Load scheduler state from file."""
        if not self._state_file_path or not os.path.exists(self._state_file_path):
            return {}

        try:
            with open(self._state_file_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logging.warning(f"Could not load scheduler state: {e}")
            return {}

    def _save_state(self):
        """Save scheduler state to file."""
        if not self._state_file_path:
            return

        try:
            os.makedirs(os.path.dirname(self._state_file_path), exist_ok=True)
            with open(self._state_file_path, "w") as f:
                json.dump(self._state, f, indent=2)
        except OSError as e:
            logging.error(f"Could not save scheduler state: {e}")

    def is_active_period(self, t=None):
        """
        Check if current time is within an active period.

        Args:
            t (float): Unix timestamp to check. If None, uses current time.

        Returns:
            bool: True if within active period, False otherwise
        """
        if t is None:
            t = time.time()

        start_timestamp = self._daily_start_timestamp(t)

        # Handle interval periods (multiple periods per day or multi-day intervals)
        interval_seconds = self._interval_hours * 3600
        active_seconds = self._daily_duration_hours * 3600

        # Find the most recent period start
        periods_since_start = int((t - start_timestamp) // interval_seconds)
        if t < start_timestamp:
            periods_since_start = -1

        current_period_start = start_timestamp + (
            periods_since_start * interval_seconds
        )
        current_period_end = current_period_start + active_seconds

        # Check if we're in the active window
        is_active = current_period_start <= t < current_period_end

        # Update state tracking
        if is_active and self._state_file_path:
            period_key = f"period_{int(current_period_start)}"
            if period_key not in self._state:
                self._state[period_key] = {
                    "start_time": current_period_start,
                    "end_time": current_period_end,
                    "first_activity": t,
                }
                self._save_state()

        return is_active

    def get_next_active_period(self, t=None):
        """
        Get the start and end times of the next active period.

        Args:
            t (float): Reference timestamp. If None, uses current time.

        Returns:
            tuple: (start_timestamp, end_timestamp) of next active period
        """
        if t is None:
            t = time.time()

        start_timestamp = self._daily_start_timestamp(t)

        interval_seconds = self._interval_hours * 3600
        active_seconds = self._daily_duration_hours * 3600

        # Find next period start
        if t >= start_timestamp:
            periods_passed = int((t - start_timestamp) // interval_seconds) + 1
            next_start = start_timestamp + (periods_passed * interval_seconds)
        else:
            next_start = start_timestamp

        next_end = next_start + active_seconds

        return (next_start, next_end)

    def get_time_until_next_period(self, t=None):
        """
        Get seconds until next active period starts.

        Args:
            t (float): Reference timestamp. If None, uses current time.

        Returns:
            float: Seconds until next active period
        """
        if t is None:
            t = time.time()

        next_start, _ = self.get_next_active_period(t)
        return max(0, next_start - t)

    def get_remaining_active_time(self, t=None):
        """
        Get remaining seconds in current active period.

        Args:
            t (float): Reference timestamp. If None, uses current time.

        Returns:
            float: Remaining seconds in active period, 0 if not active
        """
        if not self.is_active_period(t):
            return 0

        if t is None:
            t = time.time()

        start_timestamp = self._daily_start_timestamp(t)

        interval_seconds = self._interval_hours * 3600
        active_seconds = self._daily_duration_hours * 3600

        periods_since_start = int((t - start_timestamp) // interval_seconds)
        current_period_start = start_timestamp + (
            periods_since_start * interval_seconds
        )
        current_period_end = current_period_start + active_seconds

        return max(0, current_period_end - t)

    def get_schedule_info(self):
        """
        Get human-readable schedule information.

        Returns:
            dict: Schedule configuration and status
        """
        now = time.time()
        is_active = self.is_active_period(now)

        info = {
            "daily_duration_hours": self._daily_duration_hours,
            "interval_hours": self._interval_hours,
            "daily_start_time": self._daily_start_time,
            "currently_active": is_active,
        }

        if is_active:
            info["remaining_active_seconds"] = self.get_remaining_active_time(now)
        else:
            info["seconds_until_next_period"] = self.get_time_until_next_period(now)

        next_start, next_end = self.get_next_active_period(now)
        info["next_period_start"] = datetime.datetime.fromtimestamp(
            next_start
        ).isoformat()
        info["next_period_end"] = datetime.datetime.fromtimestamp(next_end).isoformat()

        return info


def format_countdown(seconds):
    """
    Render a number of seconds as the ``DD:HH:MM`` string the web interface shows.

    Sub-minute remainders are truncated rather than rounded: the string is a
    "time left" readout, and rounding up would let it claim a minute that has
    already gone.

    Args:
        seconds (float): A duration in seconds. Negative values clamp to zero.

    Returns:
        str: The duration as ``DD:HH:MM``.
    """
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return f"{days:02d}:{hours:02d}:{minutes:02d}"


class TimedStop(DescribedObject):
    """
    When an experiment should stop by itself.

    Accepts either a duration to run for or an absolute date and time to stop at,
    and resolves whichever was given into a single absolute unix timestamp. That
    timestamp is the only thing the control threads act on, which is what lets a
    scheduled stop survive the clock corrections the node pushes to devices: the
    supervisor compares the wall clock against a target rather than sleeping out
    a countdown fixed at the moment the experiment started.

    Used by both tracking and video recording (see
    :class:`~ethoscope.control.tracking.ControlThread`).
    """

    _description = {
        "overview": "Stop the experiment automatically, so it does not have to be "
        "stopped by hand.",
        "arguments": [
            {
                # The two ways of saying when are mutually exclusive, so the form asks
                # which one first and shows only that. Answering both was possible
                # before, and the rule for resolving it - the date wins - was written
                # down in the overview where nobody had to read it.
                "type": "dropdown",
                "name": "mode",
                "description": "Automatic stop",
                # The three arguments answer one question, so they share a row. The
                # dropdown and the boxes say what they are on their own - "Run for a
                # fixed time", then days/hours/minutes - so the headings above them were
                # only costing a second row, and the icon carries the meaning instead.
                "icon": "fa-hourglass-half",
                "inline": True,
                "options": [
                    {"value": "never", "text": "Do not stop automatically"},
                    {"value": "duration", "text": "Run for a fixed time"},
                    {"value": "datetime", "text": "Stop at a date and time"},
                ],
                "default": "never",
            },
            {
                "type": "duration",
                "name": "run_for",
                "description": "",
                "inline": True,
                "default": {"days": 0, "hours": 0, "minutes": 0},
                "depends_on": {"mode": ["duration"]},
            },
            {
                "type": "datetime",
                "name": "stop_at",
                "description": "",
                "inline": True,
                "default": "",
                "depends_on": {"mode": ["datetime"]},
            },
        ],
    }

    #: Accepted values of ``mode``.
    MODES = ("never", "duration", "datetime")

    def __init__(
        self,
        mode=None,
        run_for=None,
        days=0,
        hours=0,
        minutes=0,
        stop_at="",
        duration=None,
        timer=None,
    ):
        """
        Args:
            mode (str): Which of the two ways of saying when to use - ``"never"``,
                ``"duration"`` or ``"datetime"``. This is what the form sends. When it
                is absent, as it is for a saved configuration or an API call giving
                just the one field, whichever field was filled in is used, and an
                absolute time wins over a duration.
            run_for (dict): ``{"days": d, "hours": h, "minutes": m}``, as the web form
                sends it. Any key present overrides the matching argument below.
            days (int): Whole days to run for. The flat form, which reads better when
                driving the API directly - ``{"days": 2}``.
            hours (int): Hours to run for, on top of the days.
            minutes (int): Minutes to run for, on top of the days and hours.
            stop_at (str|float): An absolute stop time, either a unix timestamp or a
                ``YYYY-MM-DD HH:MM`` string read in the device's local time.
            duration (str): Deprecated ``DD:HH:MM`` string. Kept so experiment
                configurations saved by earlier versions still start.
            timer (str): Deprecated alias for ``duration``, under its even earlier name.

        Raises:
            TimedStopError: If any field is malformed, or if a mode was chosen and the
                field it asks for was left empty.
        """
        if mode is not None and mode not in self.MODES:
            raise TimedStopError(f"{mode!r} is not one of {', '.join(self.MODES)}")

        self.mode = mode

        legacy = timer if timer is not None else duration
        if legacy is not None:
            # An old saved configuration. The packed DD:HH:MM string is ambiguous when
            # a field is out of range, so it keeps its stricter parse; the numeric
            # fields below simply add up.
            self._countdown = self._parse_duration(legacy)
            self.days, self.hours, self.minutes = 0, 0, 0
        else:
            if isinstance(run_for, dict):
                days = run_for.get("days", days)
                hours = run_for.get("hours", hours)
                minutes = run_for.get("minutes", minutes)

            self.days = self._whole_number(days, "days")
            self.hours = self._whole_number(hours, "hours")
            self.minutes = self._whole_number(minutes, "minutes")
            self._countdown = self.days * 86400 + self.hours * 3600 + self.minutes * 60

        self.duration = legacy
        self.stop_at = stop_at
        self._absolute = self._parse_stop_at(stop_at)

        # A chosen mode is honoured exactly, so the field belonging to the other one
        # cannot quietly take effect - not from a stale form value, and not from a
        # saved configuration carrying both.
        if mode == "never":
            self._countdown, self._absolute = 0, None
        elif mode == "duration":
            self._absolute = None
            if self._countdown <= 0:
                raise TimedStopError(
                    "Say how long to run for, or set the automatic stop to "
                    "'Do not stop automatically'"
                )
        elif mode == "datetime":
            self._countdown = 0
            if self._absolute is None:
                raise TimedStopError(
                    "Choose a stop date and time, or set the automatic stop to "
                    "'Do not stop automatically'"
                )

        # Reason: an experiment that is not meant to stop by itself is the common
        # case, so it must be reachable by leaving the form alone.
        self.autostop = self._absolute is not None or self._countdown > 0

    @staticmethod
    def _whole_number(value, field):
        """
        Read one of the duration fields.

        The fields are summed rather than range-checked: three separately labelled
        boxes cannot be misread the way a packed string can, so "36 hours" is taken to
        mean 36 hours rather than being rejected for exceeding a day.

        Args:
            value: Whatever the form sent for this field.
            field (str): Its name, for the error message.

        Returns:
            int: The value as a whole number.

        Raises:
            TimedStopError: If it is not a non-negative whole number.
        """
        if value is None or str(value).strip() == "":
            return 0

        try:
            number = int(float(str(value).strip()))
        except ValueError as e:
            raise TimedStopError(
                f"{field} must be a whole number, not {value!r}"
            ) from e

        if number < 0:
            raise TimedStopError(f"{field} cannot be negative")

        return number

    @staticmethod
    def _parse_duration(duration):
        """
        Parse a ``DD:HH:MM`` duration into seconds.

        Args:
            duration (str): The duration string, e.g. ``"02:12:30"``.

        Returns:
            int: Total number of seconds. Zero means "no automatic stop".

        Raises:
            TimedStopError: If the string is not three integers separated by colons,
                or if hours or minutes are out of range.
        """
        if duration is None or str(duration).strip() == "":
            return 0

        parts = str(duration).strip().split(":")
        if len(parts) != 3:
            raise TimedStopError(
                f"Could not read the duration {duration!r}. Use DD:HH:MM (days, hours, minutes)"
            )

        try:
            days, hours, minutes = (int(p) for p in parts)
        except ValueError as e:
            raise TimedStopError(
                f"Could not read the duration {duration!r}. Use DD:HH:MM (days, hours, minutes)"
            ) from e

        if days < 0 or hours < 0 or minutes < 0:
            raise TimedStopError(f"The duration {duration!r} cannot be negative")
        if not 0 <= hours < 24:
            raise TimedStopError("Hours must be between 0 and 23")
        if not 0 <= minutes < 60:
            raise TimedStopError("Minutes must be between 0 and 59")

        return days * 86400 + hours * 3600 + minutes * 60

    @staticmethod
    def _parse_stop_at(stop_at):
        """
        Parse an absolute stop time into a unix timestamp.

        Both a numeric timestamp and a date string are accepted. The web interface
        sends a timestamp, because only the browser knows the user's timezone; the
        string form is what a human types, and is read in the device's local time.

        Args:
            stop_at (str|float): The stop time, or an empty value for "not set".

        Returns:
            float|None: The stop time as a unix timestamp, or None if not set.

        Raises:
            TimedStopError: If the value is neither a timestamp nor a recognised date.
        """
        if stop_at is None:
            return None

        stop_at = str(stop_at).strip()
        if stop_at == "":
            return None

        try:
            timestamp = float(stop_at)
        except ValueError:
            pass
        else:
            # Reason: a bare number small enough to be a duration in seconds is far
            # more likely to be a mis-filled field than a stop time in 1970, and
            # silently stopping the experiment immediately is the worst outcome.
            if timestamp < 1e9:
                raise TimedStopError(
                    f"{stop_at!r} does not look like a date or a unix timestamp"
                )
            return timestamp

        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.datetime.strptime(stop_at, pattern)
            except ValueError:
                continue
            return time.mktime(parsed.timetuple())

        raise TimedStopError(
            f"Could not read the stop time {stop_at!r}. Use YYYY-MM-DD HH:MM:SS"
        )

    def resolve(self, start_time):
        """
        The absolute time at which the experiment should stop.

        Args:
            start_time (float): Unix timestamp the experiment is starting from. Only
                used for a duration; an absolute stop time ignores it.

        Returns:
            float|None: The unix timestamp to stop at, or None for no automatic stop.

        Raises:
            TimedStopError: If an absolute stop time has already passed. Refusing is
                the only safe reading: the alternative is an experiment that stops
                the moment it starts, several days after someone set it up.
        """
        if self._absolute is not None:
            if self._absolute <= start_time:
                raise TimedStopError(
                    f"The stop time {self.stop_at!r} is in the past, so the experiment "
                    "would stop as soon as it started"
                )
            return self._absolute

        if self._countdown > 0:
            return start_time + self._countdown

        return None

    def describe(self, start_time):
        """
        The scheduled stop as the ``DD:HH:MM`` run length the web interface displays.

        Args:
            start_time (float): Unix timestamp the experiment is starting from.

        Returns:
            str|bool: The run length as ``DD:HH:MM``, or False when there is no
                automatic stop, matching what the interface expects to be given.
        """
        stop_at = self.resolve(start_time)
        if stop_at is None:
            return False
        return format_countdown(stop_at - start_time)


# Experiment configurations saved before this class was shared between tracking and
# recording name it "timedStop", and the control threads resolve option classes by
# name, so the old spelling has to keep resolving.
timedStop = TimedStop
