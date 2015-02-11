from pysolovideo.tracking.roi_builders import SleepMonitorWithTargetROIBuilder
import cv2
smrb = SleepMonitorWithTargetROIBuilder()
im = cv2.imread("/tmp/b91dfd54-b15d-11e4-92e2-f62dad0aefc8.jpg")
smrb(im)