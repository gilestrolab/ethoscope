
__author__ = 'quentin'


# Interface to V4l
from pysolovideo.tracking.cameras import V4L2Camera
from pysolovideo.tracking.cameras import MovieVirtualCamera

# Build ROIs from greyscale image
from pysolovideo.tracking.roi_builders import SleepMonitorWithTargetROIBuilder

# the robust self learning tracker
from pysolovideo.tracking.trackers import AdaptiveBGModel

# the standard monitor
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.utils.io import ResultWriter

import pkg_resources
import optparse
import logging




_result_dir = "/tmp/psv/results/"
_last_img_file = "/tmp/psv/last_img.jpg"
_dbg_img_file = "/tmp/psv/dbg_img.png"
_log_file = "/tmp/psv/psv.log"

if __name__ == "__main__":

    # parser = optparse.OptionParser()
    # parser.add_option("-o", "--output", dest="out", help="the output file (eg out.csv   )", type="str")
    #
    # parser.add_option("-r", "--result-video", dest="result_video", help="the path to an optional annotated video file."
    #                                                             "This is useful to show the result on a video.",
    #                                                             type="str", default=None)
    #
    # parser.add_option("-d", "--duration",dest="duration", help="The maximal duration of the monitoring (seconds). "
    #                                                            "Keyboard interrupt can be use to stop before",
    #                                                             default=None, type="int")
    #
    # parser.add_option("-f", "--drawing-frequency",dest="drawing_frequency", help="Draw only every N frames (to save processing power).",
    #                                                             default=-1, type="int")
    # (options, args) = parser.parse_args()

    logging.basicConfig(filename=_log_file, level=logging.INFO)

    # option_dict = vars(options)



    #cam = V4L2Camera(0, target_fps=5, target_resolution=(640, 480))
    INPUT_VIDEO = '/data/pysolo_video_samples/sleep_monitor_100h_no_heat.avi'
    cam = MovieVirtualCamera(INPUT_VIDEO)


    logging.info("Building ROIs")
    roi_builder = SleepMonitorWithTargetROIBuilder()
    rois = roi_builder(cam)

    logging.info("Initialising monitor")

    metadata = {
                 "machine_id": "NA",
                 "date_time": "NA",
                 "frame_width":cam.width,
                 "frame_height":cam.height,
                  "psv_version": pkg_resources.get_distribution("pysolovideo").version
                  }

    monit = Monitor(cam,
                AdaptiveBGModel,
                rois,
                result_dir=_result_dir,
                metadata=metadata,
                draw_every_n=1,
                draw_results=True
                )


    monit.run()

