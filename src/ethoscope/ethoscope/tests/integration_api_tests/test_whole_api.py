"""
A general test to try to find out if anything is wrong with the API.
"""

import tempfile
import os
import time
import random
from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.hardware.interfaces.interfaces import BaseInterface
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from _constants import VIDEO, DRAW_FRAMES
from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable


import unittest


class MockInterface(BaseInterface):
    def send(self,**kwargs):
        print("Sending " + str(kwargs))
        time.sleep(.1)
    def _warm_up(self):
        print("Warming up")
        time.sleep(1)

class MockStimulator(BaseStimulator):
    _HardwareInterfaceClass = MockInterface
    def _decide(self):
        roi_id = self._tracker._roi.idx
        now = self._tracker.last_time_point
        # every 100 times:
        interact = random.uniform(0.0, 1.0) < 0.01
        return HasInteractedVariable(interact), {"channel":roi_id, "time":now }

# from ethoscope.stimulators.sleep_depriver_stimulators import MiddleCrossingStimulator
# class MockStimulator2(MiddleCrossingStimulator):
#     _HardwareInterfaceClass = MockInterface




class TestAPI(unittest.TestCase):
    def test_API(self):
        random.seed(1)
        cam = MovieVirtualCamera(VIDEO)
        rb = SleepMonitorWithTargetROIBuilder()
        rois = rb.build(cam)
        hc = HardwareConnection(MockInterface)
        stimulators = [MockStimulator(hc) for _ in rois]

        cam.restart()
        mon = Monitor(cam, AdaptiveBGModel, rois, stimulators)

        drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)
        tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]
        try:
            print("Making a tmp db: " + tmp)
            with SQLiteResultWriter(tmp , rois) as rw:
                mon.run(result_writer=rw, drawer=drawer)
        except:
            self.fail("testAPI raised ExceptionType unexpectedly!")
        finally:
            hc.stop()
            cam._close()
            print("Removing temp db (" + tmp+ ")")
            os.remove(tmp)
