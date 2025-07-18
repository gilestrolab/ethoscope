__author__ = 'quentin'






from ethoscope.tracking.cameras import *
from ethoscope.tracking.trackers import AdaptiveBGModel
import cv2
from ethoscope.tracking.roi_builders import DefaultROIBuilder

# we start from a cropped video:
cam = MovieVirtualCamera("/stk/pysolo_video_samples/singleDamTube1_150min_night.avi")



for t,frame in cam:
    break
rois = DefaultROIBuilder()(frame[:,0:24,:])
amog = AdaptiveBGModel(*rois)

for t,frame in cam:

    frame = frame[:,0:24,:]
    amog(t, frame)


    cv2.imshow("frame",frame )
    cv2.waitKey(3)
