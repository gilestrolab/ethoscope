__author__ = 'quentin'

from ethoscope.tracking.cameras import MovieVirtualCamera



from ethoscope.tracking.roi_builders import TubeMonitorWithTargetROIBuilder

from ethoscope.tracking.trackers import AdaptiveBGModel


from ethoscope.tracking.monitor import Monitor
from ethoscope.utils.io import SQLiteResultWriter


import logging
import unittest




INPUT_VIDEO = "/data/sleep_dep_vid.mp4"
OUTPUT_VIDEO = "/data/sleep_dep_vid_annot.avi"
OUTPUT_DB = "/data/sleep_dep_vid.db"


class TestMySQL(unittest.TestCase):
    def test_all(self):
        cam = MovieVirtualCamera(INPUT_VIDEO, use_wall_clock=False)

        roi_builder = TubeMonitorWithTargetROIBuilder()
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
                        video_out=OUTPUT_VIDEO,
                        drop_each=10,
                        )


        try:
            with SQLiteResultWriter(OUTPUT_DB ,rois, metadata) as rw:
                logging.info("Running monitor" )
                monit.run(rw)
        except KeyboardInterrupt:
            monit.stop()

