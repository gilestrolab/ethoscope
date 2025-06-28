
import tempfile
import os
from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.stimulators.sleep_depriver_stimulators import SleepDepStimulator
from ethoscope.hardware.interfaces.interfaces import BaseInterface
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.tests.integration_api_tests._constants import VIDEO, DRAW_FRAMES

class MockSDInterface(BaseInterface):
    def send(self,channel, dt=350,margin=10):
        print(("Stimulus in channel", channel))
    def _warm_up(self):
        print("Warming up")

class MockSDStimulator(SleepDepStimulator):
    _HardwareInterfaceClass = MockSDInterface

tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]

print("Making a tmp db: " + tmp)
cam = MovieVirtualCamera(VIDEO,drop_each=15)
rb = SleepMonitorWithTargetROIBuilder()
rois = rb.build(cam)
cam.restart()


connection  = HardwareConnection(MockSDInterface)
stimulators = [MockSDStimulator(connection,min_inactive_time= 10, date_range="2015-10-20 09:00:00 > 2017-12-21 00:00:00") for _ in rois ]

mon = Monitor(cam, AdaptiveBGModel, rois, stimulators=stimulators)
drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)


try:
    with SQLiteResultWriter(tmp , rois) as rw:
        mon.run(result_writer=rw, drawer=drawer)

finally:
    print("Removing temp db (" + tmp+ ")")
    os.remove(tmp)

    connection.stop()