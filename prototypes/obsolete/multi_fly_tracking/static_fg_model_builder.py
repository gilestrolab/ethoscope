__author__ = 'quentin'

from ethoscope.core.monitor import Monitor
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel, ObjectModel
from ethoscope.utils.io import SQLiteResultWriter
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.drawers.drawers import DefaultDrawer
import cv2
import numpy as np
from math import log10
import os
# You can also load other types of ROI builder. This one is for 20 tubes (two columns of ten rows)
from ethoscope.roi_builders.target_roi_builder import SleepMonitorWithTargetROIBuilder

class ObjectModelImageSaver(ObjectModel):
    _path = open("/tmp/fly_snapshots/positive.csv","w")
    _idx = 0

    def update(self, img, contour,time):
        self._last_updated_time = time
        self._ring_buff[self._ring_buff_idx] = self.compute_features(img,contour)

        self._ring_buff_idx += 1

        if self._ring_buff_idx == self._history_length:
            self._is_ready = True
            self._ring_buff_idx = 0
        self._draw_match(img,contour)



    def _draw_match(self, img, contour):


        x,y,w,h = cv2.boundingRect(contour)

        if self._roi_img_buff is None or np.any(self._roi_img_buff.shape < img.shape[0:2]) :
            # dynamically reallocate buffer if needed
            self._img_buff_shape[1] =  max(self._img_buff_shape[1],w)
            self._img_buff_shape[0] =  max(self._img_buff_shape[0], h)

            self._roi_img_buff = np.zeros(self._img_buff_shape, np.uint8)
            self._mask_img_buff = np.zeros_like(self._roi_img_buff)

        sub_mask = self._mask_img_buff[0 : h, 0 : w]

        sub_grey = self._roi_img_buff[ 0 : h, 0: w]

        cv2.cvtColor(img[y : y + h, x : x + w, :],cv2.COLOR_BGR2GRAY,sub_grey)
        if self._idx % 10 == 0:
            sub_grey = cv2.resize(sub_grey, (24,24))
            x_arrstr = np.char.mod('%i', sub_grey)
            out = ", ".join(list(x_arrstr.flatten())) + "\n"
            self._path.write(out)
            #cv2.imwrite(os.path.join(self._path, "positive_%09d.png" % (self._idx)), sub_grey)
        self._idx += 1




class ABGMImageSaver(AdaptiveBGModel):

    fg_model = ObjectModelImageSaver()



# change these three variables according to how you name your input/output files
INPUT_VIDEO = "/home/quentin/comput/ethoscope-git/src/ethoscope/tests/integration_server_tests/test_video.mp4"
OUTPUT_VIDEO = "/tmp/my_output.avi"
OUTPUT_DB = "/tmp/results.db"

# We use a video input file as if it was a "camera"
cam = MovieVirtualCamera(INPUT_VIDEO)

# here, we generate ROIs automatically from the targets in the images
roi_builder = SleepMonitorWithTargetROIBuilder()

rois = roi_builder.build(cam)
# Then, we go back to the first frame of the video
cam.restart()

# we use a drawer to show inferred position for each animal, display frames and save them as a video
drawer = DefaultDrawer(OUTPUT_VIDEO, draw_frames = True)
# We build our monitor
monitor = Monitor(cam, ABGMImageSaver, rois)


# Now everything ius ready, we run the monitor with a result writer and a drawer
with SQLiteResultWriter(OUTPUT_DB, rois) as rw:
    monitor.run(rw, drawer)

