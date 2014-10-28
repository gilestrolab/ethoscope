__author__ = 'quentin'
#




__author__ = 'quentin'



from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
from pysolovideo.tracking.interactors import SleepDepInteractor
from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface

import cv2




cam = MovieVirtualCamera("/stk/pysolo_video_samples/23cm.avi")

for t,f in cam:
    im =f
    break

im2=cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
im2[:,:,0] = 0


# mser = cv2.MSER(_delta= 50,_max_area=1000, _min_area=300)
#mser = cv2.MSER()
mser = cv2.MSER(_max_area=1000, _min_area=300)


objects = mser.detect(im2)

print len(objects)
for o in objects:
    ct = o.reshape((o.shape[0],1,2))
    cv2.drawContours(im,[ct],0,(255,255,50),-1)

cv2.imshow("test",im);cv2.waitKey(-1)
