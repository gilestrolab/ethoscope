from ethoscope.hardware.input.cameras import *

from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
from ethoscope.drawers.drawers import DefaultDrawer, BaseDrawer

from ethoscope.core.monitor import Monitor
from ethoscope.roi_builders.roi_builders import  DefaultROIBuilder

from ethoscope.utils.io import rawdatawriter


# the input video - we work on an mp4 acquired with the Record function
input_video = "/home/gg/Downloads/test_video.mp4"

# the output video - we can save a video with the drawing of the tracking
# output_video = None
output_video = "/home/gg/tracked_video.mp4"

camera = MovieVirtualCamera(input_video)

# we use the default drawer and we show the video as we track - this is useful to understand how things are going
# disabling the video will speed things up
drawer = DefaultDrawer(draw_frames = False, video_out = output_video, video_out_fps=25)


# One Big ROI using the Default ROIBuilder
roi_builder = DefaultROIBuilder()
rois = roi_builder.build(camera)

# We use the npy tracker to save data in a npy file
rdw = rawdatawriter(basename='/home/gg/tracking_test.npy', n_rois=len(rois))


#Choice of trackers
# AdaptiveBGModel - The default tracker for fruit flies. One animal per ROI.
# MultiFlyTracker - An experimental tracker to monitor several animals per ROI.

# Starts the tracking monitor
monit = Monitor(camera, MultiFlyTracker, rois, stimulators=None )
monit.run(drawer=drawer, result_writer = rdw)
