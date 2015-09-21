__author__ = 'quentin'

from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder
import cv2
import unittest
import os

images = {"bright_targets":"./img/bright_targets.png",
           "dark_targets": "./img/dark_targets.png"}


LOG_DIR = "./test_logs/"

class TestTargetROIBuilder(unittest.TestCase):

    roi_builder = SleepMonitorWithTargetROIBuilder()

    def _draw(self,img, rois):
        for r in rois:
            cv2.drawContours(img,r.polygon,-1, (255,255,0), 2, cv2.CV_AA)


    def _test_one_img(self,path, out):

        img = cv2.imread(path)

        rois = self.roi_builder.build(img)
        self._draw(img, rois)
        cv2.imwrite(out,img)
        self.assertEquals(len(rois),20)


    def test_all(self):
        for k,i in images.iteritems():
            out = os.path.join(LOG_DIR,k+".png")
            self._test_one_img(i,out)




