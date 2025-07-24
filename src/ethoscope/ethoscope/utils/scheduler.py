import re
import datetime
import time
import logging
import json
import os

class DateRangeError(Exception):
    pass

class DailyScheduleError(Exception):
    pass

class Scheduler(object):
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
        for drs in  date_range_str:
            dr = self._parse_date_range(drs)

            self._date_ranges.append(dr)
        self._check_date_ranges(self._date_ranges)

    def _check_date_ranges(self, ranges):
        all_dates = []
        for start,end in ranges:
            all_dates.append(start)
            all_dates.append(end)

        for i  in  range(0, len(all_dates)-1):
            if (all_dates[i+1] - all_dates[i]) <= 0:
                raise DateRangeError("Some date ranges overlap")
        pass

    def check_time_range(self, t = None):
        """
        Check whether a unix timestamp is within the allowed range.
        :param t: the time to test. When ``None``, the system time is used
        :type t: float
        :return: ``True`` if the time was in range, ``False`` otherwise
        :rtype: bool
        """
        if t is None:
            t= time.time()
        return self._in_range(t)

    def _in_range(self, t):
        for r in self._date_ranges:
            if r[1] > t > r[0]:
                return True
        return False

    def _parse_date_range(self, str):
        self._start_date = 0
        self._stop_date = float('inf')
        dates = re.split(r"\s*>\s*", str)

        if len(dates) > 2:
            raise DateRangeError(" found several '>' symbol. Only one is allowed")
        date_strs = []
        for d in dates:
            date_strs.append(self._parse_date(d))

        if len(date_strs) == 1:
            # start_date
            if date_strs[0] is None:
                out =  (0,float("inf"))
            else:
                out = (date_strs[0], float("inf"))

        elif len(date_strs) == 2:
            d1, d2 = date_strs
            if d1 is None:
                if d2 is None:
                    raise DateRangeError("Data range cannot inclue two None dates")
                out =  (0, d2)
            elif d2 is None:
                out =  (d1, float("inf"))
            else:
                out =  (d1, d2)
        else:
            raise Exception("Unexpected date string")
        if out[0] >= out[1]:
            raise DateRangeError("Error in date %s, the end date appears to be in the past" % str)
        return out
        
    def _parse_date(self, str):
        pattern = re.compile(r"^\s*(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\s*$")
        if re.match(r"^\s*$", str):
            return None
        if not re.match(pattern, str):
            raise DateRangeError("%s not match the expected pattern" % str)
        datestr = re.match(pattern, str).groupdict()["date"]
        return time.mktime(datetime.datetime.strptime(datestr,'%Y-%m-%d %H:%M:%S').timetuple())


class DailyScheduler(object):
    """
    Enhanced scheduler for daily time-restricted operations.
    
    This scheduler supports operations that run for N hours per day at specified intervals,
    designed for sleep restriction experiments that inherit from mAGO stimulators.
    """
    
    def __init__(self, daily_duration_hours, interval_hours=24, daily_start_time="00:00:00", state_file_path=None):
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
            raise DailyScheduleError("daily_duration_hours cannot exceed interval_hours")
            
        self._daily_duration_hours = daily_duration_hours
        self._interval_hours = interval_hours
        self._daily_start_time = daily_start_time
        self._state_file_path = state_file_path
        
        # Parse start time
        self._start_time_seconds = self._parse_time_string(daily_start_time)
        
        # State tracking
        self._state = self._load_state() if state_file_path else {}
        
        logging.info(f"DailyScheduler initialized: {daily_duration_hours}h active every {interval_hours}h starting at {daily_start_time}")
    
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
        except ValueError:
            raise DailyScheduleError(f"Invalid time format: {time_str}. Expected HH:MM:SS")
    
    def _load_state(self):
        """Load scheduler state from file."""
        if not self._state_file_path or not os.path.exists(self._state_file_path):
            return {}
            
        try:
            with open(self._state_file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Could not load scheduler state: {e}")
            return {}
    
    def _save_state(self):
        """Save scheduler state to file."""
        if not self._state_file_path:
            return
            
        try:
            os.makedirs(os.path.dirname(self._state_file_path), exist_ok=True)
            with open(self._state_file_path, 'w') as f:
                json.dump(self._state, f, indent=2)
        except IOError as e:
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
            
        # Get current time components
        dt = datetime.datetime.fromtimestamp(t)
        current_seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
        
        # Calculate time since the most recent start time
        days_since_epoch = int(t // 86400)  # 86400 seconds per day
        start_timestamp = days_since_epoch * 86400 + self._start_time_seconds
        
        # Handle interval periods (multiple periods per day or multi-day intervals)
        interval_seconds = self._interval_hours * 3600
        active_seconds = self._daily_duration_hours * 3600
        
        # Find the most recent period start
        periods_since_start = int((t - start_timestamp) // interval_seconds)
        if t < start_timestamp:
            periods_since_start = -1
            
        current_period_start = start_timestamp + (periods_since_start * interval_seconds)
        current_period_end = current_period_start + active_seconds
        
        # Check if we're in the active window
        is_active = current_period_start <= t < current_period_end
        
        # Update state tracking
        if is_active and self._state_file_path:
            period_key = f"period_{int(current_period_start)}"
            if period_key not in self._state:
                self._state[period_key] = {
                    'start_time': current_period_start,
                    'end_time': current_period_end,
                    'first_activity': t
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
            
        # Calculate next period start
        days_since_epoch = int(t // 86400)
        start_timestamp = days_since_epoch * 86400 + self._start_time_seconds
        
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
            
        # Calculate current period end
        days_since_epoch = int(t // 86400)
        start_timestamp = days_since_epoch * 86400 + self._start_time_seconds
        
        interval_seconds = self._interval_hours * 3600
        active_seconds = self._daily_duration_hours * 3600
        
        periods_since_start = int((t - start_timestamp) // interval_seconds)
        current_period_start = start_timestamp + (periods_since_start * interval_seconds)
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
            'daily_duration_hours': self._daily_duration_hours,
            'interval_hours': self._interval_hours,
            'daily_start_time': self._daily_start_time,
            'currently_active': is_active,
        }
        
        if is_active:
            info['remaining_active_seconds'] = self.get_remaining_active_time(now)
        else:
            info['seconds_until_next_period'] = self.get_time_until_next_period(now)
            
        next_start, next_end = self.get_next_active_period(now)
        info['next_period_start'] = datetime.datetime.fromtimestamp(next_start).isoformat()
        info['next_period_end'] = datetime.datetime.fromtimestamp(next_end).isoformat()
        
        return info
