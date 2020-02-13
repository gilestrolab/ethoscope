import tempfile
import os
import traceback
import shutil
import logging
import time
import re
import cv2
from threading import Thread
import pickle
import secrets

import trace
from ethoscope.hardware.input.cameras import OurPiCameraAsync, MovieVirtualCamera, DummyPiCameraAsync, V4L2Camera
from ethoscope.roi_builders.target_roi_builder import OlfactionAssayROIBuilder, SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder, ElectricShockAssayROIBuilder
from ethoscope.roi_builders.roi_builders import  DefaultROIBuilder
from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import NullDrawer, DefaultDrawer
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.hardware.interfaces.interfaces import HardwareConnection, EthoscopeSensor
from ethoscope.stimulators.stimulators import DefaultStimulator
from ethoscope.stimulators.sleep_depriver_stimulators import SleepDepStimulator, OptomotorSleepDepriver, ExperimentalSleepDepStimulator, MiddleCrossingStimulator, OptomotorSleepDepriverSystematic
from ethoscope.stimulators.odour_stimulators import DynamicOdourSleepDepriver, MiddleCrossingOdourStimulator, MiddleCrossingOdourStimulatorFlushed
from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator

from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.io import ResultWriter, SQLiteResultWriter
from ethoscope.utils.description import DescribedObject
from ethoscope.web_utils.helpers import isMachinePI, hasPiCamera, isExperimental, get_machine_name

class ExperimentalInformation(DescribedObject):
    
        _description  = {   "overview": "Optional information about your experiment",
                            "arguments": [
                                    {"type": "str", "name": "name", "description": "Who are you?", "default" : "", "asknode" : "users", "required" : "required"},
                                    {"type": "str", "name": "location", "description": "Where is your device","default" : "", "asknode" : "incubators"},
                                    {"type": "str", "name": "code", "description": "Would you like to add any code to the resulting filename?", "default" : ""},
                                    {"type": "str", "name": "sensor", "description": "url to access the relevant ethoscope sensor", "default": "", "asknode" : "sensors", "hidden" : "true"}

                                   ]}
        def __init__(self, name="", location="", code="", sensor=""):
            self._check_code(code)
            self._info_dic = {"name":name,
                              "location":location,
                              "code":code,
                              "sensor":sensor}

        def _check_code(self, code):
            r = re.compile(r"[^a-zA-Z0-9-]")
            clean_code = r.sub("",code)
            if len(code) != len(clean_code):
                logging.error("the code in the video name contains unallowed characters")
                raise Exception("Code contains special characters. Please use only letters, digits or -")



        @property
        def info_dic(self):
            return self._info_dic


