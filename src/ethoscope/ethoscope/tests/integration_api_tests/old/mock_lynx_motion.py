
import time
import tempfile
import os
from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.stimulators.sleep_depriver_stimulators import SleepDepStimulator
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface
from ethoscope.hardware.interfaces.lynx_motion import SimpleLynxMotionInterface
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.tests.integration_api_tests._constants import VIDEO, DRAW_FRAMES

class MockSerial(object):
    def write(self, str):
        t = time.time()
        print("%i : MockSerial > %s" % (t,str) )
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
cam = MovieVirtualCamera(VIDEO,drop_each=15)
rb = SleepMonitorWithTargetROIBuilder()
rois = rb.build(cam)
cam.restart()

connection  = HardwareConnection(MockSDInterface)
stimulators = [MockSDStimulator(connection,min_inactive_time= 10) for _ in rois ]
mon = Monitor(cam, AdaptiveBGModel, rois, stimulators=stimulators)
drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)

try:
    with SQLiteResultWriter(tmp , rois) as rw:
        mon.run(result_writer=rw, drawer=drawer)
finally:
    print("Removing temp db (" + tmp+ ")")
    os.remove(tmp)
    connection.stop()