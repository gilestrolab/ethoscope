import pickle
import cv2
import time
from ethoscope.hardware.interfaces.interfaces import  HardwareConnection
from ethoscope.hardware.interfaces.sleep_depriver_interface import SleepDepriverInterface

obj = HardwareConnection(SleepDepriverInterface)
with open("/tmp/pickled.pkl", "w") as f:
    pickle.dump(obj, f)
obj.stop()

with open("/tmp/pickled.pkl", "r") as f2:
    obj_bis = pickle.load(f2)
print("stp")
obj_bis.stop()
print("ok")
#
# from ethoscope.core.tracking_unit import TrackingUnit
# from ethoscope.utils.io import ResultWriter, SQLiteResultWriter
# from ethoscope.hardware.input.cameras import OurPiCameraAsync
# import logging
# import multiprocessing
#
# class DummyFrameGrabber(multiprocessing.Process):
#     def __init__(self, target_fps, target_resolution, queue, stop_queue):
#         self._queue = queue
#         self._stop_queue = stop_queue
#         self._target_fps = target_fps
#         self._target_resolution = target_resolution
#         super(DummyFrameGrabber, self).__init__()
#     def run(self):
#         try:
#             cap = cv2.VideoCapture("/data/ethoscope_ref_videos/2016-03-07_21-05-28_w1118iso_validation/2016-03-07_21-05-28_w1118iso_validation.mp4")
#             while True:
#                 if not self._stop_queue.empty():
#                     logging.warning("The stop queue is not empty. Stop acquiring frames")
#                     self._stop_queue.get()
#                     self._stop_queue.task_done()
#                     logging.warning("Stop Task Done")
#                     break
#                 _, out = cap.read()
#                 out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
#                 self._queue.put(out)
#
#         finally:
#             logging.warning("Closing frame grabber process")
#             self._stop_queue.close()
#             self._queue.close()
#             logging.warning("Camera Frame grabber stopped acquisition cleanly")
#
# class TestCam(OurPiCameraAsync):
#     _frame_grabber_class = DummyFrameGrabber

# rois = [ROI([(1,1),(2,3),(3,10),(11,5)], 1),
#             ROI([(1,1),(2,3),(3,10),(11,5)], 2)]

#
# cam = TestCam()
# for t,f in cam:
#     if t >3000:
#         break
#
#
# rois = SleepMonitorWithTargetROIBuilder().build(cam)
# cam.restart()
#
# mon = Monitor(cam, AdaptiveBGModel, rois)
# dr = DefaultDrawer(draw_frames=True)
# md = {"a": 10, "b": 30}
# with SQLiteResultWriter("/tmp/test.db",rois, metadata=md) as rw:
#     obj = {"monitor": mon,
#            "drawer": dr,
#            "result_writer": rw
#            }

#
# monitor = obj_bis["monitor"]
# drawer= obj_bis["drawer"]
#
# try:
#     with obj_bis["result_writer"] as result_writer:
#         monitor.run(result_writer, drawer = drawer)
# except KeyboardInterrupt:
#     mon.stop()
# print "has run now try to append data"
#
# time.sleep(5)
# with open("/tmp/pickled.pkl", "r") as f2:
#     obj_ter = pickle.load(f2)
#
# monitor = obj_ter["monitor"]
# drawer= obj_ter["drawer"]
#
# try:
#     with obj_ter["result_writer"] as result_writer:
#         monitor.run(result_writer, drawer = drawer)
# except KeyboardInterrupt:
#     mon.stop()
