
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

import optparse
import logging





if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-o", "--output", dest="out", help="the output file (eg out.csv   )", type="str")
    parser.add_option("-v", "--video", dest="video", help="the path to an optional video file."
                                                                "If not specified, the webcam will be used",
                                                                type="str", default=None)
    parser.add_option("-r", "--result-video", dest="result_video", help="the path to an optional annotated video file."
                                                                "This is useful to show the result on a video.",
                                                                type="str", default=None)

    parser.add_option("-d", "--duration",dest="duration", help="The maximal duration of the monitoring (seconds). "
                                                               "Keyboard interrupt can be use to stop before",
                                                                default=None, type="int")

    parser.add_option("-f", "--drawing-frequency",dest="drawing_frequency", help="Draw only every N frames (to save processing power).",
                                                                default=-1, type="int")
    (options, args) = parser.parse_args()

    option_dict = vars(options)



    # use a video file instead of the camera if asked by the user (--video /path/to/video)
    if option_dict["video"] is not None:
        cam = MovieVirtualCamera(option_dict["video"])
    # Otherwise, webcam
    else:

        cam = V4L2Camera(0, target_fps=5, target_resolution=(560, 420))

    roi_builder = SleepMonitorWithTargetROIBuilder()

    rois = roi_builder(cam)

    df = option_dict["drawing_frequency"]
    if df <= 0:
        draw = False
    else:
        draw = True

    monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    out_file=option_dict["out"], # save a csv out
                    max_duration=option_dict["duration"], # when to stop (in seconds)
                    video_out=option_dict["result_video"], # when to stop (in seconds)
                    draw_results=draw, # draw position on image
                    draw_every_n=df) # only draw 1 every 10 frames to save time
    monit.run()


