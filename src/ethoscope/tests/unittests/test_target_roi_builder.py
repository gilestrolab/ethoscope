__author__ = 'quentin'

import cv2
import unittest
import os
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder


try:
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import LINE_AA

images = {"bright_targets":"../static_files/img/bright_targets.png",
           "dark_targets": "../static_files/img/dark_targets.png"}


LOG_DIR = "./test_logs/"

class TestTargetROIBuilder(unittest.TestCase):

    roi_builder = SleepMonitorWithTargetROIBuilder()

    def _draw(self,img, rois):
        for r in rois:
            cv2.drawContours(img,r.polygon,-1, (255,255,0), 2, LINE_AA)


    def _test_one_img(self,path, out):

        img = cv2.imread(path)

        rois = self.roi_builder.build(img)
        self._draw(img, rois)
        cv2.imwrite(out,img)
        self.assertEqual(len(rois),20)


    def test_all(self):

        for k,i in list(images.items()):
            out = os.path.join(LOG_DIR,k+".png")
            print(out)
            self._test_one_img(i,out)




