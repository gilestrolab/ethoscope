import tempfile
import os
from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.utils.io import SQLiteResultWriter, ResultWriter
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.drawers.drawers import DefaultDrawer
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.tests.integration_api_tests._constants import VIDEO, DRAW_FRAMES


def test_stimulator(StimulatorClass, InterfaceClass, remove_db_file = True, *args, **kwargs):
    tmp = tempfile.mkstemp(suffix="_ethoscope_test.db")[1]

    print(("Making a tmp db: " + tmp))
    cam = MovieVirtualCamera(VIDEO, drop_each=15)
    rb = SleepMonitorWithTargetROIBuilder()
    rois = rb.build(cam)
    cam.restart()

    connection = HardwareConnection(InterfaceClass)
    try:
        # stimulators = [MockSDStimulator(connection,min_inactive_time= 10) for _ in rois ]
        stimulators = [StimulatorClass(connection, *args, **kwargs) for _ in rois]
        mon = Monitor(cam, AdaptiveBGModel, rois, stimulators=stimulators)
        drawer = DefaultDrawer(draw_frames=DRAW_FRAMES)

        with SQLiteResultWriter(tmp , rois) as rw:
            mon.run(result_writer=rw, drawer=drawer)
        # cred = {"name": "ethoscope_db",
        #  "user": "ethoscope",
        #  "password": "ethoscope"}
        # with ResultWriter( cred , rois) as rw:
        #     mon.run(result_writer=rw, drawer=drawer)

    finally:
        if remove_db_file :
            print(("Removing temp db (" + tmp+ ")"))
            os.remove(tmp)
        else:
            print(("db file lives in (" + tmp + ")"))
        connection.stop()
