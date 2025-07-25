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
import secrets
from collections import OrderedDict
import json

import subprocess
import signal

import trace
from ethoscope.hardware.input.cameras import OurPiCameraAsync, MovieVirtualCamera, V4L2Camera
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import NullDrawer, DefaultDrawer
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.hardware.interfaces.interfaces import HardwareConnection, EthoscopeSensor
from ethoscope.stimulators.stimulators import DefaultStimulator
from ethoscope.stimulators.sleep_depriver_stimulators import * #importing all stimulators - remember to add the allowed ones to line 84
from ethoscope.stimulators.sleep_restriction_stimulators import mAGOSleepRestriction, SimpleTimeRestrictedStimulator
from ethoscope.stimulators.odour_stimulators import DynamicOdourSleepDepriver, MiddleCrossingOdourStimulator, MiddleCrossingOdourStimulatorFlushed
from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator
from ethoscope.stimulators.multi_stimulator import MultiStimulator

from ethoscope.utils.debug import EthoscopeException
from ethoscope.io import MySQLResultWriter, SQLiteResultWriter, dbAppender 
from ethoscope.io import create_metadata_cache
from ethoscope.utils.description import DescribedObject
from ethoscope.utils import pi

class ExperimentalInformation(DescribedObject):
    
        _description  = {   "overview": "Optional information about your experiment",
                            "arguments": [
                                    {"type": "str", "name": "name", "description": "Who are you?", "default" : "", "asknode" : "users", "required" : "required"},
                                    {"type": "str", "name": "location", "description": "Where is your device","default" : "", "asknode" : "incubators"},
                                    {"type": "str", "name": "code", "description": "Would you like to add any code to the resulting filename or metadata?", "default" : ""},
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
                                            AGO,
                                            mAGOSleepRestriction,
                                            SimpleTimeRestrictedStimulator,
                                            MultiStimulator
                                            ],
                    }),
        ("roi_builder", {
                "possible_classes":[FileBasedROIBuilder, TargetGridROIBuilder],
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
                        "possible_classes":[SQLiteResultWriter, MySQLResultWriter, dbAppender],
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
        
        # for image write rate limiting (max 1 image per second)
        self._last_img_write_time = 0


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
        """
        Check if the last experiment was interrupted abruptly (not stopped gracefully).
        Uses cache system to determine if experiment ended gracefully.
        """
        if self._metadata_cache:
            try:
                # Get the most recent cache files to check for graceful stop
                cache_files = self._metadata_cache.list_cache_files()
                if cache_files:
                    recent_cache_path = cache_files[0]['path']
                    if os.path.exists(recent_cache_path):
                        with open(recent_cache_path, 'r') as f:
                            cache_data = json.load(f)
                        
                        # Check if experiment was stopped gracefully
                        stopped_gracefully = cache_data.get('stopped_gracefully', False)
                        return not stopped_gracefully
            except Exception as e:
                logging.warning(f"Failed to check cache for graceful stop: {e}")
        
        # Default to not interrupted if no cache info available
        return False

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
            if frame is not None and (wall_time - self._last_img_write_time) >= 1.0:
                cv2.imwrite(self._info["last_drawn_img"], frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                self._last_img_write_time = wall_time

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
        
        # Update backup filename from result writer if available during tracking
        if self._monit and hasattr(self._monit, '_result_writer'):
            try:
                backup_filename = self._monit._result_writer.get_backup_filename()
                if backup_filename:
                    self._info["backup_filename"] = backup_filename
            except Exception as e:
                logging.warning(f"Failed to get backup filename from result writer: {e}")

        self._last_info_t_stamp = wall_time
        self._last_info_frame_idx = frame_idx

    def _start_tracking(self, camera, result_writer, rois, reference_points, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs, time_offset=0):

        #Here the stimulator passes args. Hardware connection was previously open as thread.
        stimulators = [StimulatorClass(hardware_connection, **stimulator_kwargs) for _ in rois]
        
        kwargs = self._monit_kwargs.copy()
        kwargs.update(tracker_kwargs)

        self._monit = Monitor(camera, TrackerClass, rois,
                              reference_points = reference_points,
                              stimulators=stimulators,
                              time_offset=time_offset,
                              *self._monit_args)
        
        self._info["status"] = "running"
        logging.info("Setting monitor status as running: '%s'" % self._info["status"])
        
        # Set tracking start time for database metadata
        # Use the original experiment start time from metadata/backup filename, not current time
        if hasattr(self, '_metadata') and self._metadata is not None and 'date_time' in self._metadata:
            # Use experiment start time from metadata (already updated for dbAppender)
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

        try:
            cam = CameraClass(**camera_kwargs)
        except EthoscopeException as e:
            if "Camera hardware not available" in str(e):
                logging.error("Cannot start tracking: No camera hardware detected")
                raise EthoscopeException("Tracking disabled: No camera hardware available. This ethoscope cannot perform video tracking or recording without camera hardware.")
            else:
                raise e

        roi_builder = ROIBuilderClass(**roi_builder_kwargs)
        
        try:
            reference_points, rois = roi_builder.build(cam)
            
            # Handle graceful failure when ROI building returns None values
            if reference_points is None or rois is None:
                logging.warning("ROI building failed: insufficient targets detected.")
                # Save debug image to help user understand the issue
                self._save_roi_debug_image(cam, "Insufficient targets detected")
                try:
                    cam._close()
                    # Add a delay to allow camera hardware to reset
                    time.sleep(2.0)
                    logging.info("Camera cleanup completed, hardware should be available for next attempt")
                except Exception as cleanup_error:
                    logging.error(f"Error during camera cleanup: {cleanup_error}")
                # Return None to indicate failure instead of raising exception
                return None
                
        except (EthoscopeException, Exception) as e:
            logging.error(f"ROI building failed: {e}")
            # Save debug image with exception details
            self._save_roi_debug_image(cam, f"ROI building error: {str(e)}")
            try:
                cam._close()
                # Add a delay to allow camera hardware to reset
                time.sleep(2.0)
                logging.info("Camera cleanup completed, hardware should be available for next attempt")
            except Exception as cleanup_error:
                logging.error(f"Error during camera cleanup: {cleanup_error}")
            # Return None to indicate failure instead of raising exception
            return None


        logging.info("Initialising monitor")
        cam.restart()

        ExpInfoClass = self._option_dict["experimental_info"]["class"]
        exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]
        
        # Debug: log what's being passed to ExperimentalInformation
        logging.info(f"DEBUG: Creating ExperimentalInformation with kwargs: {exp_info_kwargs}")
        
        self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic
        
        # Debug: log the final experimental_info
        logging.info(f"DEBUG: Final experimental_info created: {self._info['experimental_info']}")
        
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

        # Use current camera start time for experiment timestamp
        experiment_time = cam.start_time
        self._info["time"] = experiment_time
        
        # Create initial backup filename - result writer may override this later
        self._info["backup_filename"] = self._create_backup_filename()
        logging.info(f"Creating initial backup filename: {self._info['backup_filename']}")
        
        # Determine result writer type
        ResultWriterClass = self._option_dict["result_writer"]["class"]
        if hasattr(ResultWriterClass, '_database_type'):
            result_writer_type = ResultWriterClass._database_type
        else:
            result_writer_type = ResultWriterClass.__name__
        
        self._info["interactor"] = {}
        self._info["interactor"]["name"] = str(self._option_dict['interactor']['class'])
        self._info["interactor"].update ( self._option_dict['interactor']['kwargs'])
        
        # For SQLite, construct the source database file path using consistent directory structure
        # Path: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/{backup_filename}
        sqlite_source_path = None
        if result_writer_type == "SQLite3" or result_writer_type == "SQLiteResultWriter":
            # Create new database with current timestamp
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
            "sqlite_source_path": sqlite_source_path,
            "run_id": self._info["experimental_info"]["run_id"]
        }
        
        # hardware_interface is a running thread
        # Use the selected result writer class and pass appropriate arguments
        result_writer_kwargs.update({
            'take_frame_shots': True, 
            'erase_old_db': True,  # Always create new database (dbAppender handles append internally)
            'sensor': sensor
        })
        
        # Configure database credentials and metadata cache based on result writer type
        if result_writer_type == "SQLite3" or result_writer_type == "SQLiteResultWriter":
            # SQLite uses the consistent directory structure for database file path
            if sqlite_source_path is None:
                raise ValueError("SQLite source path is None - backup filename parsing failed")
                
            # Ensure the directory structure exists before creating the database
            sqlite_dir = os.path.dirname(sqlite_source_path)
            os.makedirs(sqlite_dir, exist_ok=True)
            logging.info(f"Created SQLite directory structure: {sqlite_dir}")
            
            # Create clean SQLite credentials (only database path, no MySQL connection params)
            sqlite_credentials = {"name": sqlite_source_path}
            rw = ResultWriterClass(sqlite_credentials, rois, self._metadata, **result_writer_kwargs)
            
            # Get the backup filename from the result writer (may be different from initial one)
            backup_filename_from_writer = rw.get_backup_filename()
            if backup_filename_from_writer:
                self._info["backup_filename"] = backup_filename_from_writer
                logging.info(f"Updated backup filename from result writer: {backup_filename_from_writer}")
            
            # Initialize SQLite metadata cache for JSON file generation
            # Use clean SQLite credentials (only database path)
            cache_credentials = {"name": sqlite_source_path}
            self._metadata_cache = create_metadata_cache(
                db_credentials=cache_credentials,
                device_name=self._info["name"],
                cache_dir=self._cache_dir,
                database_type="SQLite3"
            )
        elif result_writer_type == "dbAppender":
            # dbAppender handles database discovery and append functionality internally
            rw = ResultWriterClass(
                db_credentials=self._db_credentials,
                rois=rois,
                metadata=self._metadata,
                **result_writer_kwargs
            )
            
            # Get the backup filename from the result writer (may be different from initial one)
            backup_filename_from_writer = rw.get_backup_filename()
            if backup_filename_from_writer:
                self._info["backup_filename"] = backup_filename_from_writer
                logging.info(f"Updated backup filename from result writer: {backup_filename_from_writer}")
            
            # Initialize metadata cache based on detected database type
            # The dbAppender will have created the appropriate writer internally
            if hasattr(rw, '_writer') and hasattr(rw._writer, '_database_type'):
                db_type = rw._writer._database_type
                
                # Update result_writer_type to the actual database type instead of "dbAppender"
                result_writer_type = db_type
                logging.info(f"dbAppender: Updated result_writer_type from 'dbAppender' to '{db_type}'")
                
                if db_type == "SQLite3":
                    cache_credentials = {"name": rw._writer._db_credentials["name"]}
                    cache_db_type = "SQLite3"
                    # Update sqlite_source_path for SQLite dbAppender
                    sqlite_source_path = rw._writer._db_credentials["name"]
                else:
                    cache_credentials = self._db_credentials
                    cache_db_type = "MySQL"
                    
                self._metadata_cache = create_metadata_cache(
                    db_credentials=cache_credentials,
                    device_name=self._info["name"],
                    cache_dir=self._cache_dir,
                    database_type=cache_db_type
                )
                
                # For dbAppender, get the original experiment timestamp from the database
                # This ensures we reuse the existing cache file instead of creating a new one
                try:
                    original_timestamp = self._metadata_cache.get_database_timestamp()
                    if original_timestamp:
                        # Update the experiment time to use the original timestamp
                        experiment_time = original_timestamp
                        logging.info(f"dbAppender: Using original experiment timestamp {original_timestamp} from database")
                        
                        # Update metadata with original experiment time
                        self._metadata['date_time'] = experiment_time
                        
                        # Update backup filename to match original experiment
                        original_backup_filename = self._metadata_cache.get_backup_filename()
                        if original_backup_filename:
                            self._info["backup_filename"] = original_backup_filename
                            logging.info(f"dbAppender: Using original backup filename {original_backup_filename}")
                        else:
                            # Generate backup filename from original timestamp
                            ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(original_timestamp))
                            self._info["backup_filename"] = f"{ts_str}_{self._info['id']}.db"
                            logging.info(f"dbAppender: Generated backup filename from original timestamp: {self._info['backup_filename']}")
                    else:
                        logging.warning("dbAppender: Could not retrieve original experiment timestamp, using new timestamp")
                except Exception as e:
                    logging.warning(f"dbAppender: Failed to get original experiment timestamp: {e}")
            else:
                # Fallback to standard metadata cache
                self._metadata_cache = create_metadata_cache(
                    db_credentials=self._db_credentials,
                    device_name=self._info["name"],
                    cache_dir=self._cache_dir,
                    database_type="MySQL"
                )
            
            # Update metadata and experiment_info_to_store with the correct result_writer_type
            # (they were created before we knew the actual database type)
            self._metadata["result_writer_type"] = result_writer_type
            self._metadata["sqlite_source_path"] = sqlite_source_path
            experiment_info_to_store["result_writer_type"] = result_writer_type
            experiment_info_to_store["sqlite_source_path"] = sqlite_source_path
        else:
            # MySQL uses standard credentials and metadata cache
            rw = ResultWriterClass(self._db_credentials, rois, self._metadata, **result_writer_kwargs)
            
            # Get the backup filename from the result writer (may be different from initial one)
            backup_filename_from_writer = rw.get_backup_filename()
            if backup_filename_from_writer:
                self._info["backup_filename"] = backup_filename_from_writer
                logging.info(f"Updated backup filename from result writer: {backup_filename_from_writer}")
            
            # Initialize MySQL metadata cache
            self._metadata_cache = create_metadata_cache(
                db_credentials=self._db_credentials,
                device_name=self._info["name"],
                cache_dir=self._cache_dir,
                database_type="MySQL"
            )
        
        # Store experiment information in cache (replaces last_run_info file)
        if self._metadata_cache:
            # Use the experiment timestamp (which may be original timestamp for dbAppender)
            tracking_start_time = experiment_time
            self._metadata_cache.store_experiment_info(tracking_start_time, experiment_info_to_store)

        time_offset = 0
        # dbAppender handles append functionality and time offset internally
        if hasattr(rw, 'append'):
            time_offset = rw.append()

        return  (cam, rw, rois, reference_points, TrackerClass, tracker_kwargs,
                        hardware_connection, StimulatorClass, stimulator_kwargs, time_offset)

    def _save_roi_debug_image(self, cam, error_message):
        """
        Save a debug image when ROI building fails to help user understand the issue.
        """
        try:
            # Get a frame from the camera to show what was detected
            _, frame = next(iter(cam))
            
            # Convert to color if it's grayscale for better annotation visibility
            if len(frame.shape) == 2:
                debug_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            else:
                debug_frame = frame.copy()
            
            # Add timestamp in bottom right corner in white text
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 2.0  # 4x larger than 0.5
            color = (255, 255, 255)  # White color
            thickness = 3  # Thicker for better visibility
            
            # Get current timestamp with timezone
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")
            # If no timezone info, add local timezone indicator
            if not timestamp.endswith(' '):
                import time
                tz_name = time.tzname[time.daylight]
                timestamp = f"{timestamp.rstrip()} {tz_name}"
            
            # Calculate text size to position it in bottom right
            text_size = cv2.getTextSize(timestamp, font, font_scale, thickness)[0]
            text_x = debug_frame.shape[1] - text_size[0] - 10  # 10 pixels from right edge
            text_y = debug_frame.shape[0] - 10  # 10 pixels from bottom edge
            
            cv2.putText(debug_frame, timestamp, (text_x, text_y), font, font_scale, color, thickness)
            
            # Save the debug image
            debug_path = self._info["dbg_img"]
            cv2.imwrite(debug_path, debug_frame)
            logging.info(f"Debug image saved to: {debug_path}")
            
        except Exception as e:
            logging.error(f"Failed to save debug image: {e}")

    def run(self):
        cam = None
        hardware_connection = None

        try:
            self._info["status"] = "initialising"
            logging.info("Starting Monitor thread")
            self._info["error"] = None
            self._last_info_t_stamp = 0
            self._last_info_frame_idx = 0

            # Always create a new tracking instance (pickle resume logic removed)
            tracking_setup = self._set_tracking_from_scratch()
            
            # Handle graceful failure when tracking setup fails
            if tracking_setup is None:
                logging.warning("Tracking setup failed. Please check your arena setup and try again.")
                self._info["status"] = "stopped"  # Keep device available for restart
                self._info["error"] = "ROI building failed: insufficient targets detected. Please check your arena has 3 circular targets visible."
                # Don't exit, just stop this tracking attempt - device remains available
                return  # Exit gracefully without crashing
                
            cam, rw, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, time_offset = tracking_setup
            
            with rw as result_writer:
                # Start tracking directly (pickle saving removed)
                self._start_tracking(cam, result_writer, rois, reference_points, TrackerClass, tracker_kwargs, hardware_connection, StimulatorClass, stimulator_kwargs, time_offset=time_offset)
            
            #self.stop()

        except EthoscopeException as e:
            if e.img is not  None:
                cv2.imwrite(self._info["dbg_img"], e.img)
            # This is an exception-based stop, so it's not graceful
            self.stop(traceback.format_exc())
        
        except Exception as e:
            # This is an exception-based stop, so it's not graceful
            self.stop(traceback.format_exc())

        finally:
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
            
            # Finalize database cache file when tracking stops
            if self._tracking_start_time and self._metadata_cache is not None:
                try:
                    # Determine if this was a graceful stop or an error
                    is_graceful = error is None
                    stop_reason = "error" if error else "user_stop"
                    
                    self._metadata_cache.finalize_cache(self._tracking_start_time, graceful=is_graceful, stop_reason=stop_reason)
                    logging.info(f"Finalized database cache file for tracking session (graceful={is_graceful}, reason={stop_reason})")
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
