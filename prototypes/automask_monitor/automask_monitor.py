from pysolovideo.tracking.roi_builders import SleepMonitorWithTargetROIBuilder
import cv2
smrb = SleepMonitorWithTargetROIBuilder()
im = cv2.imread("./new_targets.png")
smrb(im)