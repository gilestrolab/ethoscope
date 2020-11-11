from ethoscope.hardware.input.cameras import *

from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker, HaarTracker
from ethoscope.drawers.drawers import DefaultDrawer

from ethoscope.core.monitor import Monitor
from ethoscope.roi_builders.roi_builders import  DefaultROIBuilder

from ethoscope.utils.io import rawdatawriter, npyAppendableFile


# the input video - we work on an mp4 acquired with the Record function
#input_video = "/home/gg/Downloads/test_video.mp4"
input_video= "//home/gg/Cabinet/Work/Projects/custom_devices/ethoscope/olfactometer/olfactometer_tracking/whole_2020-10-21_19-16-51_2020f8bceb334c1c84518f62359ddc76_applestarved_1280x960@25_00001.mp4"

#the location of the haar cascade file (in case we want to use the haar tracking function)
cascade = "/home/gg/Cabinet/Work/Projects/custom_devices/ethoscope/olfactometer/olfactometer_tracking/data/cascade.xml"

#how many flies we expect
entities=35

#the type of tracking we want to use
ttype = "haar"

#Choice of trackers
# default - AdaptiveBGModel - The default tracker for fruit flies. One animal per ROI.
# multi - MultiFlyTracker - An experimental tracker to monitor several animals per ROI.
# haar - HaarTracker - An experimental tracker to monitor several animals per ROI using a Haar Cascade.

# the output video - we can save a video with the drawing of the tracking
output_video = None

#output_video = "/home/gg/tracked_video_big_fly.mp4"

camera = MovieVirtualCamera(input_video)

# we use the default drawer and we show the video as we track - this is useful to understand how things are going
# disabling the video will speed things up. We can also save a video output if we pass a filename for the video
drawer = DefaultDrawer(draw_frames = True, video_out = output_video, video_out_fps=25)


#Choice of ROIs
roi_builder = DefaultROIBuilder() # One Big ROI using the Default ROIBuilder
#roi_builder = SleepMonitorWithTargetROIBuilder() # the default ROI structure for a 20 vials arena. Requires targets
#roi_builder = ImgMaskROIBuilder("maskfile.png") # Creates a custom MASK as ROI taken from a greyscale image file. Each different shade of grey is a different ROI


#create the rois
rois = roi_builder.build(camera)

# We use the npy tracker to save data in a npy file
#rdw = rawdatawriter(basename='/home/gg/tracking_%s.npy' % ttype, n_rois=len(rois), entities=entities)
rdw = None


#for multifly tracking using BS subtraction

if ttype == "multi":
    monit = Monitor(camera, MultiFlyTracker, rois, stimulators=None, data={ 'maxN' : 50, 
                                        'visualise' : False ,
                                        'fg_data' : { 'sample_size' : 400, 'normal_limits' : (50, 200), 'tolerance' : 0.8 }
                                      } )

#For the haar tracking
if ttype == "haar":
    monit = Monitor(camera, HaarTracker, rois, stimulators=None, data = { 'maxN' : entities, 
                     'cascade' : cascade,
                     'scaleFactor' : 1.1,
                     'minNeighbors' : 3,
                     'flags' : 0,
                     'minSize' : (15,15),
                     'maxSize' : (20,20),
                     'visualise' : False }
                     )

if ttype == "default":
    monit = Monitor(camera, AdaptiveBGModel, rois)

# Starts the tracking monitor
monit.run(drawer = drawer, result_writer = rdw)
