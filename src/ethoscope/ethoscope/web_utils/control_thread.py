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
from collections import OrderedDict
import json
import mysql.connector

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
from ethoscope.utils.io import ResultWriter, SQLiteResultWriter
from ethoscope.utils.description import DescribedObject
from ethoscope.web_utils.helpers import *

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


def get_database_metadata(db_credentials, tracking_start_time=None, device_name=""):
    """
    Get database metadata either by querying MariaDB or reading from cache file.
    
    Args:
        db_credentials: Database connection credentials
        tracking_start_time: Timestamp when tracking started (for cache file naming)
        device_name: Device name for cache file naming
        
    Returns:
        dict: Database metadata including size, table counts, etc.
    """
    # Determine cache file path
    cache_dir = "/ethoscope_data/cache"
    os.makedirs(cache_dir, exist_ok=True)
    
    if tracking_start_time and device_name:
        # Create timestamp string for filename
        ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(tracking_start_time))
        cache_filename = f"db_metadata_{ts_str}_{device_name}_db.json"
        cache_file_path = os.path.join(cache_dir, cache_filename)
    else:
        cache_file_path = None
    
    try:
        # Try to connect to database and get metadata
        db_info = query_database_metadata(db_credentials)
        
        if cache_file_path:
            # Update cache file with current metadata
            update_cache_file(cache_file_path, db_info, db_credentials["name"], 
                            tracking_start_time, device_name)
        
        return db_info
        
    except Exception as e:
        logging.warning(f"Failed to query database: {e}")
        
        # If database query fails, try to read from most recent cache file
        if cache_file_path and os.path.exists(cache_file_path):
            return read_cache_file(cache_file_path)
        else:
            # Find most recent cache file for this device
            return read_latest_cache_file(cache_dir, device_name)


def query_database_metadata(db_credentials):
    """Query database for metadata including size and table counts."""
    try:
        with mysql.connector.connect(
            host='localhost',
            user=db_credentials["user"],
            password=db_credentials["password"],
            database=db_credentials["name"],
            charset='latin1',
            use_unicode=True,
            connect_timeout=10
        ) as conn:
            cursor = conn.cursor()
            
            # Get database size
            cursor.execute("""
                SELECT ROUND(SUM(data_length + index_length)) as db_size 
                FROM information_schema.tables 
                WHERE table_schema = %s
            """, (db_credentials["name"],))
            db_size = cursor.fetchone()[0] or 0
            
            # Get table counts
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            
            table_counts = {}
            for table in tables:
                try:
                    if table in ["ROI_MAP", "VAR_MAP", "METADATA"]:
                        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    else:
                        cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM `{table}`")
                    
                    result = cursor.fetchone()
                    table_counts[table] = result[0] if result and result[0] is not None else 0
                except mysql.connector.Error:
                    table_counts[table] = 0
            
            return {
                "db_size_bytes": int(db_size),
                "table_counts": table_counts,
                "last_db_update": time.time()
            }
            
    except mysql.connector.Error as e:
        logging.error(f"Database connection error: {e}")
        raise


def update_cache_file(cache_file_path, db_info, db_name, tracking_start_time, device_name):
    """Update or create cache file with database metadata."""
    try:
        # Check if cache file exists
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r') as f:
                cache_data = json.load(f)
        else:
            # Create new cache file
            cache_data = {
                "db_name": db_name,
                "device_name": device_name,
                "tracking_start_time": time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(tracking_start_time)),
                "creation_timestamp": tracking_start_time,
                "db_status": "tracking"
            }
        
        # Update with current database info
        cache_data.update({
            "last_updated": time.time(),
            "db_size_bytes": db_info["db_size_bytes"],
            "table_counts": db_info["table_counts"],
            "last_db_update": db_info["last_db_update"]
        })
        
        # Write cache file
        with open(cache_file_path, 'w') as f:
            json.dump(cache_data, f, indent=2)
            
    except Exception as e:
        logging.warning(f"Failed to update cache file {cache_file_path}: {e}")


