__author__ = 'quentin'


from ethoscope.tracking.roi_builders import ImgMaskROIBuilder
from ethoscope.tracking.cameras import MovieVirtualCamera
from ethoscope.tracking.monitor import Monitor
from ethoscope.tracking.trackers import AdaptiveBGModel
from ethoscope.tracking.interactors import SleepDepInteractor
from ethoscope.hardware_control.arduino_api import SleepDepriverInterface

import cv2




cam = MovieVirtualCamera("/stk/pysolo_video_samples/sleepdep_150min_night.avi")


rb = ImgMaskROIBuilder("/stk/pysolo_video_samples/maskOf_sleepdep_150min_night.png")

rois = rb(cam)


sdi = SleepDepriverInterface()

inters = [SleepDepInteractor(i, sdi) for i in range(13)]




monit = Monitor(cam, AdaptiveBGModel, interactors= inters, roi_builder=rb)
monit.run()