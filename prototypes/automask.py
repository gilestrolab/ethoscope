__author__ = 'quentin'



from pysolovideo.tracking.roi_builders import SleepDepROIBuilder
from pysolovideo.tracking.cameras import MovieVirtualCamera
from pysolovideo.tracking.monitor import Monitor
from pysolovideo.tracking.trackers import AdaptiveBGModel
import glob
import cv2
import os

AUTO_ROI_DATA = "/stk/pysolo_video_samples/auto_rois/"
OUT_IMG = "/home/quentin/Desktop/tmp/"
shots = glob.glob(AUTO_ROI_DATA + "*.png")


roi_builder = SleepDepROIBuilder()
for i, s in enumerate(reversed(sorted(shots))):


    im = cv2.imread(s)
    cv2.imshow("auto", im)
    cv2.waitKey(1)
    try:
        rois = roi_builder(im)


        for r in rois:
            cv2.putText(im, str(r.idx+1), r.offset, cv2.FONT_HERSHEY_COMPLEX_SMALL,0.75,(255,255,0))
            cv2.drawContours(im,[r.polygon],-1, (255,0,0), 1, cv2.CV_AA)

    except Exception as e:
        print "FAILED:", s, "i = ", i
        print e

    cv2.imshow("auto", im)
    cv2.waitKey(500)
    cv2.imwrite(OUT_IMG+ "/RESULT_"+ os.path.basename(s), im)
