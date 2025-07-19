__author__ = 'quentin'






from ethoscope.tracking.cameras import *
from ethoscope.tracking.trackers import AdaptiveMOGTracker
import cv2
import cv
import numpy as np

# we start from a cropped video:
cam = MovieVirtualCamera("/stk/pysolo_video_samples/singleDamTube2_150min_night.avi")




amog = AdaptiveMOGTracker()

for t,frame in cam:
    amog(t, frame, None)


    cv2.imshow("frame",frame )
    cv2.waitKey(1)
