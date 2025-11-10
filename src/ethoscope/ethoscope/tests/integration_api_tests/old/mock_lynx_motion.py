import os
import tempfile
import time

from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionInterface
from ethoscope.hardware.interfaces.sleep_depriver_interface import (
    SleepDepriverInterface,
)
from ethoscope.io import SQLiteResultWriter
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.stimulators.sleep_depriver_stimulators import SleepDepStimulator
from ethoscope.tests.integration_api_tests._constants import DRAW_FRAMES, VIDEO
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel


class MockSerial:
    def write(self, str):
        t = time.time()
        print("%i : MockSerial > %s" % (t, str))

    def close(self):
        t = time.time()
        print("%i : MockSerial closed" % t)


class MockLynxMotionInterface(SimpleLynxMotionInterface):
    def __init__(self, port=None):
        self._serial = MockSerial()


class MockSDInterface(MockLynxMotionInterface, SleepDepriverInterface):
    pass


class MockSDStimulator(SleepDepStimulator):
    _HardwareInterfaceClass = MockSDInterface


tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]

print("Making a tmp db: " + tmp)
cam = MovieVirtualCamera(VIDEO, drop_each=15)
rb = FileBasedROIBuilder(template_name="sleep_monitor_20tube")
reference_points, rois = rb.build(cam)
cam.restart()

connection = HardwareConnection(MockSDInterface)
stimulators = [MockSDStimulator(connection, min_inactive_time=10) for _ in rois]
mon = Monitor(cam, AdaptiveBGModel, rois, stimulators=stimulators)
drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)

try:
    with SQLiteResultWriter(tmp, rois) as rw:
        mon.run(result_writer=rw, drawer=drawer)
finally:
    print("Removing temp db (" + tmp + ")")
    os.remove(tmp)
    connection.stop()
