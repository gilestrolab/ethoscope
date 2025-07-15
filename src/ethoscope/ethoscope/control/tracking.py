import tempfile
import os
import traceback
import shutil
import logging
import time
import datetime
import re
import cv2
from threading import Thread
import pickle
import secrets
from collections import OrderedDict
import json

import subprocess
import signal

import trace
from ethoscope.hardware.input.cameras import OurPiCameraAsync, MovieVirtualCamera, V4L2Camera
from ethoscope.roi_builders.target_roi_builder import OlfactionAssayROIBuilder, SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder, ElectricShockAssayROIBuilder
from ethoscope.roi_builders.roi_builders import  DefaultROIBuilder
from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import NullDrawer, DefaultDrawer
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.hardware.interfaces.interfaces import HardwareConnection, EthoscopeSensor
from ethoscope.stimulators.stimulators import DefaultStimulator
from ethoscope.stimulators.sleep_depriver_stimulators import * #importing all stimulators - remember to add the allowed ones to line 84
from ethoscope.stimulators.odour_stimulators import DynamicOdourSleepDepriver, MiddleCrossingOdourStimulator, MiddleCrossingOdourStimulatorFlushed
from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator

from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.io import MySQLResultWriter, SQLiteResultWriter 
from ethoscope.utils.cache import create_metadata_cache, get_all_databases_info
from ethoscope.utils.description import DescribedObject
from ethoscope.utils import pi

