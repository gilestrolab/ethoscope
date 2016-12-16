import re
import datetime
import time
import logging

class DateRangeError(Exception):
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
        dates = re.split("\s*>\s*", str)

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
        pattern = re.compile("^\s*(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\s*$")
        if re.match("^\s*$", str):
            return None
        if not re.match(pattern, str):
            raise DateRangeError("%s not match the expected pattern" % str)
        datestr = re.match(pattern, str).groupdict()["date"]
        return time.mktime(datetime.datetime.strptime(datestr,'%Y-%m-%d %H:%M:%S').timetuple())