def read_cache_file(cache_file_path):
    """Read database metadata from cache file."""
    try:
        with open(cache_file_path, 'r') as f:
            cache_data = json.load(f)
        
        return {
            "db_size_bytes": cache_data.get("db_size_bytes", 0),
            "table_counts": cache_data.get("table_counts", {}),
            "last_db_update": cache_data.get("last_db_update", 0),
            "cache_file": cache_file_path,
            "db_status": cache_data.get("db_status", "unknown")
        }
        
    except Exception as e:
        logging.warning(f"Failed to read cache file {cache_file_path}: {e}")
        return {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0}


def read_latest_cache_file(cache_dir, device_name):
    """Find and read the most recent cache file for a device."""
    try:
        # Find all cache files for this device
        pattern = f"db_metadata_*_{device_name}_db.json"
        cache_files = []
        
        for filename in os.listdir(cache_dir):
            if filename.endswith(f"_{device_name}_db.json") and filename.startswith("db_metadata_"):
                cache_files.append(os.path.join(cache_dir, filename))
        
        if not cache_files:
            return {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0}
        
        # Sort by modification time and get the most recent
        cache_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        latest_cache = cache_files[0]
        
        return read_cache_file(latest_cache)
        
    except Exception as e:
        logging.warning(f"Failed to find latest cache file for {device_name}: {e}")
        return {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0}


