__author__ = 'quentin'


from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
from pysolovideo.tracking.interactors import SleepDepInteractor

import cv2




cam = MovieVirtualCamera("/stk/pysolo_video_samples/23cm.avi")


rb = SleepDepROIBuilder()

# rois = rb(cam)
#
#
#
#
# inters = [SleepDepInteractor(i) for i in range(13)]
#
#
#
#
# monit = Monitor(cam, AdaptiveBGModel, interactors= inters, roi_builder=rb)
# monit.run()
######################################

#
# for t,img in cam:
#     for i,r in enumerate(rois):
#         sub_img, mask = r(img)
#
#         cv2.imshow(str(i), sub_img)
#     cv2.imshow(str(i), img)
#     cv2.waitKey(1)
#