class ExperimentalInformation(DescribedObject):
    
        _description  = {   "overview": "Optional information about your experiment",
                            "arguments": [
                                    {"type": "str", "name": "name", "description": "Who are you?", "default" : "", "asknode" : "users", "required" : "required"},
                                    {"type": "str", "name": "location", "description": "Where is your device","default" : "", "asknode" : "incubators"},
                                    {"type": "str", "name": "code", "description": "Would you like to add any code to the resulting filename or metadata?", "default" : ""},
                                    {"type": "boolean", "name": "append", "description": "Append tracking data to the existing database", "default": False},
                                    {"type": "str", "name": "sensor", "description": "url to access the relevant ethoscope sensor", "default": "", "asknode" : "sensors", "hidden" : "true"}
                                   ]}
                                   
        def __init__(self, name="", location="", code="", append=False, sensor=""):
            self._check_code(code)
            self._info_dic = {"name":name,
                              "location":location,
                              "code":code,
                              "sensor":sensor,
                              "append":append}

        def _check_code(self, code):
            r = re.compile(r"[^a-zA-Z0-9-]")
            clean_code = r.sub("",code)
            if len(code) != len(clean_code):
                logging.error("The provided string contains unallowed characters: %s" % code)
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

    _auto_SQL_backup_at_stop = False
    
    _option_dict = OrderedDict([
        ("experimental_info", {
                        "possible_classes":[ExperimentalInformation],
                }),
        ("interactor", {
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
                                            MiddleCrossingOdourStimulatorFlushed,
                                            mAGO,
                                            AGO
                                            ],
                    }),
        ("roi_builder", {
                "possible_classes":[DefaultROIBuilder, SleepMonitorWithTargetROIBuilder, TargetGridROIBuilder, OlfactionAssayROIBuilder, ElectricShockAssayROIBuilder],
            }),
        ("tracker", {
                "possible_classes":[AdaptiveBGModel],
            }),
        ("drawer", {
                        "possible_classes":[DefaultDrawer, NullDrawer],
                    }),
        ("camera", {
                        "possible_classes":[OurPiCameraAsync, MovieVirtualCamera, V4L2Camera],
                    }),
        ("result_writer", {
                        "possible_classes":[MySQLResultWriter, SQLiteResultWriter],
                }),
     ])
    
    #some classes do not need to be offered as choices to the user in normal conditions
    #these are shown only if the machine is not a PI
    _is_a_rPi = pi.isMachinePI() and pi.hasPiCamera() and not pi.isExperimental()
    _hidden_options = {'camera', 'tracker'}  # result_writer is now always available
    
    for k in _option_dict:
        _option_dict[k]["class"] =_option_dict[k]["possible_classes"][0]
        _option_dict[k]["kwargs"] ={}


    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"

    #give the database an ethoscope specific name
    #future proof in case we want to use a remote server
    _db_credentials = {"name": "%s_db" % pi.get_machine_name(),
                      "user": "ethoscope",
                      "password": "ethoscope"}

    _default_monitor_info =  {
                            #fixme, not needed
                            "last_positions":None,

                            "last_time_stamp":0,
                            "fps":0
                            }

    _persistent_state_file = pi.PERSISTENT_STATE
    _last_run_info = '/var/run/last_run.ethoscope'

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
            os.remove("/tmp/ethoscope_*")
        except OSError:
            pass

        try:
            os.makedirs(ethoscope_dir)
        except OSError:
            pass

        # Manage disk space before starting experiment
        try:
            space_result = pi.manage_disk_space(ethoscope_dir)
            if space_result.get('cleanup_performed', False):
                logging.info(f"Disk space cleanup completed: {space_result.get('cleanup_summary', {}).get('files_deleted', 0)} files removed")
        except Exception as e:
            logging.warning(f"Disk space management failed, continuing anyway: {e}")

        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")
        
        # Database metadata tracking
        self._tracking_start_time = None
        # DatabaseMetadataCache is only compatible with MySQL databases
        # For SQLite, we'll create it only when needed (see metadata cache initialization)
        self._metadata_cache = None
        
        # Cache for databases info to avoid repeated reads
        self._databases_info_cache = None
        self._databases_info_cache_time = 0
        
        #todo add 'data' -> how monitor was started to metadata
        self._info = {  "status": "stopped",
                        "time": time.time(), #this is time of last interaction, e.g. last reboot, last start, last stop.
                        "error": None,
                        "log_file": os.path.join(self._tmp_dir, self._log_file),
                        "dbg_img": os.path.join(self._tmp_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "db_name": self._db_credentials["name"],
                        "monitor_info": self._default_monitor_info,
                        #"user_options": self._get_user_options(),
                        "experimental_info": {},
                        "database_info": {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0, "db_status": "initializing"},

                        "id": machine_id,
                        "name": name,
                        "version": version,
                        "used_space" : pi.get_partition_info(ethoscope_dir)['Use%'].replace("%","")
                        }
        self._monit = None
        self._drawer = None  # Initialize drawer to None until monitor starts

        # Initialize cache directory first
        self._cache_dir = os.path.join (ethoscope_dir, 'cache')
        
        # Try to get last experiment info from cache files (replaces pickle file)
        try:
            # Create temporary cache instance to read last experiment info
            temp_cache = create_metadata_cache(
                db_credentials={"name": "temp"},  # Temporary, will be replaced
                device_name=name,
                cache_dir=self._cache_dir,
                database_type="SQLite3"  # Default, auto-detected later
            )
            last_experiment_info = temp_cache.get_last_experiment_info()
            if last_experiment_info and isinstance(last_experiment_info, dict):
                self._info.update(last_experiment_info)
                logging.info(f"Loaded last experiment info from cache: user={last_experiment_info.get('previous_user', 'unknown')}")
            elif last_experiment_info:
                logging.warning(f"Cache returned non-dict experiment info: {type(last_experiment_info)}")
        except Exception as e:
            logging.warning(f"Failed to load last experiment info from cache: {e}")
            # Ensure _info is still a dictionary even if cache loading fails
            if not isinstance(self._info, dict):
                logging.error("self._info became non-dict after cache failure, resetting")
                self._info = {
                    "id": machine_id,
                    "name": name,
                    "version": version,
                    "used_space": pi.get_partition_info(ethoscope_dir)['Use%'].replace("%","")
                }
        
        # Fallback: try the old pickle file if cache doesn't have info
        if os.path.exists(self._last_run_info) and not self._info.get("previous_backup_filename"):
            try:
                with open(self._last_run_info, 'rb') as fn:
                    pickle_data = pickle.load(fn)
                    if isinstance(pickle_data, dict):
                        self._info.update(pickle_data)
                        logging.info("Loaded last experiment info from legacy pickle file")
                    else:
                        logging.warning(f"Pickle file contained non-dict data: {type(pickle_data)}")
            except Exception as e:
                logging.warning(f"Failed to load from pickle file: {e}")
        
        # Final safety check: ensure _info is always a dictionary
        if not isinstance(self._info, dict):
            logging.error("self._info is not a dictionary after initialization, creating new one")
            self._info = {
                "id": machine_id,
                "name": name,
                "version": version,
                "used_space": pi.get_partition_info(ethoscope_dir)['Use%'].replace("%","")
            }

        # Initialize database info now that _info is fully constructed
        if self._metadata_cache is not None:
            try:
                self._info["database_info"] = self._metadata_cache.get_database_info()
            except Exception as e:
                logging.warning(f"Failed to get database info from metadata cache during initialization: {e}")
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "error"
                }
        else:
            self._info["database_info"] = {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "no_cache"
            }
        
        # Check for existing backup filename from metadata cache during initialization
        # This ensures backup_filename is available immediately for status requests
        if "backup_filename" not in self._info:
            if self._metadata_cache is not None:
                try:
                    existing_backup_filename = self._metadata_cache.get_backup_filename()
                    if existing_backup_filename:
                        self._info["backup_filename"] = existing_backup_filename
                        logging.info(f"Found existing backup filename during initialization: {existing_backup_filename}")
                except Exception as e:
                    logging.warning(f"Failed to get backup filename from metadata cache during initialization: {e}")

        self._parse_user_options(data)
       
        logging.info('Starting a new monitor control thread')
        super(ControlThread, self).__init__()

    def _create_backup_filename(self):
        current_time = self.info["time"]
        date_and_time = datetime.datetime.utcfromtimestamp(current_time).strftime('%Y-%m-%d_%H-%M-%S')
        device_id = self._info["id"]
        return f"{date_and_time}_{device_id}.db"
    
    @property
    def controltype(self):
        return "tracking"

    @property
    def hw_info(self):
        """
        This is information about the ethoscope that is not changing in time such as hardware specs and configuration parameters
        """
        return { 'kernel'      : os.uname()[2],
                 'pi_version'  : pi.pi_version(),
                 'camera'      : pi.getPiCameraVersion(),
                 'SD_CARD_AGE' : pi.get_SD_CARD_AGE(),
                 'partitions'  : pi.get_partition_info(),
                 'SD_CARD_NAME':  pi.get_SD_CARD_NAME()  }



    @property
    def info(self):
        self._update_info()
        # Safety check: ensure we always return a dictionary
        if not isinstance(self._info, dict):
            logging.error(f"self._info is not a dictionary ({type(self._info)}), creating emergency fallback")
            self._info = {
                "id": getattr(self, '_machine_id', 'unknown'),
                "name": getattr(self, '_name', 'unknown'),
                "version": "unknown",
                "error": "info corruption detected and recovered"
            }
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
            if key not in self._hidden_options or pi.isExperimental() or not self._is_a_rPi:
                out[key] = []
                for p in value["possible_classes"]:
                    try:
                        if pi.isExperimental():
                            d = p.__dict__["_description"]
                            d["name"] = p.__name__
                            out[key].append(d)
                            
                        elif not pi.isExperimental() and 'hidden' not in p.__dict__['_description'] or not p.__dict__['_description']['hidden']:
                            d = p.__dict__["_description"]
                            d["name"] = p.__name__
                            out[key].append(d)

                    except KeyError:
                        continue

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
        '''
        Updates a dictionary with information that relates to the current status of the machine, ie data linked for instance to data acquisition
        Information that is not related to control and it is not experiment-dependent will come from elsewhere
        '''
        
        # Add comprehensive databases information using existing cache files
        # This should be available regardless of monitor status
        self._info["databases"] = self._get_databases_info()
        
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

        if self._drawer:
            frame = self._drawer.last_drawn_frame
            if frame is not None:
                cv2.imwrite(self._info["last_drawn_img"], frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])

        # Update database info using MetadataCache
        if self._metadata_cache is not None:
            try:
                self._info["database_info"] = self._metadata_cache.get_database_info()
            except Exception as e:
                logging.warning(f"Failed to get database info from metadata cache: {e}")
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "error"
                }
        else:
            self._info["database_info"] = {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "no_cache"
            }
        
        # Update backup filename from metadata cache - always include regardless of status
        if "backup_filename" not in self._info or not self._info["backup_filename"]:
            if self._metadata_cache is not None:
                try:
                    backup_filename = self._metadata_cache.get_backup_filename()
                    if backup_filename:
                        self._info["backup_filename"] = backup_filename
                except Exception as e:
                    logging.warning(f"Failed to get backup filename from metadata cache: {e}")

        self._last_info_t_stamp = wall_time
        self._last_info_frame_idx = frame_idx

    def _get_databases_info(self):
        """
        Get comprehensive database information using existing cache files.
        Uses caching to avoid repeated reads within a short time period.
        
        Returns:
            dict: Nested structure with SQLite and MariaDB database information
        """
        current_time = time.time()
        
        # Cache results for 30 seconds to avoid repeated reads
        if (self._databases_info_cache is not None and 
            current_time - self._databases_info_cache_time < 30):
            return self._databases_info_cache
        
        try:
            databases_info = get_all_databases_info(self._info["name"], self._cache_dir)
            # Update cache
            self._databases_info_cache = databases_info
            self._databases_info_cache_time = current_time
            return databases_info
        except Exception as e:
            logging.warning(f"Failed to get databases info: {e}")
            return {"SQLite": {}, "MariaDB": {}}

    def _invalidate_databases_cache(self):
        """Invalidate the databases info cache to force a fresh read."""
        self._databases_info_cache = None
        self._databases_info_cache_time = 0

    def _start_tracking(self, camera, result_writer, rois, reference_points, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs):

        #Here the stimulator passes args. Hardware connection was previously open as thread.
        stimulators = [StimulatorClass(hardware_connection, **stimulator_kwargs) for _ in rois]
        
        kwargs = self._monit_kwargs.copy()
        kwargs.update(tracker_kwargs)

        # todo: pickle hardware connection, camera, rois, tracker class, stimulator class,.
        # then rerun stimulators and Monitor(......)
        self._monit = Monitor(camera, TrackerClass, rois,
                              reference_points = reference_points,
                              stimulators=stimulators,
                              *self._monit_args)
        
        self._info["status"] = "running"
        logging.info("Setting monitor status as running: '%s'" % self._info["status"])
        
        # Invalidate databases cache when tracking starts
        self._invalidate_databases_cache()
        
        # Set tracking start time for database metadata
        # Use the original experiment start time from metadata/backup filename, not current time
        if hasattr(self, '_metadata') and self._metadata is not None and 'date_time' in self._metadata:
            # Use experiment start time from metadata
            self._tracking_start_time = self._metadata['date_time']
            logging.info(f"Using experiment start time from metadata: {self._tracking_start_time}")

        elif self._info.get('backup_filename'):
            # Extract start time from backup filename as fallback
            try:
                # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
                timestamp_part = self._info['backup_filename'].split('_')[:2]  # Only take date and time parts
                timestamp_str = '_'.join(timestamp_part)
                self._tracking_start_time = time.mktime(time.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S'))
                logging.info(f"Using experiment start time from backup filename: {self._tracking_start_time}")
            except (ValueError, IndexError) as e:
                logging.warning(f"Could not parse time from backup filename {self._info['backup_filename']}: {e}")
                self._tracking_start_time = time.time()
        else:
            # Fallback to current time if no other information available
            self._tracking_start_time = time.time()
            logging.warning("Using current time as tracking start time (no metadata/backup filename available)")
        
        # Initialize database metadata for tracking
        if self._metadata_cache is not None:
            try:
                self._info["database_info"] = self._metadata_cache.get_database_info()
            except Exception as e:
                logging.warning(f"Failed to get database info from metadata cache for tracking: {e}")
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "error"
                }
        else:
            self._info["database_info"] = {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "no_cache"
            }

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

    def _save_pickled_state(self, camera, result_writer, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, running_info):
        """
        note that cv2.videocapture is not a serializable object and cannot be pickled
        """

        tpl = (camera, result_writer, rois, reference_points, TrackerClass, tracker_kwargs,
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

        DrawerClass = self._option_dict["drawer"]["class"]
        drawer_kwargs = self._option_dict["drawer"]["kwargs"]
        self._drawer = DrawerClass(**drawer_kwargs)

        cam = CameraClass(**camera_kwargs)

        roi_builder = ROIBuilderClass(**roi_builder_kwargs)
        
        try:
            reference_points, rois = roi_builder.build(cam)
        except EthoscopeException as e:
            cam._close()
            raise e


        logging.info("Initialising monitor")
        cam.restart()

        ExpInfoClass = self._option_dict["experimental_info"]["class"]
        exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]
        self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic
        self._info["time"] = cam.start_time # the camera start time is the reference 0
        
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

        if "append" in self._info["experimental_info"]:
            append_to_db = self._info["experimental_info"]["append"]
            logging.info(["Recreating a new database", "Appending tracking data to the existing database"][append_to_db])
        else:
            append_to_db = False

        # Try to get existing backup filename from metadata cache first
        existing_backup_filename = None
        if self._metadata_cache is not None:
            try:
                existing_backup_filename = self._metadata_cache.get_backup_filename()
            except Exception as e:
                logging.warning(f"Failed to get backup filename from metadata cache: {e}")
        
        if existing_backup_filename and append_to_db:
            # Use existing backup filename when appending to database
            self._info["backup_filename"] = existing_backup_filename
            logging.info(f"Using existing backup filename for append mode: {existing_backup_filename}")

        elif self._has_pickle_file() and existing_backup_filename and not append_to_db:
            # and when we are recovering from a crash
            self._info["backup_filename"] = existing_backup_filename

        else:
            # No existing backup filename or first time - create new one
            self._info["backup_filename"] = self._create_backup_filename()
            logging.info(f"Creating new backup filename: {self._info['backup_filename']}")
        
        self._info["interactor"] = {}
        self._info["interactor"]["name"] = str(self._option_dict['interactor']['class'])
        self._info["interactor"].update ( self._option_dict['interactor']['kwargs'])

        # this will be saved in the metadata table
        # and in the pickle file below
        # Extract original experiment start time from backup filename for consistency
        timestamp_str = '_'.join( self._info["backup_filename"].split('_')[:2] )
        experiment_time = time.mktime(time.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S'))
        
        # Determine result writer type for backup metadata
        ResultWriterClass = self._option_dict["result_writer"]["class"]
        result_writer_type = ResultWriterClass.__name__
        
        # For SQLite, construct the source database file path using consistent directory structure
        # Path: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/{backup_filename}
        sqlite_source_path = None
        if result_writer_type == "SQLiteResultWriter":
            # Parse backup filename format: YYYY-MM-DD_HH-MM-SS_machine_id.db
            filename_parts = self._info["backup_filename"].replace('.db', '').split("_")
            if len(filename_parts) >= 3:
                backup_date = filename_parts[0]
                backup_time = filename_parts[1] 
                etho_id = "_".join(filename_parts[2:])  # Join remaining parts as machine_id might contain underscores
                sqlite_source_path = f"/ethoscope_data/results/{etho_id}/{self._info['name']}/{backup_date}_{backup_time}/{self._info['backup_filename']}"
            else:
                raise ValueError(f"Invalid backup filename format: {self._info['backup_filename']}")
        
        self._metadata = {
            "machine_id": self._info["id"],
            "machine_name": self._info["name"],
            "date_time": experiment_time,
            "frame_width": cam.width,
            "frame_height": cam.height,
            "version": self._info["version"]["id"],
            "experimental_info": str(self._info["experimental_info"]),
            "selected_options": str(self._option_dict),
            "hardware_info" : str(self.hw_info),
            "reference_points" : str([(p[0],p[1]) for p in reference_points]),
            "backup_filename" : self._info["backup_filename"],
            "result_writer_type": result_writer_type,
            "sqlite_source_path": sqlite_source_path
        }
        
        # This is useful to retrieve the latest run's information after a reboot
        # Now stored in cache files instead of separate pickle file
        experiment_info_to_store = {
            "date_time": self._info["time"],
            "backup_filename": self._info["backup_filename"],
            "user": self._info["experimental_info"]["name"],
            "location": self._info["experimental_info"]["location"],
            "result_writer_type": result_writer_type,
            "sqlite_source_path": sqlite_source_path
        }
        
        # hardware_interface is a running thread
        # Use the selected result writer class and pass appropriate arguments
        result_writer_kwargs.update({
            'take_frame_shots': True, 
            'erase_old_db': (not append_to_db), 
            'sensor': sensor
        })
        
        # Configure database credentials and metadata cache based on result writer type
        if result_writer_type == "SQLiteResultWriter":
            # SQLite uses the consistent directory structure for database file path
            if sqlite_source_path is None:
                raise ValueError("SQLite source path is None - backup filename parsing failed")
                
            # Ensure the directory structure exists before creating the database
            sqlite_dir = os.path.dirname(sqlite_source_path)
            os.makedirs(sqlite_dir, exist_ok=True)
            logging.info(f"Created SQLite directory structure: {sqlite_dir}")
            
            sqlite_credentials = self._db_credentials.copy()
            sqlite_credentials["name"] = sqlite_source_path
            rw = ResultWriterClass(sqlite_credentials, rois, self._metadata, **result_writer_kwargs)
            
            # Initialize SQLite metadata cache for JSON file generation
            self._metadata_cache = create_metadata_cache(
                db_credentials=sqlite_credentials,
                device_name=self._info["name"],
                cache_dir=self._cache_dir,
                database_type="SQLite3"
            )
        else:
            # MySQL uses standard credentials and metadata cache
            rw = ResultWriterClass(self._db_credentials, rois, self._metadata, **result_writer_kwargs)
            
            # Initialize MySQL metadata cache
            self._metadata_cache = create_metadata_cache(
                db_credentials=self._db_credentials,
                device_name=self._info["name"],
                cache_dir=self._cache_dir,
                database_type="MySQL"
            )
        
        # Store experiment information in cache (replaces last_run_info file)
        if self._metadata_cache:
            tracking_start_time = time.time()
            self._metadata_cache.store_experiment_info(tracking_start_time, experiment_info_to_store)

        return  (cam, rw, rois, reference_points, TrackerClass, tracker_kwargs,
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

            #check if a previous instance exist and if it does attempts to start from there
            if self._has_pickle_file():
                logging.warning("Attempting to resume a previously interrupted state")
                
                try:
                    cam, rw, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, self._info = self._set_tracking_from_pickled()
                    
                    # IMPORTANT: Validate backup filename from pickle against metadata table
                    # The pickle file might have an outdated backup filename if the ethoscope rebooted
                    logging.info(f"Loaded backup filename from pickle: {self._info.get('backup_filename', 'None')}")
                    
                    # Get the correct backup filename from metadata cache
                    metadata_backup_filename = None
                    if self._metadata_cache is not None:
                        try:
                            metadata_backup_filename = self._metadata_cache.get_backup_filename()
                        except Exception as e:
                            logging.warning(f"Failed to get backup filename from metadata cache: {e}")
                    
                    if metadata_backup_filename and metadata_backup_filename != self._info.get('backup_filename'):
                        logging.warning(f"Backup filename mismatch! Pickle: {self._info.get('backup_filename')} vs Metadata: {metadata_backup_filename}")
                        logging.info(f"Using correct backup filename from metadata: {metadata_backup_filename}")
                        self._info['backup_filename'] = metadata_backup_filename
                    elif metadata_backup_filename:
                        logging.info(f"Backup filename validated against metadata: {metadata_backup_filename}")
                    else:
                        logging.warning("No backup filename found in metadata cache, keeping pickle version")

                except Exception as e:
                    logging.error("Could not load previous state for unexpected reason:")
                    raise e
            
            #a previous instance does not exist, hence we create a new one
            else:
                cam, rw, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs = self._set_tracking_from_scratch()
                
            
            with rw as result_writer:
                
                # and we save it if we can
                if cam.canbepickled:
                    self._save_pickled_state(cam, rw, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, self._info)
                
                # then we start tracking
                self._start_tracking(cam, result_writer, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs)
            
            #self.stop()

        except EthoscopeException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            self.stop(traceback.format_exc())
        
        except Exception as e:
            self.stop(traceback.format_exc())

        finally:

            if os.path.exists(self._persistent_state_file):
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

    def stop (self, error=None):
        """
        """
        #We stop only if we are actually running - not when the thread simply dies
        if self.info["status"] in ["running", "starting", "initialising"]:

            self._info["status"] = "stopping"
            self._info["time"] = time.time()
            
            # Invalidate databases cache when tracking stops
            self._invalidate_databases_cache()

            # we reset all the user data of the latest experiment except the run_id
            # a new run_id will be created when we start another experiment
            
            if "experimental_info" in self._info and "run_id" in self._info["experimental_info"]:
                self._info["experimental_info"] = { "run_id" : self._info["experimental_info"]["run_id"] }

            if not self._monit is None:
                self._monit.stop()
                self._monit = None

                if self._auto_SQL_backup_at_stop:
                    logging.info("Performing a SQL dump of the database.")
                    t = Thread( target = SQL_dump )
                    t.start()


            self._info["status"] = "stopped"
            self._info["time"] = time.time()
            self._info["error"] = error
            self._info["monitor_info"] = self._default_monitor_info
            
            # Finalize database cache file when tracking stops (MySQL only)
            if self._tracking_start_time and self._metadata_cache is not None:
                try:
                    self._metadata_cache.finalize_cache(self._tracking_start_time)
                    logging.info(f"Finalized database cache file for tracking session")
                except Exception as e:
                    logging.warning(f"Failed to finalize cache file: {e}")
            
            # Update database info after stopping
            if self._metadata_cache is not None:
                try:
                    self._info["database_info"] = self._metadata_cache.get_database_info()
                except Exception as e:
                    logging.warning(f"Failed to get database info from metadata cache after stopping: {e}")
                    self._info["database_info"] = {
                        "db_size_bytes": 0,
                        "table_counts": {},
                        "last_db_update": 0,
                        "db_status": "error"
                    }
            else:
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "no_cache"
                }
            
            if "backup_filename" in self._info:
                self._info["previous_date_time"] = self._info["time"]
                self._info["previous_backup_filename"] = self._info["backup_filename"]
                self._info["previous_user"] = self._info["experimental_info"].get("name", "")
                self._info["previous_location"] = self._info["experimental_info"].get("location", "")


            if error is not None:
                logging.error("Monitor closed with an error:")
                logging.error(error)
            else:
                logging.info("Monitor closed all right")

    def __del__(self):
        """
        """

        self.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        shutil.rmtree(self._persistent_state_file, ignore_errors=True)