def finalize_cache_file(cache_file_path):
    """Mark cache file as finalized when tracking stops."""
    try:
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r') as f:
                cache_data = json.load(f)
            
            cache_data["db_status"] = "finalised"
            cache_data["finalized_timestamp"] = time.time()
            
            with open(cache_file_path, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
    except Exception as e:
        logging.warning(f"Failed to finalize cache file {cache_file_path}: {e}")


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
                        "possible_classes":[ResultWriter, SQLiteResultWriter],
                }),
     ])
    
    #some classes do not need to be offered as choices to the user in normal conditions
    #these are shown only if the machine is not a PI
    _is_a_rPi = isMachinePI() and hasPiCamera() and not isExperimental()
    _hidden_options = {'camera', 'result_writer', 'tracker'}
    
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

    _persistent_state_file = PERSISTENT_STATE
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

        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")
        
        # Database metadata tracking
        self._tracking_start_time = None
        self._current_cache_file = None
        
        #todo add 'data' -> how monitor was started to metadata
        self._info = {  "status": "stopped",
                        "time": time.time(), #this is time of last interaction, e.g. last reboot, last start, last stop.
                        "error": None,
                        "log_file": os.path.join(ethoscope_dir, self._log_file),
                        "dbg_img": os.path.join(ethoscope_dir, self._dbg_img_file),
                        "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
                        "db_name": self._db_credentials["name"],
                        "monitor_info": self._default_monitor_info,
                        #"user_options": self._get_user_options(),
                        "experimental_info": {},
                        "database_info": {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0, "db_status": "initializing"},

                        "id": machine_id,
                        "name": name,
                        "version": version,
                        "used_space" : get_partition_info("/ethoscope_data")['Use%'].replace("%","")
                        }
        self._monit = None

        if os.path.exists(self._last_run_info):
            with open(self._last_run_info, 'rb') as fn:
                self._info.update( pickle.load(fn) )

        # Initialize database info now that _info is fully constructed
        self._info["database_info"] = self._get_database_info()
        
        # Check for existing backup filename from metadata table during initialization
        # This ensures backup_filename is available immediately for status requests
        if "backup_filename" not in self._info:
            existing_backup_filename = self._get_latest_backup_filename()
            if existing_backup_filename:
                self._info["backup_filename"] = existing_backup_filename
                logging.info(f"Found existing backup filename during initialization: {existing_backup_filename}")

        self._parse_user_options(data)
        
        DrawerClass = self._option_dict["drawer"]["class"]
        drawer_kwargs = self._option_dict["drawer"]["kwargs"]
        self._drawer = DrawerClass(**drawer_kwargs)
        
        logging.info('Starting a new monitor control thread')

        super(ControlThread, self).__init__()

    
    @property
    def hw_info(self):
        """
        This is information about the ethoscope that is not changing in time such as hardware specs and configuration parameters
        """
        return { 'kernel'      : os.uname()[2],
                 'pi_version'  : pi_version(),
                 'camera'      : getPiCameraVersion(),
                 'SD_CARD_AGE' : get_SD_CARD_AGE(),
                 'partitions'  : get_partition_info(),
                 'SD_CARD_NAME':  get_SD_CARD_NAME()  }



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
            if key not in self._hidden_options or isExperimental() or not self._is_a_rPi:
                out[key] = []
                for p in value["possible_classes"]:
                    try:
                        if isExperimental():
                            d = p.__dict__["_description"]
                            d["name"] = p.__name__
                            out[key].append(d)
                            
                        elif not isExperimental() and 'hidden' not in p.__dict__['_description'] or not p.__dict__['_description']['hidden']:
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



    def _get_database_info(self):
        """Get database metadata based on current status."""
        try:
            if self._info.get("status") in ["running", "recording"]:
                # During tracking: query database live and update cache
                logging.debug(f"Getting live database info for tracking device {self._info.get('name')}")
                db_info = get_database_metadata(
                    self._db_credentials, 
                    self._tracking_start_time, 
                    self._info.get("name", "")
                )
                logging.debug(f"Retrieved database info: size={db_info.get('db_size_bytes', 0)} bytes, status={db_info.get('db_status', 'unknown')}")
                return db_info
            else:
                # When stopped: read from most recent cache file
                cache_dir = "/ethoscope_data/cache"
                device_name = self._info.get("name", "")
                logging.debug(f"Reading cache file for stopped device {device_name}")
                cache_result = read_latest_cache_file(cache_dir, device_name)
                
                # If no cache file found, try a simple database query without cache
                if cache_result.get("db_size_bytes", 0) == 0:
                    logging.debug(f"No cache found, attempting direct database query for {device_name}")
                    try:
                        db_info = query_database_metadata(self._db_credentials)
                        db_info["db_status"] = "queried_direct"
                        return db_info
                    except Exception as db_e:
                        logging.warning(f"Direct database query failed for {device_name}: {db_e}")
                        return {
                            "db_size_bytes": 0,
                            "table_counts": {},
                            "last_db_update": 0,
                            "db_status": "no_cache_no_db"
                        }
                
                return cache_result
                
        except Exception as e:
            logging.warning(f"Failed to get database info for {self._info.get('name', 'unknown')}: {e}")
            return {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "error"
            }

    def _update_info(self):
        '''
        Updates a dictionary with information that relates to the current status of the machine, ie data linked for instance to data acquisition
        Information that is not related to control and it is not experiment-dependent will come from elsewhere
        '''
        
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

        # Update database info periodically during tracking
        if self._info.get("status") in ["running", "recording"]:
            logging.debug(f"Updating database info for running device {self._info.get('name')}")
            self._info["database_info"] = self._get_database_info()
            logging.debug(f"Database info set: {self._info.get('database_info', {}).get('db_size_bytes', 'missing')}")
        
        # Update backup filename from metadata table - always include regardless of status
        if "backup_filename" not in self._info or not self._info["backup_filename"]:
            backup_filename = self._get_latest_backup_filename()
            if backup_filename:
                self._info["backup_filename"] = backup_filename

        self._last_info_t_stamp = wall_time
        self._last_info_frame_idx = frame_idx


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
        
        # Set tracking start time for database metadata
        # Use the original experiment start time from metadata/backup filename, not current time
        if hasattr(self, '_metadata') and 'date_time' in self._metadata:
            # Use experiment start time from metadata
            self._tracking_start_time = self._metadata['date_time']
            logging.info(f"Using experiment start time from metadata: {self._tracking_start_time}")
        elif self._info.get('backup_filename'):
            # Extract start time from backup filename as fallback
            try:
                # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
                timestamp_part = self._info['backup_filename'].split('_')[:3]
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
        self._info["database_info"] = self._get_database_info()

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

        # Try to get existing backup filename from metadata table first
        existing_backup_filename = self._get_latest_backup_filename()
        
        if existing_backup_filename and append_to_db:
            # Use existing backup filename when appending to database
            self._info["backup_filename"] = existing_backup_filename
            logging.info(f"Using existing backup filename for append mode: {existing_backup_filename}")
        elif existing_backup_filename and not append_to_db:
            # If we're not appending but there's an existing backup filename,
            # we should still check if we're continuing the same experiment
            # (e.g., after a reboot during an ongoing experiment)
            current_time = self._info["time"]
            
            # Extract timestamp from existing backup filename to check if it's recent
            try:
                # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
                timestamp_part = existing_backup_filename.split('_')[:3]  # Get date and time parts
                timestamp_str = '_'.join(timestamp_part)  # Reconstruct timestamp string
                existing_time = time.mktime(time.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S'))
                
                # If the existing backup is recent (within 7 days), use it
                # This handles the case where ethoscope rebooted during an experiment
                if current_time - existing_time < 7 * 24 * 3600:  # 7 days
                    self._info["backup_filename"] = existing_backup_filename
                    logging.info(f"Using existing recent backup filename (experiment likely continuing): {existing_backup_filename}")
                else:
                    # Old backup, create new one
                    self._info["backup_filename"] = "%s_%s.db" % ( datetime.datetime.utcfromtimestamp(current_time).strftime('%Y-%m-%d_%H-%M-%S'), self._info["id"] )
                    logging.info(f"Creating new backup filename (old experiment): {self._info['backup_filename']}")
            except (ValueError, IndexError) as e:
                logging.warning(f"Could not parse existing backup filename {existing_backup_filename}: {e}")
                # Create new backup filename as fallback
                self._info["backup_filename"] = "%s_%s.db" % ( datetime.datetime.utcfromtimestamp(current_time).strftime('%Y-%m-%d_%H-%M-%S'), self._info["id"] )
                logging.info(f"Creating new backup filename (parse error): {self._info['backup_filename']}")
        else:
            # No existing backup filename or first time - create new one
            self._info["backup_filename"] = "%s_%s.db" % ( datetime.datetime.utcfromtimestamp(self._info["time"]).strftime('%Y-%m-%d_%H-%M-%S'), self._info["id"] )
            logging.info(f"Creating new backup filename (no existing): {self._info['backup_filename']}")
        
        self._info["interactor"] = {}
        self._info["interactor"]["name"] = str(self._option_dict['interactor']['class'])
        self._info["interactor"].update ( self._option_dict['interactor']['kwargs'])

        # this will be saved in the metadata table
        # and in the pickle file below
        # Extract original experiment start time from backup filename for consistency
        original_experiment_time = self._info["time"]  # Default to current time
        if self._info.get('backup_filename'):
            try:
                # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
                timestamp_part = self._info['backup_filename'].split('_')[:3]
                timestamp_str = '_'.join(timestamp_part)
                original_experiment_time = time.mktime(time.strptime(timestamp_str, '%Y-%m-%d_%H-%M-%S'))
                logging.info(f"Using original experiment time from backup filename for metadata: {original_experiment_time}")
            except (ValueError, IndexError) as e:
                logging.warning(f"Could not parse time from backup filename for metadata: {e}")
        
        self._metadata = {
            "machine_id": self._info["id"],
            "machine_name": self._info["name"],
            "date_time": original_experiment_time,
            "frame_width": cam.width,
            "frame_height": cam.height,
            "version": self._info["version"]["id"],
            "experimental_info": str(self._info["experimental_info"]),
            "selected_options": str(self._option_dict),
            "hardware_info" : str(self.hw_info),
            "reference_points" : str([(p[0],p[1]) for p in reference_points]),
            "backup_filename" : self._info["backup_filename"]
        }
        
        # This is useful to retrieve the latest run's information after a reboot
        with open(self._last_run_info, "wb") as f:
            pickle.dump( {
                        "previous_date_time" : self._info["time"],
                        "previous_backup_filename" : self._info["backup_filename"],
                        "previous_user" : self._info["experimental_info"]["name"],
                        "previous_location" : self._info["experimental_info"]["location"]
                        }, f)
        
        # hardware_interface is a running thread
        rw = ResultWriter(self._db_credentials, rois, self._metadata, take_frame_shots=True, erase_old_db = (not append_to_db), sensor=sensor,)

        return  (cam, rw, rois, reference_points, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs)

    def _get_latest_backup_filename(self):
        '''
        Tries to recover the latest backup_filename from the metadata table
        '''
        try:
            # Connect to the MySQL database
            conn = mysql.connector.connect(
                host='localhost',
                user=self._db_credentials["user"],
                password=self._db_credentials["password"],
                database=self._db_credentials["name"]
            )
            cursor = conn.cursor()
            
            # Query the metadata table for the backup filename
            cursor.execute("SELECT DISTINCT value FROM METADATA WHERE field = 'backup_filename' AND value IS NOT NULL")
            result = cursor.fetchone()
            
            if result:
                backup_filename = result[0]
                logging.info(f"Found existing backup filename from metadata: {backup_filename}")
                return backup_filename
            else:
                logging.info("No existing backup filename found in metadata table")
                return None
                
        except mysql.connector.Error as e:
            logging.warning(f"Could not retrieve backup filename from metadata table: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error retrieving backup filename: {e}")
            return None
        finally:
            if 'conn' in locals() and conn.is_connected():
                cursor.close()
                conn.close()
        
    
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
                    
                    # Get the correct backup filename from metadata table
                    metadata_backup_filename = self._get_latest_backup_filename()
                    if metadata_backup_filename and metadata_backup_filename != self._info.get('backup_filename'):
                        logging.warning(f"Backup filename mismatch! Pickle: {self._info.get('backup_filename')} vs Metadata: {metadata_backup_filename}")
                        logging.info(f"Using correct backup filename from metadata: {metadata_backup_filename}")
                        self._info['backup_filename'] = metadata_backup_filename
                    elif metadata_backup_filename:
                        logging.info(f"Backup filename validated against metadata: {metadata_backup_filename}")
                    else:
                        logging.warning("No backup filename found in metadata table, keeping pickle version")

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

            if self._auto_SQL_backup_at_stop:
                logging.info("Performing a SQL dump of the database.")
                t = Thread( target = SQL_dump )
                t.start()


        self._info["status"] = "stopped"
        self._info["time"] = time.time()
        self._info["error"] = error
        self._info["monitor_info"] = self._default_monitor_info
        
        # Finalize database cache file when tracking stops
        if self._tracking_start_time and self._info.get("name"):
            try:
                cache_dir = "/ethoscope_data/cache"
                ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(self._tracking_start_time))
                cache_filename = f"db_metadata_{ts_str}_{self._info['name']}_db.json"
                cache_file_path = os.path.join(cache_dir, cache_filename)
                finalize_cache_file(cache_file_path)
                logging.info(f"Finalized database cache file: {cache_file_path}")
            except Exception as e:
                logging.warning(f"Failed to finalize cache file: {e}")
        
        # Update database info after stopping
        self._info["database_info"] = self._get_database_info()
        
        
        if "backup_filename" in self._info:
            self._info["previous_date_time"] = self._info["time"]
            self._info["previous_backup_filename"] = self._info["backup_filename"]
            self._info["previous_user"] = self._info["experimental_info"]["name"]
            self._info["previous_location"] = self._info["experimental_info"]["location"]


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
