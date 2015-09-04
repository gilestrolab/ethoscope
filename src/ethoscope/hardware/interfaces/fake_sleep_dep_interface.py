__author__ = 'quentin'
from sleep_depriver_interface import SleepDepriverInterface, SleepDepriverSubProcess, SleepDepriverConnection


class FakeSleepDepriverConnection(SleepDepriverConnection):
    def deprive(self,channel, dt=500):
        str = "depriving channel %i, with dt= %i" % (channel,dt)
        time.sleep(1)
        print str

    def __del__(self):
        pass

class FakeSleepDepriverSubProcess(SleepDepriverSubProcess):
    _DepriverConnectionClass = FakeSleepDepriverInterface

class FakeSleepDepriverInterface(SleepDepriverInterface):
    _SubProcessClass = FakeSleepDepriverSubProcess


