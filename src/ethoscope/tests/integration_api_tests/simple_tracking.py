from __future__ import print_function
import tempfile
import os
from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from _constants import VIDEO, DRAW_FRAMES


tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]

print("Making a tmp db: " + tmp)
cam = MovieVirtualCamera(VIDEO)
rb = SleepMonitorWithTargetROIBuilder()
rois = rb.build(cam)
cam.restart()
mon = Monitor(cam,AdaptiveBGModel, rois)
drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)
try:
    with SQLiteResultWriter(tmp , rois) as rw:
        mon.run(result_writer=rw, drawer=drawer)

finally:
    print("Removing temp db (" + tmp+ ")")
    os.remove(tmp)


