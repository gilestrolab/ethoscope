__author__ = 'quentin'


__author__ = 'quentin'

from pysolovideo.tracking.cameras import MovieVirtualCamera

# Build ROIs from greyscale image
from pysolovideo.tracking.roi_builders import SleepMonitorWithTargetROIBuilder

# the robust self learning tracker
from pysolovideo.tracking.trackers import AdaptiveBGModel

# the standard monitor
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.utils.io import SQLiteResultWriter

import pkg_resources
import optparse
import logging
import os

CHUNK_LENGTH = 10 #s
if __name__ == "__main__":

    parser = optparse.OptionParser()
    parser.add_option("-o", "--output", dest="out", help="the output dir", type="str")
    parser.add_option("-i", "--input", dest="input", help="the output video file", type="str")

    (options, args) = parser.parse_args()

    option_dict = vars(options)

    cam = MovieVirtualCamera(option_dict ["input"], use_wall_clock=True)


    roi_builder = SleepMonitorWithTargetROIBuilder()
    rois = roi_builder(cam)

    for t in range(60 * 10 ,20 *60, 5*60):

        for r in rois:

            d = r.get_feature_dict()
            out_file_basename = "%02d_%i.mp4" %(d["idx"], t)
            out_file_path = os.path.join(option_dict["out"],out_file_basename)
            print "Generating %s" % out_file_path
            command ='ffmpeg  -n -ss %i -i %s   -t %i -vf "crop=%i:%i:%i:%i"  %s' %(
                t,
                option_dict["input"],
                CHUNK_LENGTH,
                d["w"],
                d["h"],
                d["x"],
                d["y"],
                out_file_path
            )

            os.system(command)

