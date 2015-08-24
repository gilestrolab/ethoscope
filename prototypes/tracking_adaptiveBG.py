__author__ = 'quentin'






from ethoscope.tracking.cameras import *
from ethoscope.tracking.trackers import AdaptiveBGModel
import cv2
import cv
import numpy as np
from ethoscope.tracking.roi_builders import DefaultROIBuilder

# we start from a cropped video:
cam = MovieVirtualCamera("/stk/pysolo_video_samples/singleDamTube1_150min_night.avi")




roi = DefaultROIBuilder()(cam)
amog = AdaptiveBGModel(*roi)

for t,frame in cam:
    amog(t, frame)


    cv2.imshow("frame",frame )
    cv2.waitKey(3)
