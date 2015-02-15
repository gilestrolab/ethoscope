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
import shutil
import logging
import time
# to add pkg version in metadata
import pkg_resources
import glob
import traceback
from pysolovideo.utils.io import ResultWriter
from pysolovideo.utils.io import SQLiteResultWriter

# http://localhost:9001/controls/3a92bcf229a34c4db2be733f6802094d/start
# {"time": "372894738."}


class ControlThread(Thread):


    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "psv.log"
    _mysql_db_name = "psv_db"
    _default_monitor_info =  {
                            "last_positions":None,
                            "last_time_stamp":0,
                            "fps":0
                            }

    def __init__(self, machine_id, name, psv_dir, video_file=None, *args, **kwargs):
        self._monit_args = args
        self._monit_kwargs = kwargs
        self._metadata = None
        # We wipe off previous data
        shutil.rmtree(psv_dir, ignore_errors=True)


        # self._result_dir = os.path.join(psv_dir, self._result_dir_basename)
        try:
            os.makedirs(psv_dir)
        except OSError:
            pass

        #self._result_file = os.path.join(result_dir, self._result_db_name)
        self._video_file = video_file

        if name.find('SM')==0:
            type_of_device = 'sm'
        elif name.find('SD')==0:
            type_of_device = 'sd'
        else:
            type_of_device = 'Unknown'

        self._tmp_dir = tempfile.mkdtemp(prefix="psv_")
        self._info = {  "status": "stopped",
                        "time": time.time(),
                        "error": None,
                        "log_file": os.path.join(psv_dir, self._log_file),
                        "dbg_img": os.path.join(psv_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "machine_id": machine_id,
                        "name": name,
                        "type": type_of_device,
                        "db_name":self._mysql_db_name,
                        "monitor_info": self._default_monitor_info
                        }

        logging.basicConfig(filename=self._info["log_file"], level=logging.INFO)

        logger = logging.getLogger()
        logger.handlers[0].stream.close()
        logger.removeHandler(logger.handlers[0])

        file_handler = logging.FileHandler(self._info["log_file"])
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(filename)s, %(lineno)d, %(funcName)s: %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        self._monit = None
        super(ControlThread, self).__init__()

    @property
    def info(self):
        self._update_info()
        return self._info

    def _update_info(self):
        if self._monit is None:
            return
        t = self._monit.last_time_stamp
        p = self._monit.last_positions
        f = self._monit.fps

        pos = {}
        for k,v in p.items():
            pos[k] = dict(v)
            pos[k]["roi_idx"] = k

        if t is not None and p is not None:
            self._info["monitor_info"] = {
                            "last_positions":pos,
                            "last_time_stamp":t,
                            "fps": f
                            }

        f = self._monit.last_drawn_frame
        if not f is None:
            cv2.imwrite(self._info["last_drawn_img"], f)


    def run(self):
        try:
            logging.info("Starting Monitor thread")
            self._info["status"] = "running"
            self._info["error"] = None
            self._info["time"] = time.time()
            self.thread_init()
            logging.info("Starting monitor")

            with ResultWriter(self._mysql_db_name ,self._metadata) as rw:
                self._monit.run(rw)
                logging.info("Stopping Monitor thread")
                self.stop()

        except PSVException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            self.stop(traceback.format_exc(e))
        except Exception as e:
            self.stop(traceback.format_exc(e))

    def thread_init(self):
        logging.info("Starting camera")

        if self._video_file is None:
            cam = V4L2Camera(0, target_fps=10, target_resolution=(1280, 920))
        else:
            cam = MovieVirtualCamera(self._video_file)


        logging.info("Building ROIs")
        roi_builder = SleepMonitorWithTargetROIBuilder()
        rois = roi_builder(cam)

        logging.info("Initialising monitor")



        self._metadata = {
                     "machine_id": self._info["machine_id"],
                     "date_time": self._info["time"],
                     "frame_width":cam.width,
                     "frame_height":cam.height,
                      "psv_version": pkg_resources.get_distribution("pysolovideo").version
                      }


        self._monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    *self._monit_args,
                    **self._monit_kwargs
                    )

    def stop(self, error=None):

        logging.info("Stopping monitor")
        if not self._monit is None:
            self._monit.stop()
            self._monit = None


        self._info["status"] = "stopped"
        self._info["time"] = time.time()
        self._info["error"] = error
        self._info["monitor_infos"] = self._default_monitor_info
        if error is not None:
            logging.error("Monitor closed with an error:")
            logging.error(error)
        else:
            logging.info("Monitor closed all right")

    def __del__(self):
        self.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
