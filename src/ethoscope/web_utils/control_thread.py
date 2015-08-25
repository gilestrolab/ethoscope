import tempfile
import os
import cv2
from threading import Thread
from ethoscope.tracking.monitor import Monitor

# Interface to V4l
from ethoscope.tracking.cameras import OurPiCameraAsync
from ethoscope.tracking.cameras import MovieVirtualCamera

# Build ROIs from greyscale image
from ethoscope.tracking.roi_builders import SleepMonitorWithTargetROIBuilder,TubeMonitorWithTargetROIBuilder, WellsMonitorWithTargetROIBuilder
from ethoscope.tracking.roi_builders  import TargetArenaTest

# the robust self learning tracker
from ethoscope.tracking.trackers import AdaptiveBGModel
from ethoscope.tracking.interactors import DefaultInteractor
from ethoscope.utils.debug import EthoscopeException
import shutil
import logging
import time

import traceback
from ethoscope.utils.io import ResultWriter


# http://localhost:9001/controls/3a92bcf229a34c4db2be733f6802094d/start
# {"time": "372894738."}


class ControlThread(Thread):

    _possible_roi_builder_classes = [TargetArenaTest]
    _ROIBuilderClass = WellsMonitorWithTargetROIBuilder
    _ROIBuilderClass_kwargs = {}

    _possible_tracker_classes = [AdaptiveBGModel]
    _TrackerClass = WellsMonitorWithTargetROIBuilder
    _TrackerClass_kwargs = {}

    _possible_interactor_classes = [DefaultInteractor]
    _InteractorClass = WellsMonitorWithTargetROIBuilder
    _InteractorClass_kwargs = {}

    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"
    _db_credentials = {"name": "ethoscope_db",
                      "user": "ethoscope",
                      "password": "ethoscope"}

    _default_monitor_info =  {
                            "last_positions":None,
                            "last_time_stamp":0,
                            "fps":0
                            }

    def _get_user_options(self):
        out = {}
        out["roi_builder"] = []
        for p in self._possible_roi_builder_classes:
            d = p.__dict__["description"]
            d["name"] = p.__name__
            out["roi_builder"].append(d)

        out["tracker"] = []
        for p in self._possible_tracker_classes:
            d = p.__dict__["description"]
            d["name"] = p.__name__
            out["tracker"].append(d)

        out["interactor"] = []
        for p in self._possible_interactor_classes:
            d = p.__dict__["description"]
            d["name"] = p.__name__
            out["interactor"].append(d)
        return out

    def _parse_user_options(self,data):

        if data is None:
            return

        data = {"roi_builder":{"name":"TargetArenaTest",
                              "arguments":{"n_cols": 2, "n_rows": 4}},
                "tracker": {"name":"AdaptiveBGModel",
                              "arguments":{}},
                "interactor": {"name":"DefaultInteractor",
                              "arguments":{}},
        }

        rb_data =  data["roi_builder"]
        self._ROIBuilderClass = eval(rb_data["name"])
        self._ROIBuilderClass_kwargs = rb_data["arguments"]

        tracker_data =  data["tracker"]
        self._TrackerClass= eval(tracker_data["name"])
        self._TrackerClass_kwargs = tracker_data["arguments"]

        interactor_data =  data["interactor"]
        self._InteractorClass= eval(interactor_data["name"])
        self._InteractorClass_kwargs= interactor_data["arguments"]



    def __init__(self, machine_id, name, version, ethogram_dir, video_file=None, data=None, *args, **kwargs):

        self._monit_args = args
        self._monit_kwargs = kwargs
        self._metadata = None

        # for FPS computation
        self._last_info_t_stamp = 0
        self._last_info_frame_idx = 0

        # We wipe off previous data
        shutil.rmtree(ethogram_dir, ignore_errors=True)
        try:
            os.makedirs(ethogram_dir)
        except OSError:
            pass

        #self._result_file = os.path.join(result_dir, self._result_db_name)
        self._video_file = video_file

        # fixme this is becoming irrelevant
        if name.find('SM')==0:
            type_of_device = 'sm'
        elif name.find('SD')==0:
            type_of_device = 'sd'
        else:
            type_of_device = 'sm'

        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")
        #todo add 'data' -> how monitor was started to metadata
        self._info = {  "status": "stopped",
                        "time": time.time(),
                        "error": None,
                        "log_file": os.path.join(ethogram_dir, self._log_file),
                        "dbg_img": os.path.join(ethogram_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "id": machine_id,
                        "name": name,
                        "version": version,
                        # type is obsolete. any device could be any type really
                        "type": type_of_device,
                        "db_name":self._db_credentials["name"],
                        "monitor_info": self._default_monitor_info,
                        "user_options": self._get_user_options()
                        }

        self._monit = None
        # self.get_user_options()

        self._parse_user_options(data)

        super(ControlThread, self).__init__()


    @property
    def info(self):
        self._update_info()
        return self._info

    def _update_info(self):
        if self._monit is None:
            return
        t = self._monit.last_time_stamp

        frame_idx = self._monit.last_frame_idx
        wall_time = time.time()
        dt = wall_time - self._last_info_t_stamp
        df = float(frame_idx - self._last_info_frame_idx)

        if self._last_info_t_stamp == 0 or dt > 0:
            f = round(df/dt, 2)
        else:
            f="NaN"
        p = self._monit.last_positions

        pos = {}
        for k,v in p.items():
            if v is None:
                continue
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

        self._last_info_t_stamp = wall_time
        self._last_info_frame_idx = frame_idx

    def run(self):

        try:
            self._info["status"] = "initialising"
            logging.info("Starting Monitor thread")

            self._info["error"] = None


            self._last_info_t_stamp = 0
            self._last_info_frame_idx = 0
            try:
                if self._video_file is None:
                    cam = OurPiCameraAsync( target_fps=20, target_resolution=(1280, 960))
                else:
                    cam = MovieVirtualCamera(self._video_file, use_wall_clock=True)

                logging.info("Building ROIs")

                roi_builder = self._ROIBuilderClass(**self._ROIBuilderClass_kwargs)
                rois = roi_builder(cam)

                logging.info("Initialising monitor")
                cam.restart()

                #todo add info about select options here
                self._metadata = {
                             "machine_id": self._info["id"],
                             "machine_name": self._info["name"],
                             "date_time": cam.start_time, #the camera start time is the reference 0
                             "frame_width":cam.width,
                             "frame_height":cam.height,
                             "version": self._info["version"]
                              }
                #the camera start time is the reference 0
                self._info["time"] = cam.start_time

                interactors = [self._InteractorClass() for _ in rois]
                kwargs = self._monit_kwargs.copy()
                kwargs.update(self._TrackerClass_kwargs)

                self._monit = Monitor(cam, self._TrackerClass, rois,
                                      interactors=interactors,
                                     *self._monit_args, **kwargs)

                logging.info("Starting monitor")

                with ResultWriter(self._db_credentials ,rois, self._metadata) as rw:
                    self._info["status"] = "running"
                    logging.info("Setting monitor status as running: '%s'" % self._info["status"] )
                    self._monit.run(rw)
                logging.info("Stopping Monitor thread")
                self.stop()
            finally:
                try:
                    cam._close()
                except:
                    pass

        except EthoscopeException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            self.stop(traceback.format_exc(e))
        except Exception as e:
            self.stop(traceback.format_exc(e))


    def stop(self, error=None):
        self._info["status"] = "stopping"
        self._info["time"] = time.time()

        logging.info("Stopping monitor")
        if not self._monit is None:
            self._monit.stop()
            self._monit = None

        self._info["status"] = "stopped"
        self._info["time"] = time.time()
        self._info["error"] = error
        self._info["monitor_info"] = self._default_monitor_info

        if error is not None:
            logging.error("Monitor closed with an error:")
            logging.error(error)
        else:
            logging.info("Monitor closed all right")

    def __del__(self):
        self.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

