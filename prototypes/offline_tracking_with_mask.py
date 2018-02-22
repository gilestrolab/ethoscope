__author__ = 'diana'

import cv2
try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2


import ethoscope

from ethoscope.core.monitor import Monitor
from ethoscope.trackers.adaptive_bg_extra_object_pos_info_tracker import AdaptiveBGModelExtraObjectPosInfo
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel

from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.subroi_drawer import SubRoiDrawer
from ethoscope.drawers.drawers import DefaultDrawer
from optparse import OptionParser
from ethoscope.trackers.simple_tracker import SimpleTracker
import os

from ethoscope.roi_builders.arena_mask_roi_builder import ArenaMaskROIBuilder

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-i", "--input", dest="input", help="The input video file")
    parser.add_option("-o", "--video", dest="video", help="The output video file with the tracking")
    parser.add_option("-r", "--resultdb", dest="resultdb", help="The .db result file")

    (options, args) = parser.parse_args()
    option_dict = vars(options)
    INPUT_VIDEO = option_dict["input"]
    OUTPUT_DB = option_dict["resultdb"]
    OUTPUT_VIDEO = option_dict["video"]



    #INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4"
    #INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos_y_maze/021aeeee10184bb39b0754e75cef7900/ETHOSCOPE_021/2016-06-20_10-44-38/whole_2016-06-20_10-44-38_021aeeee10184bb39b0754e75cef7900_diana-cntrl-reg-13-etho-21_1280x960@25_00000_clean.mp4"
    #INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos_y_maze/024aeeee10184bb39b0754e75cef7900/ETHOSCOPE_024/2016-05-03_11-08-02/whole_2016-05-03_11-08-02_024aeeee10184bb39b0754e75cef7900_diana-dam-3-fly-10-etho-24-ctrl_1280x960@25_00000_clean.mp4"
    #INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos_y_maze/021aeeee10184bb39b0754e75cef7900/ETHOSCOPE_021/2016-06-21_09-25-46/whole_2016-06-21_09-25-46_021aeeee10184bb39b0754e75cef7900_fly2-ctrl-etho21_1280x960@25_00000_clean.mp4"
    #OUTPUT_VIDEO ="/home/diana/Desktop/test2.avi"
    #OUTPUT_DB = "/home/diana/Desktop/test2.db"

    #MASK = "/data/Diana/data_node/InkscapeFiles/single_arena_2_regions.png"
    #MASK = "/home/diana/Desktop/hinata/hinata_final_mask.png"
    #MASK = "/data/Diana/data_node/InkscapeFiles/single_arena.png"
    #MASK = "/data/Diana/data_node/InkscapeFiles/test1.png"
    #MASK = "/data/Diana/data_node/InkscapeFiles/different_regions.png"
    #MASK = "/data/Diana/data_node/InkscapeFiles/arena_binary_final.png"
    #MASK = "/data/Diana/data_node/InkscapeFiles/image_2.png"
    #MASK = "/data/Diana/data_node/InkscapeFiles/image_7.png"

    #MASK = "/data/Diana/data_node/InkscapeFiles/arena_many_holes.png"

    MASK = "/data/Diana/data_node/InkscapeFiles/arena_24flies.png"

    # We use a video input file as if it was a "camera"
    cam = MovieVirtualCamera(INPUT_VIDEO, drop_each=1)

    # here, we generate ROIs automatically using the mask of the arena
    roi_builder = ArenaMaskROIBuilder(MASK)
    rois = roi_builder.build(cam)

    # Then, we go back to the first frame of the video
    cam.restart()

    # we use a drawer to show inferred position for each animal, display frames and save them as a video
    drawer = SubRoiDrawer(OUTPUT_VIDEO, draw_frames=True)

    # We build our monitor
    monitor = Monitor(cam, AdaptiveBGModelExtraObjectPosInfo, rois)

    # Now everything ius ready, we run the monitor with a result writer and a drawer
    with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
        monitor.run(rw, drawer)
