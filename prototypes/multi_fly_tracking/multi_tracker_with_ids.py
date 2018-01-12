__author__ = 'diana'

from ethoscope.core.monitor import Monitor
from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
from ethoscope.trackers.multi_fly_tracker_with_ids import MultiFlyTrackerWithIds
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer

# You can also load other types of ROI builder. This one is for 20 tubes (two columns of ten rows)
from ethoscope.roi_builders.roi_builders import DefaultROIBuilder
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder

# change these three variables according to how you name your input/output files
INPUT_VIDEO = "/data/Diana/data_node/ethoscope_videos/065d6ba04e534be486069c3db7b10827/ETHOSCOPE_065/2017-05-24_09-08-49/whole_2017-05-24_09-08-49_065d6ba04e534be486069c3db7b10827_SD20_1280x960@25_00000_clean.mp4"
OUTPUT_VIDEO = "/tmp/my_output.avi"
OUTPUT_DB = "/tmp/results.db"

# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO)

# here, we generate ROIs automatically from the targets in the images
roi_builder = TargetGridROIBuilder(n_rows=1, n_cols=1)
rois = roi_builder.build(cam)
# Then, we go back to the first frame of the video
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video
drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)
# We build our monitor
monitor = Monitor(cam, MultiFlyTrackerWithIds, rois)

# Now everything ius ready, we run the monitor with a result writer and a drawer
with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
    monitor.run(rw, drawer)