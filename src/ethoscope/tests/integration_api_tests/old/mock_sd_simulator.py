

import time

from ethoscope.hardware.interfaces.interfaces import BaseInterface
from ethoscope.stimulators.sleep_depriver_stimulators import SleepDepStimulator
from ethoscope.tests.integration_api_tests.old.utils import test_stimulator


class MockSDInterface(BaseInterface):
    def send(self,channel, dt=350,margin=10):
        print(("Stimulus in channel", channel))
        time.sleep(.1)
    def _warm_up(self):
        print("Warming up")
        time.sleep(1)

class MockSDExperimentalStimulator(SleepDepStimulator):
    _HardwareInterfaceClass = MockSDInterface

class MockSDStimulator(SleepDepStimulator):
    _HardwareInterfaceClass = MockSDInterface

if __name__ == "__main__":
    test_stimulator(MockSDExperimentalStimulator, MockSDInterface, False, min_inactive_time=10)
    #test_stimulator(MockSDStimulator, MockSDInterface)