import re
import datetime
import time

class DateRangeError(Exception):
    pass

class Scheduler(object):
    def __init__(self,str):
        date_range_str = str.split(",")
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

    def in_range(self, t):
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
        if out[0] >= out[1]:
            raise DateRangeError("Error in date %s, the thse second date appears before the first!" % str)
        return out
    def _parse_date(self, str):
        pattern = re.compile("^\s*(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\s*$")
        if re.match("^\s*$", str):
            return None
        if not re.match(pattern, str):
            raise DateRangeError("%s not match the expected pattern" % str)
        datestr = re.match(pattern, str).groupdict()["date"]
        return time.mktime(datetime.datetime.strptime(datestr,'%Y-%m-%d %H:%M:%S').timetuple())


#a = DateRange("2016-10-10 10:00:00 > 2016-10-12")
#a = DateRange("2016-10-10 10:00:00 > a")
#a = DateRange("2016-10-10 10:00:00 > 2016-10-10 12:00:00")
#a = DateRange(" 2016-10-10 12:00:00")
Scheduler("")

Scheduler("2015-10-04 00:00:00")

Scheduler("2015-10-04 00:00:00 > 2015-11-04 00:00:00 ")
Scheduler("> 2015-11-04 00:00:00 ")
Scheduler("2015-11-04 00:00:00 >")
Scheduler("2015-10-04 00:00:00 > 2015-11-04 00:00:00")

s = Scheduler("2015-10-04 00:00:00 > 2015-10-05 00:00:00, 2015-10-07 00:00:00 > 2015-10-08 00:00:00")

def make_time(datestr):
    return time.mktime(datetime.datetime.strptime(datestr,'%Y-%m-%d %H:%M:%S').timetuple())
t1 = make_time("2015-10-03 00:00:00")
t2 = make_time("2015-10-04 00:00:01")
t3 = make_time("2015-10-06 00:00:00")
t4 = make_time("2015-10-07 12:00:00")
t5 = make_time("2016-10-07 12:00:00")
print(s.in_range(t1)) # false
print(s.in_range(t2)) #true
print(s.in_range(t3)) #false
print(s.in_range(t4)) #true
print(s.in_range(t5)) #false


#errors:
#Scheduler("2017-10-04 00:00:0q0 > 2015-11-04 00:00:00")
#Scheduler("2017-10-04 00:00:00 > 2015-11-04 00:00:00 > 2015-12-04 00:00:00")

#Scheduler("2017-10-04 00:00:00 > 2015-11-04 00:00:00,  ")
#Scheduler(" >   ")

# overlapping
#Scheduler("2015-10-04 00:00:00 > 2015-11-04 00:00:00,  2015-10-15 00:00:00 > 2015-12-04 00:00:00")
#a = Scheduler(",")


#a = DateRange("2016-10-10 10:00:00 > 2016-10-12 > test")
#a = DateRange("2016-10-12")
#b = a._split("2016-10-10")
