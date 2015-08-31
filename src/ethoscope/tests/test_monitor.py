__author__ = 'quentin'

from ethoscope.tracking.cameras import MovieVirtualCamera
from ethoscope.tracking.roi_builders import TargetGridROIBuilderBase
from ethoscope.tracking.trackers import AdaptiveBGModel
from ethoscope.tracking.monitor import Monitor
from ethoscope.utils.io import SQLiteResultWriter
import logging
import unittest

INPUT_VIDEO = "/data/sleep_dep_vid_2fps.mp4"
OUTPUT_VIDEO = "/data/sleep_dep_vid_annot.avi"
OUTPUT_DB = "/home/quentin/Desktop/sleep_dep_vid_ok.db"

class TestROIBuilder(TargetGridROIBuilderBase):


    _vertical_spacing =  .15/10.
    _horizontal_spacing =  .025
    _n_rows = 10
    _n_cols = 2
    _horizontal_margin_left = +1. # from the center of the target to the external border (positive value makes grid larger)
    _horizontal_margin_right = +1. # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_top = -1.25 # from the center of the target to the external border (positive value makes grid larger)
    _vertical_margin_bottom = -.5 # from the center of the target to the external border (positive value makes grid larger)


class TestMonitor(unittest.TestCase):
    def test_all(self):
        cam = MovieVirtualCamera(INPUT_VIDEO, use_wall_clock=False)

        roi_builder = TestROIBuilder
        rois = roi_builder(cam)

        # logging.info("Initialising monitor")

        cam.restart()

        metadata = {
                                 "machine_id": "None",
                                 "machine_name": "None",
                                 "date_time": cam.start_time, #the camera start time is the reference 0
                                 "frame_width":cam.width,
                                 "frame_height":cam.height,
                                 "version": "whatever"
                                  }

        draw_frames = True


        monit = Monitor(cam, AdaptiveBGModel, rois,
                        draw_every_n=1,
                        draw_results=draw_frames,
                        video_out=OUTPUT_VIDEO
                        )


        try:
            with SQLiteResultWriter(OUTPUT_DB ,rois, metadata) as rw:
                logging.info("Running monitor" )
                monit.run(rw)
        except KeyboardInterrupt:
            monit.stop()