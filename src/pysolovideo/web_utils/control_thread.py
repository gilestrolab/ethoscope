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
import time


# http://localhost:9001/controls/3a92bcf229a34c4db2be733f6802094d/start
# {"time": "372894738."}


class ControlThread(Thread):

    _result_dir = "results/"
    _last_img_file = "last_img.png"
    _dbg_img_file = "dbg_img.png"
    _log_file = "psv.log"
    _result_db_name = "result.db"
    _default_monitor_info =  {
                            "last_positions":None,
                            "last_time_stamp":0,
                            "result_file": None
                            }

    def __init__(self, machine_id, name, psv_dir, video_file=None, *args, **kwargs):
        self._monit_args = args
        self._monit_kwargs = kwargs

        # We wipe off previous data
        shutil.rmtree(psv_dir, ignore_errors=True)

        result_dir = os.path.join(psv_dir, self._result_dir)
        os.makedirs(result_dir)

        self._result_file = os.path.join(result_dir, self._result_db_name)
        self._video_file = video_file

        if name.find('SM')==0:
            type_of_device = 'sm'
        elif name.find('SD')==0:
            type_of_device = 'sd'
        else:
            type_of_device = 'Unknown'

        self._info = {  "status": "stopped",
                        "time": time.time(),
                        "error": None,
                        "log_file": os.path.join(psv_dir, self._log_file),
                        "dbg_img": os.path.join(psv_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(psv_dir, self._last_img_file),
                        "machine_id": machine_id,
                        "name": name,
                        "type": type_of_device,
                        "monitor_info": self._default_monitor_info,
                        }

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
        r = self._monit.result_file

        pos = {}
        for k,v in p.items():
            pos[k] = dict(v)
            pos[k]["roi_idx"] = k

        if not t is None and not r is None and not p is None:
            self._info["monitor_infos"] = {
                            "last_positions":pos,
                            "last_time_stamp":t,
                            "result_file":r
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
            self._monit.run()
            logging.info("Stopping Monitor thread")
            self.stop()

        except PSVException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            self.stop(str(e))
        except Exception as e:
            self.stop(str(e))

    def thread_init(self):
        logging.basicConfig(filename=self._info["log_file"], level=logging.INFO)

        logger = logging.getLogger()
        logger.handlers[0].stream.close()
        logger.removeHandler(logger.handlers[0])

        file_handler = logging.FileHandler(self._info["log_file"])
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(filename)s, %(lineno)d, %(funcName)s: %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        logging.info("Starting camera")

        if self._video_file is None:
            cam = V4L2Camera(0, target_fps=1, target_resolution=(560, 420))
        else:
            cam = MovieVirtualCamera(self._video_file)



        logging.info("Building ROIs")
        roi_builder = SleepMonitorWithTargetROIBuilder()
        rois = roi_builder(cam)

        logging.info("Initialising monitor")


        roi_features = [r.get_feature_dict () for r in rois]

        metadata = {}
                    # "machine_id": self._status["machine_id"]
                    #  "date_time": date_time,
                    #  "rois": roi_features,
                    #  "img":{"w":cam.width, "h":cam.height}
                    #  }

        self._monit = Monitor(cam,
                    AdaptiveBGModel,
                    rois,
                    result_file=self._result_file,
                    metadata=metadata,
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

        logging.info("Monitor closed all right")

    def __del__(self):
        self.stop()

#
# if __name__ == '__main__':
#
#
#     debug = True
#     port = 9000
#
#     machine_id = "njfhrkesngvuiodxjng"
#
#     if debug:
#         import getpass
#         DURATION = 60*60 * 100
#         if getpass.getuser() == "quentin":
#             INPUT_VIDEO = '/data/pysolo_video_samples/sleepMonitor_5days.avi'
#         elif getpass.getuser() == "asterix":
#             INPUT_VIDEO = '/data1/sleepMonitor_5days.avi'
#         else:
#             raise Exception("where is your debugging video?")
#
#         DRAW_RESULTS = True
#
#     else:
#         INPUT_VIDEO = None
#         DURATION = None
#         DRAW_RESULTS =False
#         # fixme => we should have mounted /dev/sda/ onto a custom location instead @luis @ quentin
#
#
#     PSV_DIR = "/tmp/" + "psv_" + str(port)
#
#     control = ControlThread(machine_id=machine_id, video_file=INPUT_VIDEO,
#                             psv_dir=PSV_DIR, draw_results = DRAW_RESULTS, max_duration=DURATION)
#     control.start()
#     try:
#         i = 0
#         while True:
#             i +=1
#             time.sleep(1)
#             print i, control.info["error"], control.info["status"]
#             if i == 5:
#                 control.stop()
#             if i == 6:
#                 control = ControlThread(machine_id=machine_id, video_file=INPUT_VIDEO,
#                             psv_dir=PSV_DIR, draw_results = DRAW_RESULTS, max_duration=DURATION)
#                 control.start()
#
#     finally:
#         control.stop()
#         control.join()
