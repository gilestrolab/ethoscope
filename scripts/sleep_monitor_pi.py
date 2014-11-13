__author__ = 'quentin'


# Interface to V4l
from pysolovideo.tracking.cameras import V4L2Camera
from pysolovideo.tracking.cameras import MovieVirtualCamera

# Build ROIs from greyscale image
from pysolovideo.tracking.roi_builders import ImgMaskROIBuilder

# the robust self learning tracker
from pysolovideo.tracking.trackers import AdaptiveBGModel

# the standard monitor
from pysolovideo.tracking.monitor import Monitor

import optparse
import logging





if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-o", "--output", dest="out", help="the output file (eg out.avi)", type="str")
    parser.add_option("-m", "--mask", dest="mask", help="the path to the mask file for defining ROIs", type="str")
    parser.add_option("-v", "--video", dest="video", help="the path to an optional video file."
                                                                "If not specified, the webcam will be used",
                                                                type="str", default=None)
    parser.add_option("-d", "--duration",dest="duration", help="The maximal duration of the monitoring (seconds). "
                                                               "Keyboard interrupt can be use to stop before",
                                                                default=60, type="int")

    (options, args) = parser.parse_args()

    option_dict = vars(options)

    if option_dict["mask"] is None:
        logging.error("A mask (--mask) should be specified")
        raise Exception()

    # use a video file instead of the camera if asked by the user (--video /path/to/video)
    if option_dict["video"] is not None:
        cam = MovieVirtualCamera(option_dict["video"])
    # Otherwise, webcam
    else:
        # The camera will not try to go faster than 3 fps
        cam = V4L2Camera(0, target_fps=3)

    roi_builder = ImgMaskROIBuilder(option_dict["mask"])

    rois = roi_builder(cam)

    monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    out_file=option_dict["out"], # save a csv out
                    max_duration=option_dict["duration"], # when to stop (in seconds)
                    draw_results=True, # draw position on image
                    draw_every_n=10) # only draw 1 every 10 frames to save time
    monit.run()


#### in R one could simply do:

df = read.csv("/tmp/test.csv")
dfss = subset(df, roi_idx==0)
plot(t ~ x  , dfss, type="l")

