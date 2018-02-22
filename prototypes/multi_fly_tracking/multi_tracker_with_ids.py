__author__ = 'diana'

from ethoscope.core.monitor import Monitor
from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
from ethoscope.trackers.multi_fly_tracker_with_ids import MultiFlyTrackerWithIds
from ethoscope.trackers.multi_fly_tracker_kmeans import MultiFlyTrackerKMeans
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer

# You can also load other types of ROI builder. This one is for 20 tubes (two columns of ten rows)
from ethoscope.roi_builders.roi_builders import DefaultROIBuilder
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.roi_builders.target_roi_builder import HD12TubesRoiBuilder
from ethoscope.roi_builders.arena_mask_roi_builder import ArenaMaskROIBuilder

# change these three variables according to how you name your input/output files

INPUT_VIDEO="/data/Diana/data_node/ethoscope_videos/045c6ba04e534be486069c3db7b10827/ETHOSCOPE_045/2018-01-29_11-53-04/whole_2018-01-29_11-53-04_045c6ba04e534be486069c3db7b10827__1280x960@25_00000_IR_clean.mp4"
#INPUT_VIDEO="/data/Diana/data_node/ethoscope_videos/045c6ba04e534be486069c3db7b10827/ETHOSCOPE_045/2018-01-29_11-53-04/whole_2018-01-29_11-53-04_045c6ba04e534be486069c3db7b10827__1280x960@25_00000.mp4"
#INPUT_VIDEO ="/data/long.mp4"
#INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-04-26_14-54-13/whole_2017-04-26_14-54-13_065d6ba04e534be486069c3db7b10827_testCircles_1280x960@25_00000_clean.mp4"
#INPUT_VIDEO="/data/Diana/data_node/ethoscope_videos/071d6ba04e534be486069c3db7b10827/ETHOSCOPE_071/2017-06-01_09-08-51/whole_2017-06-01_09-08-51_071d6ba04e534be486069c3db7b10827__1280x960@25_00000_clean.mp4"
#INPUT_VIDEO="/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-04-26_14-54-13/whole_2017-04-26_14-54-13_065d6ba04e534be486069c3db7b10827_testCircles_1280x960@25_00000_cut2.mp4"
#INPUT_VIDEO="/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-10_08-54-52/whole_2017-05-10_08-54-52_065d6ba04e534be486069c3db7b10827_20femalesSD_1280x960@25_00000_clean_day.mp4"
#INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-24_09-08-49/whole_2017-05-24_09-08-49_065d6ba04e534be486069c3db7b10827_SD20_1280x960@25_00000_clean_2.mp4"
#INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-24_09-08-49/whole_2017-05-24_09-08-49_065d6ba04e534be486069c3db7b10827_SD20_1280x960@25_00000_clean.mp4"
#INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/015c6ba04e534be486069c3db7b10827/ETHOSCOPE_015/2016-08-02_08-55-23/whole_2016-08-02_08-55-23_015c6ba04e534be486069c3db7b10827__1920x1080@25_00000_clean.mp4"
#INPUT_VIDEO="/data/Diana/data_node/ethoscope_videos/015c6ba04e534be486069c3db7b10827/ETHOSCOPE_015/2016-08-02_08-55-23/whole_2016-08-02_08-55-23_015c6ba04e534be486069c3db7b10827__1920x1080@25_00000_test.mp4"
OUTPUT_VIDEO = "/tmp/my_output_12.avi"
OUTPUT_DB = "/tmp/results12.db"
MASK = "/data/Diana/data_node/InkscapeFiles/2squares_arena.png"
# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO)

# here, we generate ROIs automatically from the targets in the images
#roi_builder = TargetGridROIBuilder(n_rows=1, n_cols=1)
roi_builder = ArenaMaskROIBuilder(MASK)

rois = roi_builder.build(cam)
#rois = HD12TubesRoiBuilder().build(cam)
# Then, we go back to the first frame of the video
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video
drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)

# We build our monitor
monitor = Monitor(cam, MultiFlyTrackerKMeans, rois, n_flies = 2)


# Now everything ius ready, we run the monitor with a result writer and a drawer
with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
    monitor.run(rw, drawer)