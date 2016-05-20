from __future__ import print_function
from ethoscope.stimulators.odour_stimulators import DynamicOdourSleepDepriver
from ethoscope.hardware.interfaces.interfaces import BaseInterface
from utils import test_stimulator
import time


class MockSDInterface(BaseInterface):
    def send(self,channel, stimulus_duration ):
        print(("Stimulus in channel ", channel, "for a duration of ", stimulus_duration ))
        time.sleep(.1)
    def _warm_up(self):
        print("Warming up")

class MockOdourStimulator(DynamicOdourSleepDepriver):
    _HardwareInterfaceClass = MockSDInterface


if __name__ == "__main__":
    test_stimulator(MockOdourStimulator, MockSDInterface)

