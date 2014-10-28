__author__ = 'quentin'



from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
from pysolovideo.tracking.interactors import SleepDepInteractor
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface

import cv2




# cam = MovieVirtualCamera("/stk/pysolo_video_samples/23cm.avi")
cam = MovieVirtualCamera("/stk/pysolo_video_samples/test_red_wool.avi")


#
rb = SleepDepROIBuilder()
# #


#
#
# sdi = SleepDepriverInterface()
#
# inters = [SleepDepInteractor(i, sdi) for i in range(13)]
#
#
#
#
monit = Monitor(cam, AdaptiveBGModel, interactors= None, roi_builder=rb)
monit.run()
#
#