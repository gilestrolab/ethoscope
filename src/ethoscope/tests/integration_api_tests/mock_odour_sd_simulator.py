from __future__ import print_function
import tempfile
import os
from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.stimulators.odour_stimulators import DynamicOdourSleepDepriver
from ethoscope.hardware.interfaces.interfaces import BaseInterface
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
import time

class MockSDInterface(BaseInterface):
    def send(self,channel, stimulus_duration ):
        print(("Stimulus in channel ", channel, "for a duration of ", stimulus_duration ))
        time.sleep(2)
    def _warm_up(self):
        print("Warming up")

class MockSDStimulator(DynamicOdourSleepDepriver):
    _HardwareInterfaceClass = MockSDInterface


VIDEO = "../static_files/videos/arena_10x2_sortTubes.mp4"

tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]

print("Making a tmp db: " + tmp)
cam = MovieVirtualCamera(VIDEO,drop_each=15)
rb = SleepMonitorWithTargetROIBuilder()
rois = rb.build(cam)
cam.restart()

connection  = HardwareConnection(MockSDInterface)
stimulators = [MockSDStimulator(connection, min_inactive_time= 10) for _ in rois ]

mon = Monitor(cam, AdaptiveBGModel, rois, stimulators=stimulators)
drawer = DefaultDrawer(draw_frames=True)


try:
    with SQLiteResultWriter(tmp , rois) as rw:
        mon.run(result_writer=rw, drawer=drawer)

finally:
    print("Removing temp db (" + tmp+ ")")
    os.remove(tmp)


connection.stop()