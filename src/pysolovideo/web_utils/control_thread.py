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
from pysolovideo.utils.io import ResultWriter
import shutil
import logging

class ControlThread(Thread):

    _result_dir = "results/"
    _last_img_file = "last_img.png"
    _dbg_img_file = "dbg_img.png"
    _log_file = "psv.log"

    def __init__(self, machine_id, date_time, psv_dir, video_file=None, *args, **kwargs):

        # We wipe off previous data
        shutil.rmtree(psv_dir, ignore_errors=True)
        os.makedirs(psv_dir)


        self._tmp_files = {
            "last_img": os.path.join(psv_dir, self._last_img_file),
            "dbg_img": os.path.join(psv_dir, self._dbg_img_file),
            "log_file": os.path.join(psv_dir, self._log_file)
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

        metadata = {"machine_id": self._machine_id,
                     "date_time": date_time
                     }
        result_dir = os.path.join(psv_dir, self._result_dir)
        self._result_writer  = ResultWriter(dir_path=result_dir, metadata=metadata)

        self._monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    result_writer=self._result_writer,
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

    def result_files(self, partial=False):
        out = []
        print self._result_writer.file_list

        for d in self._result_writer.file_list:
            if partial or d["end"] is not None:
                out.append(d["path"])
        return out

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


