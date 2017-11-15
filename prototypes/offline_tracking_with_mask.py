__author__ = 'diana'

import cv2
from ethoscope.utils.debug import EthoscopeException


try:
    CV_VERSION = int(cv2.__version__.split(".")[0])
except:
    CV_VERSION = 2

from ethoscope.core.monitor import Monitor
from ethoscope.trackers.adaptive_bg_extra_object_pos_info_tracker import AdaptiveBGModelExtraObjectPosInfo
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.subroi_drawer import SubRoiDrawer
from ethoscope.roi_builders.arena_mask_roi_builder import ArenaMaskROIBuilder

INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/026c6ba04e534be486069c3db7b10827/ETHOSCOPE_026/2017-10-11_10-08-08/whole_2017-10-11_10-08-08_026c6ba04e534be486069c3db7b10827_trial_1920x1080@25_00000.mp4"
OUTPUT_VIDEO ="/home/diana/Desktop/test2.avi"
OUTPUT_DB = "/home/diana/Desktop/test2.db"

MASK = "/data/Diana/data_node/InkscapeFiles/single_arena_2_regions.png"

# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO, drop_each=1)

# here, we generate ROIs automatically using the mask of the arena
roi_builder = ArenaMaskROIBuilder(MASK)
rois = roi_builder.build(cam)

# Then, we go back to the first frame of the video
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video
drawer = SubRoiDrawer(OUTPUT_VIDEO, draw_frames = True)

# We build our monitor
monitor = Monitor(cam, AdaptiveBGModelExtraObjectPosInfo, rois)

# Now everything ius ready, we run the monitor with a result writer and a drawer
with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
 monitor.run(rw,drawer)