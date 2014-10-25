__author__ = 'quentin'


from pysolovideo.tracking.roi_builders import ImgMaskROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
from pysolovideo.tracking.interactors import SleepDepInteractor
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface

import cv2




cam = MovieVirtualCamera("/stk/pysolo_video_samples/sleepdep_150min_night.avi")


rb = ImgMaskROIBuilder("/stk/pysolo_video_samples/maskOf_sleepdep_150min_night.png")

rois = rb(cam)


sdi = SleepDepriverInterface()

inters = [SleepDepInteractor(i, sdi) for i in range(13)]




monit = Monitor(cam, AdaptiveBGModel, interactors= inters, roi_builder=rb)
monit.run()