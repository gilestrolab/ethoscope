import pickle
import cv2
import time
from ethoscope.core.roi import ROI
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.core.monitor import Monitor

from ethoscope.core.tracking_unit import TrackingUnit
from ethoscope.hardware.input.cameras import OurPiCameraAsync
import logging
import multiprocessing

class DummyFrameGrabber(multiprocessing.Process):
    def __init__(self, target_fps, target_resolution, queue, stop_queue):
        self._queue = queue
        self._stop_queue = stop_queue
        self._target_fps = target_fps
        self._target_resolution = target_resolution
        super(DummyFrameGrabber, self).__init__()
    def run(self):
        try:
            import numpy as np

            while True:
                if not self._stop_queue.empty():
                    logging.warning("The stop queue is not empty. Stop acquiring frames")
                    self._stop_queue.get()
                    self._stop_queue.task_done()
                    logging.warning("Stop Task Done")
                    break

                time.sleep(1)
                out = np.zeros((self._target_resolution[1], self._target_resolution[0]), np.uint8)
                self._queue.put(out)

        finally:
            logging.warning("Closing frame grabber process")
            self._stop_queue.close()
            self._queue.close()
            logging.warning("Camera Frame grabber stopped acquisition cleanly")

class TestCam(OurPiCameraAsync):
    _frame_grabber_class = DummyFrameGrabber
    def __getstate__(self):
        return {"resolution":self._resolution}
    def __setstate__(self,state):
        print state

rois = [ROI([(1,1),(2,3),(3,10),(11,5)], 1),
            ROI([(1,1),(2,3),(3,10),(11,5)], 2)]

cam = TestCam()
# for t,f in cam:
#     cv2.imshow("test",f)
#     cv2.waitKey(10)

obj = Monitor(cam, AdaptiveBGModel, rois)



#
#
with open("/tmp/pickled.pkl", "w") as f:
    pickle.dump(obj, f)
# #
# with open("/tmp/pickled.pkl", "r") as f2:
#     obj_bis = pickle.load(f2)
#     print obj_bis
# #
# #
#

