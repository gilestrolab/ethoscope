import tempfile
import os
from threading import Thread
import traceback
import shutil
import logging
import time

import cv2



# Interface to V4l
from ethoscope.hardware.input.cameras import OurPiCameraAsync, MovieVirtualCamera
# Build ROIs from greyscale image

from ethoscope.roi_builders.target_roi_builder import  OlfactionAssayROIBuilder, SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder
from ethoscope.roi_builders.roi_builders import  DefaultROIBuilder
from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import NullDrawer, DefaultDrawer

# the robust self learning tracker
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.interactors.interactors import DefaultInteractor
from ethoscope.interactors.sleep_depriver_interactor import SleepDepInteractor, SystematicSleepDepInteractor, ExperimentalSleepDepInteractor
from ethoscope.interactors.fake_sleep_dep_interactor import FakeSleepDepInteractor, FakeSystematicSleepDepInteractor

from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.io import ResultWriter, SQLiteResultWriter
from ethoscope.utils.description import DescribedObject


class ExperimentalInformations(DescribedObject):
        _description  = {   "overview": "Optional information about your experiment",
                            "arguments": [
                                    {"type": "str", "name":"name", "description": "Who are you?","default":""},
                                    {"type": "str", "name":"location", "description": "Where is your device","default":""}
                                   ]}
        def __init__(self,name="",location=""):
            self._info_dic = {"name":name,
                              "location":location}
        @property
        def info_dic(self):
            return self._info_dic


