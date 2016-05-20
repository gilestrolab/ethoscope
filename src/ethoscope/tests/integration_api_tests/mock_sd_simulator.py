from __future__ import print_function
from utils import test_stimulator
from ethoscope.stimulators.sleep_depriver_stimulators import SleepDepStimulator, ExperimentalSleepDepStimulator
from ethoscope.hardware.interfaces.interfaces import BaseInterface
import time

class MockSDInterface(BaseInterface):
    def send(self,channel, dt=350,margin=10):
        print(("Stimulus in channel", channel))
        time.sleep(.1)
    def _warm_up(self):
        print("Warming up")
        time.sleep(1)

class MockSDExperimentalStimulator(ExperimentalSleepDepStimulator):
    _HardwareInterfaceClass = MockSDInterface

class MockSDStimulator(SleepDepStimulator):
    _HardwareInterfaceClass = MockSDInterface

if __name__ == "__main__":
    test_stimulator(MockSDExperimentalStimulator, MockSDInterface)
    #test_stimulator(MockSDStimulator, MockSDInterface)