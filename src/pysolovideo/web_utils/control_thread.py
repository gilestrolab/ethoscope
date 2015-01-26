import tempfile
import os
import cv2
from threading import Thread
from pysolovideo.tracking.monitor import Monitor

# Interface to V4l
from pysolovideo.tracking.cameras import V4L2Camera
from pysolovideo.tracking.cameras import MovieVirtualCamera

# Build ROIs from greyscale image
from pysolovideo.tracking.roi_builders import SleepMonitorWithTargetROIBuilder

# the robust self learning tracker
from pysolovideo.tracking.trackers import AdaptiveBGModel

class ControlThread(Thread):

    def __init__(self, *args, **kwargs):
        self._tmp_img_name = file_name = tempfile.mkstemp(suffix='.png')[1]

        cam = MovieVirtualCamera('/data/pysolo_video_samples/sleepMonitor_5days.avi')
        #cam = V4L2Camera(0, target_fps=5, target_resolution=(560, 420))

        roi_builder = SleepMonitorWithTargetROIBuilder()

        rois = roi_builder(cam)

        self._monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    out_file='out', # save a csv out
                    draw_results = True,
                    
                    )

        super(ControlThread, self).__init__()

    def run(self, **kwarg):
        self._monit.run()

    def stop(self):
        self._monit.stop()

    def __del__(self):
        self.stop()
        os.remove(self._tmp_img_name)

    @property
    def last_time_frame(self):
        return self._monit.last_time_frame

    @property
    def last_drawn_img(self):
        img = self._monit.last_drawn_frame
        cv2.imwrite(self._tmp_img_name,img)
        return self._tmp_img_name

    @property
    def data_history(self):
        return self._monit.data_history

    @property
    def last_positions(self):
        return self._monit.last_positions