class ControlThread(Thread):
    _evanescent = False
    _option_dict = {
        "roi_builder":{
                "possible_classes":[DefaultROIBuilder, SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder, OlfactionAssayROIBuilder],
            },
        "tracker":{
                "possible_classes":[AdaptiveBGModel],
            },
        "interactor":{
                        "possible_classes":[DefaultInteractor,SleepDepInteractor,
                                            SystematicSleepDepInteractor,
                                            ExperimentalSleepDepInteractor,
                                            FakeSystematicSleepDepInteractor],
                    },
        "drawer":{
                        "possible_classes":[DefaultDrawer, NullDrawer],
                    },
        "camera":{
                        "possible_classes":[OurPiCameraAsync, MovieVirtualCamera],
                    },
        "result_writer":{
                        "possible_classes":[ResultWriter, SQLiteResultWriter],
                },
        "experimental_info":{
                        "possible_classes":[ExperimentalInformations],
                }
     }
    for k in _option_dict:
        _option_dict[k]["class"] =_option_dict[k]["possible_classes"][0]
        _option_dict[k]["kwargs"] ={}


    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"
    _db_credentials = {"name": "ethoscope_db",
                      "user": "ethoscope",
                      "password": "ethoscope"}

    _default_monitor_info =  {
                            #fixme, not needed
                            "last_positions":None,

                            "last_time_stamp":0,
                            "fps":0
                            }
    def __init__(self, machine_id, name, version, ethoscope_dir, data=None, *args, **kwargs):

        self._monit_args = args
        self._monit_kwargs = kwargs
        self._metadata = None

        # for FPS computation
        self._last_info_t_stamp = 0
        self._last_info_frame_idx = 0

        # We wipe off previous data
        shutil.rmtree(ethoscope_dir, ignore_errors=True)
        try:
            os.makedirs(ethoscope_dir)
        except OSError:
            pass

        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")
        #todo add 'data' -> how monitor was started to metadata
        self._info = {  "status": "stopped",
                        "time": time.time(),
                        "error": None,
                        "log_file": os.path.join(ethoscope_dir, self._log_file),
                        "dbg_img": os.path.join(ethoscope_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "id": machine_id,
                        "name": name,
                        "version": version,
                        "db_name":self._db_credentials["name"],
                        "monitor_info": self._default_monitor_info,
                        #"user_options": self._get_user_options(),
                        "experimental_info": {}
                        }
        self._monit = None

        self._parse_user_options(data)


        DrawerClass = self._option_dict["drawer"]["class"]
        drawer_kwargs = self._option_dict["drawer"]["kwargs"]
        self._drawer = DrawerClass(**drawer_kwargs)


        super(ControlThread, self).__init__()


    @property
    def info(self):
        self._update_info()
        return self._info


    @classmethod
    def user_options(cls):
        out = {}
        for key, value in cls._option_dict.iteritems():
            out[key] = []
            for p in value["possible_classes"]:
                try:
                    d = p.__dict__["_description"]
                except KeyError:
                    continue

                d["name"] = p.__name__
                out[key].append(d)
        out_currated = {}

        for key, value in out.iteritems():
            if len(value) >0:
                out_currated[key] = value

        return out_currated


    def _parse_one_user_option(self,field, data):

        try:
            subdata = data[field]
        except KeyError:
            logging.warning("No field %s, using default" % field)
            return None, {}

        Class = eval(subdata["name"])
        kwargs = subdata["arguments"]

        return Class, kwargs


    def _parse_user_options(self,data):

        if data is None:
            return
        #FIXME DEBUG
        logging.warning("Starting control thread with data:")
        logging.warning(str(data))

        for key in self._option_dict.iterkeys():

            Class, kwargs = self._parse_one_user_option(key, data)
            # when no field is present in the JSON config, we get the default class

            if Class is None:

                self._option_dict[key]["class"] = self._option_dict[key]["possible_classes"][0]
                self._option_dict[key]["kwargs"] = {}
                continue

            self._option_dict[key]["class"] = Class
            self._option_dict[key]["kwargs"] = kwargs



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



        if t is not None:# and p is not None:
            self._info["monitor_info"] = {
                            # "last_positions":pos,
                            "last_time_stamp":t,
                            "fps": f
                            }

        f = self._drawer.last_drawn_frame
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

                CameraClass = self._option_dict["camera"]["class"]

                camera_kwargs = self._option_dict["camera"]["kwargs"]

                ROIBuilderClass= self._option_dict["roi_builder"]["class"]
                roi_builder_kwargs = self._option_dict["roi_builder"]["kwargs"]

                InteractorClass= self._option_dict["interactor"]["class"]
                interactor_kwargs = self._option_dict["interactor"]["kwargs"]
                HardWareInterfaceClass =  InteractorClass.__dict__["_hardwareInterfaceClass"]

                TrackerClass= self._option_dict["tracker"]["class"]
                tracker_kwargs = self._option_dict["tracker"]["kwargs"]

                ResultWriterClass = self._option_dict["result_writer"]["class"]
                result_writer_kwargs = self._option_dict["result_writer"]["kwargs"]


                # from picamera.array import PiRGBArray
                # from picamera import PiCamera
                #
                # with  PiCamera() as capture:
                #     logging.warning(capture)
                #     capture.resolution = (1280, 960)
                #
                #     capture.framerate = 20
                #     raw_capture = PiRGBArray(capture, size=(1280, 960))
                #
                #     for i, frame in enumerate(capture.capture_continuous(raw_capture, format="bgr", use_video_port=True)):
                #         raw_capture.truncate(0)
                #         # out = np.copy(frame.array)
                #         out = cv2.cvtColor(frame.array, cv2.COLOR_BGR2GRAY)
                #         logging.warning(str((i, out.shape)))
                #         if i > 10:
                #             break
                #
                #
                # #raise Exception("Mock camera init")

                cam = CameraClass(**camera_kwargs)


                roi_builder = ROIBuilderClass(**roi_builder_kwargs)
                rois = roi_builder.build(cam)

                logging.info("Initialising monitor")
                cam.restart()
                #the camera start time is the reference 0


                ExpInfoClass = self._option_dict["experimental_info"]["class"]
                exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]
                self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic
                self._info["time"] = cam.start_time


                self._metadata = {
                             "machine_id": self._info["id"],
                             "machine_name": self._info["name"],
                             "date_time": cam.start_time, #the camera start time is the reference 0
                             "frame_width":cam.width,
                             "frame_height":cam.height,
                             "version": self._info["version"]["id"],
                             "experimental_info": str(self._info["experimental_info"]),
                             "selected_options": str(self._option_dict)
                              }




                hardware_interface = HardWareInterfaceClass()
                interactors = [InteractorClass(hardware_interface ,**interactor_kwargs) for _ in rois]
                kwargs = self._monit_kwargs.copy()
                kwargs.update(tracker_kwargs)

                self._monit = Monitor(cam, TrackerClass, rois,
                                      interactors=interactors,
                                     *self._monit_args, **kwargs)

                logging.info("Starting monitor")

                #fixme
                with ResultWriter(self._db_credentials, rois, self._metadata, take_frame_shots=True) as rw:
                    self._info["status"] = "running"
                    logging.info("Setting monitor status as running: '%s'" % self._info["status"] )
                    self._monit.run(rw,self._drawer)
                logging.info("Stopping Monitor thread")
                self.stop()

            finally:
                try:
                    cam._close()
                except:
                    logging.warning("Could not close camera properly")
                    pass

        except EthoscopeException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            self.stop(traceback.format_exc(e))
        except Exception as e:
            self.stop(traceback.format_exc(e))

        #for testing purposes
        if self._evanescent:
            import os
            del self._drawer
            self.stop()
            os._exit(0)


    def stop(self, error=None):
        self._info["status"] = "stopping"
        self._info["time"] = time.time()
        self._info["experimental_info"] = {}

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

    def set_evanescent(self, value=True):
        self._evanescent = value

