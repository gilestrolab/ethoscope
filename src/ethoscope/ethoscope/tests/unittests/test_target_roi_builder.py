__author__ = 'quentin'

import cv2
import unittest
import os
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder


try:
    from cv2.cv import CV_AA as LINE_AA
except ImportError:
    from cv2 import LINE_AA

# Get the absolute path to the test images
import pathlib
test_dir = pathlib.Path(__file__).parent.parent / "static_files" / "img"
images = {"bright_targets": str(test_dir / "bright_targets.png"),
          "dark_targets": str(test_dir / "dark_targets.png")}


LOG_DIR = "./test_logs/"

class TestTargetROIBuilder(unittest.TestCase):

    def setUp(self):
        self.roi_builder = FileBasedROIBuilder(template_name="sleep_monitor_20tube")

    def _draw(self,img, rois):
        for r in rois:
            cv2.drawContours(img,r.polygon,-1, (255,255,0), 2, LINE_AA)


    def _test_one_img(self,path, out):

        img = cv2.imread(path)

        reference_points, rois = self.roi_builder.build(img)
        self._draw(img, rois)
        cv2.imwrite(out,img)
        self.assertEqual(len(rois),20)


    def test_all(self):
        # Ensure test logs directory exists
        os.makedirs(LOG_DIR, exist_ok=True)
        
        for k,i in list(images.items()):
            out = os.path.join(LOG_DIR,k+".png")
            print(out)
            self._test_one_img(i,out)




