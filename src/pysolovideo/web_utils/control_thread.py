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
from pysolovideo.utils.debug import PSVException

import logging

class ControlThread(Thread):

    def __init__(self, machine_id, video_file=None, *args, **kwargs):

        self._tmp_files = {
            "last_img": tempfile.mkstemp(suffix='.png')[1],
            "dbg_img": tempfile.mkstemp(suffix='.png')[1],
            "log_file": tempfile.mkstemp(suffix='.log')[1]
        }
        self._machine_id = machine_id
        logging.basicConfig(filename=self._tmp_files["log_file"], level=logging.INFO)
        logging.info("Starting camera")


        if video_file is None:
            cam = V4L2Camera(0, target_fps=5, target_resolution=(560, 420))
        else:
            cam = MovieVirtualCamera(video_file)


        logging.info("Building ROIs")
        roi_builder = SleepMonitorWithTargetROIBuilder()
        rois = roi_builder(cam)

        logging.info("Initialising monitor")


        self._monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    *args,**kwargs
                    )

        super(ControlThread, self).__init__()

    def run(self, **kwarg):
        logging.info("Starting monitor")
        self._monit.run()


    def stop(self):
        logging.info("Stopping monitor")
        self._monit.stop()
        logging.info("Monitor closed all right")

    def __del__(self):
        self.stop()
        for k,i in self._tmp_files.items():
            try:
                os.remove(i)
            except:
                pass



    @property
    def last_time_frame(self):
        return self._monit.last_time_frame

    @property
    def log_file_path(self):
        return self._self._tmp_files["log_file"]

    @property
    def last_drawn_img(self):
        img = self._monit.last_drawn_frame
        cv2.imwrite(self._tmp_files["last_img"],img)
        return self._tmp_files["last_img"]

    @property
    def data_history(self):
        return self._monit.data_history

    @property
    def last_positions(self):
        return self._monit.last_positions

    def format_psv_error(self, e):

        if isinstance(e, PSVException):
            cv2.imwrite(self._tmp_files["dbg_img"], e.img)
            out = {"PSV_ERROR":[str(e), self._tmp_files["dbg_img"]]}
        else:
            out = {type(e).__name__:str(e)}

        out["log_file"] = self._tmp_files['log_file']
        return out


