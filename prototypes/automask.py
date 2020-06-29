__author__ = 'quentin'



from ethoscope.tracking.roi_builders import SleepDepROIBuilder
from ethoscope.tracking.cameras import MovieVirtualCamera
from ethoscope.tracking.monitor import Monitor
from ethoscope.tracking.trackers import AdaptiveBGModel
import glob
import cv2
import os

AUTO_ROI_DATA = "/data/pysolo_video_samples/auto_rois/"
OUT_IMG = "/home/quentin/Desktop/tmp/"
shots = glob.glob(AUTO_ROI_DATA + "*.png")


roi_builder = SleepDepROIBuilder()


for scale in [1, 0.5, 0.75, 1.25, 1.5]:
    for i, s in enumerate(reversed(sorted(shots))):
        orig_im = cv2.imread(s)
        im = cv2.resize(orig_im, (0,0), fx=scale, fy=scale)

        cv2.imshow("auto", im)
        cv2.waitKey(1)
        try:
            rois = roi_builder(im)


            for r in rois:
                cv2.putText(im, str(r.idx+1), r.offset, cv2.FONT_HERSHEY_COMPLEX_SMALL,0.75,(255,255,0))
                cv2.drawContours(im,[r.polygon],-1, (255,0,0), 1, cv2.CV_AA)
                cv2.imwrite(OUT_IMG+ "SCALE=" + str(100 * scale)+"_RESULT_"+ os.path.basename(s), im)

        except Exception as e:
            print("FAILED:", s, "i = ", i)
            print(e)
            cv2.imwrite(OUT_IMG+ "FAILED_SCALE=" + str(100 * scale)+"_RESULT_"+ os.path.basename(s), im)
            # cv2.waitKey(-1)
            # exit()

        cv2.imshow("auto", im)
        cv2.waitKey(500)

