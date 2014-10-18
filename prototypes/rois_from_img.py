__author__ = 'quentin'


from pysolovideo.tracking.roi_builders import ImgMaskROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
from pysolovideo.tracking.interactors import SystemPlaySoundOnStop

import cv2




cam = MovieVirtualCamera("/stk/pysolo_video_samples/sleepdep_150min_night.avi")


rb = ImgMaskROIBuilder("/stk/pysolo_video_samples/maskOf_sleepdep_150min_night.png")

rois = rb(cam)



# inters = [SystemPlaySoundOnStop(500 + i * 30) for i in range(13)]
inters = [SystemPlaySoundOnStop(500 + i * 30) for i in range(13)]




monit = Monitor(cam, AdaptiveBGModel, interactors= inters, roi_builder=rb)
monit.run()

#
# for t,img in cam:
#     for i,r in enumerate(rois):
#         sub_img, mask = r(img)
#
#         cv2.imshow(str(i), sub_img)
#     cv2.imshow(str(i), img)
#     cv2.waitKey(1)
#








