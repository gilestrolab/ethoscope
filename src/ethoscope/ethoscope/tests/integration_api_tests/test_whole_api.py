"""
A general test to try to find out if anything is wrong with the API.
"""

import os
import random
import tempfile
import time
import unittest

from _constants import DRAW_FRAMES
from _constants import VIDEO

from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.hardware.interfaces.interfaces import (
    SimpleSerialInterface as BaseInterface,
)
from ethoscope.io import SQLiteResultWriter
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.stimulators.stimulators import BaseStimulator
from ethoscope.stimulators.stimulators import HasInteractedVariable
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel


class MockInterface(BaseInterface):
    def send(self, **kwargs):
        print("Sending " + str(kwargs))
        time.sleep(0.1)

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
        return HasInteractedVariable(interact), {"channel": roi_id, "time": now}


# from ethoscope.stimulators.sleep_depriver_stimulators import MiddleCrossingStimulator
# class MockStimulator2(MiddleCrossingStimulator):
#     _HardwareInterfaceClass = MockInterface


class TestAPI(unittest.TestCase):
    def test_API(self):
        random.seed(1)
        cam = MovieVirtualCamera(VIDEO)
        rb = FileBasedROIBuilder(template_name="sleep_monitor_20tube")
        reference_points, rois = rb.build(cam)
        hc = HardwareConnection(MockInterface)
        stimulators = [MockStimulator(hc) for _ in rois]

        cam.restart()
        mon = Monitor(cam, AdaptiveBGModel, rois, stimulators)

        drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)
        tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]
        try:
            print("Making a tmp db: " + tmp)
            with SQLiteResultWriter({"name": tmp}, rois) as rw:
                mon.run(result_writer=rw, drawer=drawer)
        except Exception:
            self.fail("testAPI raised ExceptionType unexpectedly!")
        finally:
            hc.stop()
            hc.join(timeout=5.0)  # Wait for hardware thread to finish
            if hc.is_alive():
                print("Warning: Hardware thread did not terminate cleanly")
            cam._close()
            print("Removing temp db (" + tmp + ")")
            os.remove(tmp)
