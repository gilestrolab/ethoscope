from pysolovideo.tracking.roi_builders import TubeMonitorWithTargetROIBuilder
import cv2
smrb = TubeMonitorWithTargetROIBuilder()
im = cv2.imread("./tube_monitor_exple.png")
smrb(im)