class ControlThread(Thread):
    """
    The versatile control thread
    From this thread, the PI passes option to the node.
    Note: Options are passed and shown only if the remote class contains a "_description" field!
    """
    _evanescent = False
    _option_dict = {
        "roi_builder":{
                "possible_classes":[DefaultROIBuilder, SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder, OlfactionAssayROIBuilder, ElectricShockAssayROIBuilder],
            },
        "tracker":{
                "possible_classes":[AdaptiveBGModel],
            },
        "interactor":{
                        "possible_classes":[DefaultStimulator, 
                                            SleepDepStimulator,
                                            OptomotorSleepDepriver,
                                            MiddleCrossingStimulator,
                                            #SystematicSleepDepInteractor,
                                            ExperimentalSleepDepStimulator,
                                            #GearMotorSleepDepStimulator,
                                            #DynamicOdourDeliverer,
                                            DynamicOdourSleepDepriver,
                                            OptoMidlineCrossStimulator,
                                            OptomotorSleepDepriverSystematic,
                                            MiddleCrossingOdourStimulator,
                                            MiddleCrossingOdourStimulatorFlushed
                                            ],
                    },
        "drawer":{
                        "possible_classes":[DefaultDrawer, NullDrawer],
                    },
        "camera":{
                        "possible_classes":[OurPiCameraAsync, MovieVirtualCamera, DummyPiCameraAsync, V4L2Camera],
                    },
        "result_writer":{
                        "possible_classes":[ResultWriter, SQLiteResultWriter],
                },
        "experimental_info":{
                        "possible_classes":[ExperimentalInformation],
                }
     }
    
    #some classes do not need to be offered as choices to the user in normal conditions
    #these are shown only if the machine is not a PI
    _is_a_rPi = isMachinePI() and hasPiCamera() and not isExperimental()
    _hidden_options = {'camera', 'result_writer'}
    
    for k in _option_dict:
        _option_dict[k]["class"] =_option_dict[k]["possible_classes"][0]
        _option_dict[k]["kwargs"] ={}


    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"
    #give the database an ethoscope specific name
    #future proof in case we want to use a remote server
    _db_credentials = {"name": "%s_db" % get_machine_name(),
                      "user": "ethoscope",
                      "password": "ethoscope"}

    _default_monitor_info =  {
                            #fixme, not needed
                            "last_positions":None,

                            "last_time_stamp":0,
                            "fps":0
                            }
    _persistent_state_file = "/var/cache/ethoscope/persistent_state.pkl"

    def __init__(self, machine_id, name, version, ethoscope_dir, data=None, *args, **kwargs):

        self._monit_args = args
        self._monit_kwargs = kwargs
        self._metadata = None

        # for FPS computation
        self._last_info_t_stamp = 0
        self._last_info_frame_idx = 0


        # We wipe off previous logs and debug images
        try:
            os.remove(os.path.join(ethoscope_dir, self._log_file))
        except OSError:
            pass
        try:
            os.remove(os.path.join(ethoscope_dir, self._dbg_img_file))
        except OSError:
            pass

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

    @property
    def was_interrupted(self):
        return os.path.exists(self._persistent_state_file)


    @classmethod
    def user_options(self):
        out = {}
        for key, value in list(self._option_dict.items()):
            # check if the options for the remote class will be visible
            # they will be visible only if they have a description, and if we are on a PC or they are not hidden
            if (self._is_a_rPi and key not in self._hidden_options) or not self._is_a_rPi:
                out[key] = []
                for p in value["possible_classes"]:
                    try:
                        d = p.__dict__["_description"]
                    except KeyError:
                        continue

                    d["name"] = p.__name__
                    out[key].append(d)

        out_curated = {}
        for key, value in list(out.items()):
            if len(value) >0:
                out_curated[key] = value

        return out_curated


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

        for key in list(self._option_dict.keys()):

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

        frame = self._drawer.last_drawn_frame
        if frame is not None:
            cv2.imwrite(self._info["last_drawn_img"], frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])


        self._last_info_t_stamp = wall_time
        self._last_info_frame_idx = frame_idx


    def _start_tracking(self, camera, result_writer, rois, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs):

        #Here the stimulator passes args. Hardware connection was previously open as thread.
        stimulators = [StimulatorClass(hardware_connection, **stimulator_kwargs) for _ in rois]
        
        kwargs = self._monit_kwargs.copy()
        kwargs.update(tracker_kwargs)

        # todo: pickle hardware connection, camera, rois, tracker class, stimulator class,.
        # then rerun stimulators and Monitor(......)
        self._monit = Monitor(camera, TrackerClass, rois,
                              stimulators=stimulators,
                              *self._monit_args)
        self._info["status"] = "running"
        logging.info("Setting monitor status as running: '%s'" % self._info["status"])

        self._monit.run(result_writer, self._drawer)

    def _has_pickle_file(self):
        """
        """
        return os.path.exists(self._persistent_state_file)

    def _set_tracking_from_pickled(self):
        """
        """
        with open(self._persistent_state_file, "rb") as f:
                time.sleep(15)
                return pickle.load(f)

    def _save_pickled_state(self, camera, result_writer, rois, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, running_info):
        """
        note that cv2.videocapture is not a serializable object and cannot be pickled
        """

        tpl = (camera, result_writer, rois, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs, running_info)


        if not os.path.exists(os.path.dirname(self._persistent_state_file)):
            logging.warning("No cache dir detected. making one")
            os.makedirs(os.path.dirname(self._persistent_state_file))

        with open(self._persistent_state_file, "wb") as f:
            return pickle.dump(tpl, f)

    def _set_tracking_from_scratch(self):
        """
        """
        CameraClass = self._option_dict["camera"]["class"]
        camera_kwargs = self._option_dict["camera"]["kwargs"]

        ROIBuilderClass = self._option_dict["roi_builder"]["class"]
        roi_builder_kwargs = self._option_dict["roi_builder"]["kwargs"]

        StimulatorClass = self._option_dict["interactor"]["class"]
        stimulator_kwargs = self._option_dict["interactor"]["kwargs"]
        HardWareInterfaceClass = StimulatorClass.__dict__["_HardwareInterfaceClass"]

        TrackerClass = self._option_dict["tracker"]["class"]
        tracker_kwargs = self._option_dict["tracker"]["kwargs"]

        ResultWriterClass = self._option_dict["result_writer"]["class"]
        result_writer_kwargs = self._option_dict["result_writer"]["kwargs"]

        cam = CameraClass(**camera_kwargs)

        roi_builder = ROIBuilderClass(**roi_builder_kwargs)
        
        try:
            rois = roi_builder.build(cam)
        except EthoscopeException as e:
            cam._close()
            raise e


        logging.info("Initialising monitor")
        cam.restart()
        # the camera start time is the reference 0


        ExpInfoClass = self._option_dict["experimental_info"]["class"]
        exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]
        self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic
        self._info["time"] = cam.start_time
        
        #here the hardwareconnection call the interface class without passing any argument!
        hardware_connection = HardwareConnection(HardWareInterfaceClass)
        
        #creates a unique tracking id to label this tracking run
        self._info["experimental_info"]["run_id"] = secrets.token_hex(8)
        
        
        if self._info["experimental_info"]["sensor"]:
            #if is URL:
            sensor = EthoscopeSensor(self._info["experimental_info"]["sensor"])
            logging.info("Using sensor with URL %s" % self._info["experimental_info"]["sensor"])
        else:
            sensor = None
        
        self._metadata = {
            "machine_id": self._info["id"],
            "machine_name": self._info["name"],
            "date_time": cam.start_time,  # the camera start time is the reference 0
            "frame_width": cam.width,
            "frame_height": cam.height,
            "version": self._info["version"]["id"],
            "experimental_info": str(self._info["experimental_info"]),
            "selected_options": str(self._option_dict),
        }
        # hardware_interface is a running thread
        rw = ResultWriter(self._db_credentials, rois, self._metadata, take_frame_shots=True, sensor=sensor)

        return  (cam, rw, rois, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs)

    def run(self):
        cam = None
        hardware_connection = None

        try:
            self._info["status"] = "initialising"
            logging.info("Starting Monitor thread")
            self._info["error"] = None
            self._last_info_t_stamp = 0
            self._last_info_frame_idx = 0


            if self._has_pickle_file():
                try:
                    cam, rw, rois, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, self._info = self._set_tracking_from_pickled()

                except Exception as e:
                    logging.error("Could not load previous state for unexpected reason:")
                    raise e

            else:
                cam, rw, rois, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs = self._set_tracking_from_scratch()
                
            
            with rw as result_writer:
                if cam.canbepickled:
                    self._save_pickled_state(cam, rw, rois, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, self._info)
                
                self._start_tracking(cam, result_writer, rois, TrackerClass, tracker_kwargs,
                                     hardware_connection, StimulatorClass, stimulator_kwargs)
            self.stop()

        except EthoscopeException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            self.stop(traceback.format_exc())
        
        except Exception as e:
            self.stop(traceback.format_exc())

        finally:

            try:
                os.remove(self._persistent_state_file)
            except:
                logging.warning("Failed to remove persistent file")
            try:
                if cam is not None:
                    cam._close()

            except:
                logging.warning("Could not close camera properly")
                pass
            try:
                if hardware_connection is not None:
                    hardware_connection.stop()
            except:
                logging.warning("Could not close hardware connection properly")
                pass

            #for testing purposes
            if self._evanescent:
                del self._drawer
                self.stop()
                os._exit(0)


    def stop(self, error=None):
        self._info["status"] = "stopping"
        self._info["time"] = time.time()
        
        # we reset all the user data of the latest experiment except the run_id
        # a new run_id will be created when we start another experiment
        
        if "experimental_info" in self._info and "run_id" in self._info["experimental_info"]:
            self._info["experimental_info"] = { "run_id" : self._info["experimental_info"]["run_id"] }

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
        shutil.rmtree(self._persistent_state_file, ignore_errors=True)

    def set_evanescent(self, value=True):
        self._evanescent = value

