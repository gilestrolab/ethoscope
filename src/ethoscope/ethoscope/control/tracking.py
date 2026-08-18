import datetime
import json
import logging
import os
import re
import secrets
import shutil
import signal
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from threading import Thread

import cv2

from ethoscope.core.monitor import Monitor
from ethoscope.drawers.drawers import DefaultDrawer, NullDrawer
from ethoscope.hardware.input.cameras import (
    MovieVirtualCamera,
    OurPiCameraAsync,
    V4L2Camera,
)
from ethoscope.hardware.interfaces.interfaces import EthoscopeSensor, HardwareConnection
from ethoscope.io import (
    MySQLResultWriter,
    SQLiteResultWriter,
    create_metadata_cache,
)
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.roi_builders.target_roi_builder import TargetGridROIBuilder
from ethoscope.stimulators.composed_stimulator import ComposedStimulator
from ethoscope.stimulators.multi_stimulator import MultiStimulator
from ethoscope.stimulators.odour_stimulators import (
    DynamicOdourSleepDepriver,
    MiddleCrossingOdourStimulator,
    MiddleCrossingOdourStimulatorFlushed,
)
from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator
from ethoscope.stimulators.sleep_depriver_stimulators import (
    AGO,
    ExperimentalSleepDepStimulator,
    MiddleCrossingStimulator,
    OptomotorSleepDepriver,
    OptoSleepDepriver,
    SleepDepStimulator,
    mAGO,
)
from ethoscope.stimulators.sleep_restriction_stimulators import (
    SimpleTimeRestrictedStimulator,
    mAGOSleepRestriction,
)
from ethoscope.stimulators.stimulators import DefaultStimulator
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.utils import pi
from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.description import DescribedObject
from ethoscope.utils.scheduler import (  # noqa: F401
    TimedStop,
    TimedStopError,
    format_countdown,
    timedStop,  # resolved by name from configurations saved by earlier versions
)


class ExperimentalInformation(DescribedObject):

    _description = {
        "overview": "Optional information about your experiment",
        "arguments": [
            {
                "type": "str",
                "name": "name",
                "description": "Who are you?",
                "default": "",
                "asknode": "users",
                "required": "required",
            },
            {
                "type": "str",
                "name": "location",
                "description": "Where is your device",
                "default": "",
                "asknode": "incubators",
                "required": "required",
            },
            {
                "type": "str",
                "name": "code",
                "description": "Would you like to add any code to the resulting filename or metadata?",
                "default": "",
            },
            {
                "type": "str",
                "name": "sensor",
                "description": "url to access the relevant ethoscope sensor",
                "default": "",
                "asknode": "sensors",
                "hidden": "true",
            },
            {
                "type": "str",
                "name": "lights_on",
                "description": "Light schedule: lights on time (HH:MM)",
                "default": "",
                "hidden": "true",
            },
            {
                "type": "str",
                "name": "lights_off",
                "description": "Light schedule: lights off time (HH:MM)",
                "default": "",
                "hidden": "true",
            },
            {
                "type": "int",
                "name": "light_period_minutes",
                "description": "Light schedule: cycle length in minutes (1440 = 24h)",
                "default": 1440,
                "hidden": "true",
            },
            {
                "type": "str",
                "name": "light_cycle_anchor",
                "description": "Light schedule: ZT0 unix timestamp (empty for wall-clock midnight)",
                "default": "",
                "hidden": "true",
            },
            {
                "type": "int",
                "name": "fade_in_seconds",
                "description": "Light schedule: panel ramp-up duration at sunrise (s)",
                "default": 1,
                "hidden": "true",
            },
            {
                "type": "int",
                "name": "fade_out_seconds",
                "description": "Light schedule: panel ramp-down duration at sunset (s)",
                "default": 1,
                "hidden": "true",
            },
            {
                "type": "int",
                "name": "max_light",
                "description": "Light schedule: peak panel brightness (0..100 %)",
                "default": 100,
                "hidden": "true",
            },
            {
                "type": "int",
                "name": "crepuscular",
                "description": "Light schedule: 1 = sunset-like S-curve fade, 0 = hard on/off",
                "default": 0,
                "hidden": "true",
            },
        ],
    }

    def __init__(
        self,
        name="",
        location="",
        code="",
        sensor="",
        lights_on="",
        lights_off="",
        light_period_minutes=1440,
        light_cycle_anchor="",
        fade_in_seconds=1,
        fade_out_seconds=1,
        max_light=100,
        crepuscular=0,
    ):
        self._check_code(code)
        self._info_dic = {
            "name": name,
            "location": location,
            "code": code,
            "sensor": sensor,
            "lights_on": lights_on,
            "lights_off": lights_off,
            "light_period_minutes": light_period_minutes,
            "light_cycle_anchor": light_cycle_anchor,
            "fade_in_seconds": fade_in_seconds,
            "fade_out_seconds": fade_out_seconds,
            "max_light": max_light,
            "crepuscular": crepuscular,
        }

    def _check_code(self, code):
        r = re.compile(r"[^a-zA-Z0-9-]")
        clean_code = r.sub("", code)
        if len(code) != len(clean_code):
            logging.error(f"The provided string contains unallowed characters: {code}")
            raise Exception(
                "Code contains special characters. Please use only letters, digits or -"
            )

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
    LIGHT_SCHEDULE_FILE = "/run/ethoscope/light_schedule.json"

    # How often the autostop supervisor compares the clock against its target.
    # It polls rather than sleeping out a countdown so that a clock correction -
    # which the node pushes to devices routinely - moves the stop with the clock
    # instead of leaving it where the arithmetic put it at start. Twenty seconds
    # is invisible against experiments measured in days and costs nothing.
    _AUTOSTOP_POLL_SECONDS = 20

    # Class-level defaults so stop() is safe on any instance, including one whose
    # __init__ raised part way through - __del__ calls stop() on it regardless.
    # _init_autostop_state() shadows all four with per-instance values.
    _autostop_at = None
    _autostop_cancel = None
    _autostop_thread = None
    _autostop_fired = False

    _option_dict = OrderedDict(
        [
            (
                "experimental_info",
                {
                    "possible_classes": [ExperimentalInformation],
                },
            ),
            (
                "interactor",
                {
                    "possible_classes": [
                        DefaultStimulator,
                        ComposedStimulator,
                        SleepDepStimulator,
                        OptomotorSleepDepriver,
                        MiddleCrossingStimulator,
                        # SystematicSleepDepInteractor,
                        ExperimentalSleepDepStimulator,
                        # GearMotorSleepDepStimulator,
                        # DynamicOdourDeliverer,
                        DynamicOdourSleepDepriver,
                        OptoMidlineCrossStimulator,
                        OptoSleepDepriver,
                        MiddleCrossingOdourStimulator,
                        MiddleCrossingOdourStimulatorFlushed,
                        mAGO,
                        AGO,
                        mAGOSleepRestriction,
                        SimpleTimeRestrictedStimulator,
                        MultiStimulator,
                    ],
                },
            ),
            (
                "roi_builder",
                {
                    "possible_classes": [FileBasedROIBuilder, TargetGridROIBuilder],
                },
            ),
            (
                "tracker",
                {
                    "possible_classes": [AdaptiveBGModel],
                },
            ),
            (
                "drawer",
                {
                    "possible_classes": [DefaultDrawer, NullDrawer],
                },
            ),
            (
                "camera",
                {
                    "possible_classes": [
                        OurPiCameraAsync,
                        MovieVirtualCamera,
                        V4L2Camera,
                    ],
                },
            ),
            (
                "result_writer",
                {
                    "possible_classes": [
                        SQLiteResultWriter,
                        MySQLResultWriter,
                    ],
                },
            ),
            (
                "time_control",
                {
                    "possible_classes": [TimedStop],
                },
            ),
        ]
    )

    # some classes do not need to be offered as choices to the user in normal conditions
    # these are shown only if the machine is not a PI
    _is_a_rPi = pi.isMachinePI() and pi.hasPiCamera() and not pi.isExperimental()
    _hidden_options = {"camera", "tracker"}  # result_writer is now always available

    for k in _option_dict:
        _option_dict[k]["class"] = _option_dict[k]["possible_classes"][0]
        _option_dict[k]["kwargs"] = {}

    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"

    # give the database an ethoscope specific name
    # future proof in case we want to use a remote server
    _db_credentials = {
        "name": f"{pi.get_machine_name()}_db",
        "user": "ethoscope",
        "password": "ethoscope",
    }

    _default_monitor_info = {
        # fixme, not needed
        "last_positions": None,
        "last_time_stamp": 0,
        "fps": 0,
    }

    _persistent_state_file = pi.PERSISTENT_STATE
    _last_run_info = "/var/run/last_run.ethoscope"

    def __init__(
        self, machine_id, name, version, ethoscope_dir, data=None, *args, **kwargs
    ):

        self._monit_args = args
        self._monit_kwargs = kwargs
        self._metadata = None
        # Why the last ROI build failed, so the user is told the real cause
        # rather than a fixed "insufficient targets" message.
        self._roi_build_error = None

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
            if space_result.get("cleanup_performed", False):
                logging.info(
                    f"Disk space cleanup completed: {space_result.get('cleanup_summary', {}).get('files_deleted', 0)} files removed"
                )
        except Exception as e:
            logging.warning(f"Disk space management failed, continuing anyway: {e}")

        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")

        # Database metadata tracking
        self._tracking_start_time = None
        # DatabaseMetadataCache is only compatible with MySQL databases
        # For SQLite, we'll create it only when needed (see metadata cache initialization)
        self._metadata_cache = None

        # todo add 'data' -> how monitor was started to metadata
        self._info = {
            "status": "stopped",
            "time": time.time(),  # this is time of last interaction, e.g. last reboot, last start, last stop.
            "error": None,
            "log_file": os.path.join(self._tmp_dir, self._log_file),
            "dbg_img": os.path.join(self._tmp_dir, self._dbg_img_file),
            "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
            "db_name": self._db_credentials["name"],
            "monitor_info": self._default_monitor_info,
            # "user_options": self._get_user_options(),
            "experimental_info": {},
            "database_info": {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "initializing",
            },
            "id": machine_id,
            "name": name,
            "version": version,
            "used_space": pi.get_partition_info(ethoscope_dir)["Use%"].replace("%", ""),
            "autostop": False,
            "autostop_at": None,
        }
        self._monit = None
        self._drawer = None  # Initialize drawer to None until monitor starts

        # Initialize cache directory first
        self._cache_dir = os.path.join(ethoscope_dir, "cache")

        # Try to get last experiment info from cache files (replaces pickle file)
        try:
            # Create temporary cache instance to read last experiment info
            temp_cache = create_metadata_cache(
                db_credentials={"name": "temp"},  # Temporary, will be replaced
                device_name=name,
                cache_dir=self._cache_dir,
                database_type="SQLite3",  # Default, auto-detected later
            )
            last_experiment_info = temp_cache.get_last_experiment_info()
            if last_experiment_info and isinstance(last_experiment_info, dict):
                self._info.update(last_experiment_info)
                logging.info(
                    f"Loaded last experiment info from cache: user={last_experiment_info.get('previous_user', 'unknown')}"
                )
            elif last_experiment_info:
                logging.warning(
                    f"Cache returned non-dict experiment info: {type(last_experiment_info)}"
                )
        except Exception as e:
            logging.warning(f"Failed to load last experiment info from cache: {e}")
            # Ensure _info is still a dictionary even if cache loading fails
            if not isinstance(self._info, dict):
                logging.error(
                    "self._info became non-dict after cache failure, resetting"
                )
                self._info = {
                    "id": machine_id,
                    "name": name,
                    "version": version,
                    "used_space": pi.get_partition_info(ethoscope_dir)["Use%"].replace(
                        "%", ""
                    ),
                }

        # Final safety check: ensure _info is always a dictionary
        if not isinstance(self._info, dict):
            logging.error(
                "self._info is not a dictionary after initialization, creating new one"
            )
            self._info = {
                "id": machine_id,
                "name": name,
                "version": version,
                "used_space": pi.get_partition_info(ethoscope_dir)["Use%"].replace(
                    "%", ""
                ),
            }

        # Initialize database info now that _info is fully constructed
        if self._metadata_cache is not None:
            try:
                self._info["database_info"] = self._metadata_cache.get_database_info()
            except Exception as e:
                logging.warning(
                    f"Failed to get database info from metadata cache during initialization: {e}"
                )
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "error",
                }
        else:
            self._info["database_info"] = {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "no_cache",
            }

        # Check for existing backup filename from metadata cache during initialization
        # This ensures backup_filename is available immediately for status requests
        if "backup_filename" not in self._info:
            if self._metadata_cache is not None:
                try:
                    existing_backup_filename = (
                        self._metadata_cache.get_backup_filename()
                    )
                    if existing_backup_filename:
                        self._info["backup_filename"] = existing_backup_filename
                        logging.info(
                            f"Found existing backup filename during initialization: {existing_backup_filename}"
                        )
                except Exception as e:
                    logging.warning(
                        f"Failed to get backup filename from metadata cache during initialization: {e}"
                    )

        self._init_autostop_state()
        self._parse_user_options(data)

        logging.info("Starting a new monitor control thread")
        super().__init__()

    def _init_autostop_state(self):
        """
        Set up the bookkeeping for the automatic stop.

        Called from the constructor of every control thread. It is separate from
        __init__ because ControlThreadVideoRecording builds its own _info and calls
        Thread.__init__ directly, so there is no single constructor to hang this on.
        """
        self._autostop_at = None
        self._autostop_cancel = None
        self._autostop_thread = None
        self._autostop_fired = False

    def _arm_autostop(self, start_time=None, kwargs=None):
        """
        Schedule the automatic stop the user asked for, if any.

        Args:
            start_time (float): Unix timestamp the experiment is starting from. A
                duration is counted from here. Defaults to now.
            kwargs (dict): TimedStop arguments to use instead of the ones the
                experiment was started with. Used to change the stop of a run that
                is already under way.

        Raises:
            TimedStopError: If the requested stop is malformed or already past. This
                is deliberately fatal: it happens at the very start of the run, and a
                user who asked for an automatic stop and did not get one would only
                find out days later.
        """
        if start_time is None:
            start_time = time.time()

        TimedStopClass = self._option_dict["time_control"]["class"]
        if kwargs is None:
            kwargs = self._option_dict["time_control"]["kwargs"]
        timed_stop = TimedStopClass(**kwargs)

        self._set_autostop(timed_stop.resolve(start_time), reference=start_time)

    def set_autostop(self, data=None):
        """
        Change or cancel the automatic stop of an experiment already under way.

        This is the point of the feature for anyone who is already running: extending
        a run otherwise means stopping and restarting it, which is exactly what an
        automatic stop is there to avoid.

        Args:
            data (dict): TimedStop arguments. ``stop_at`` is an absolute time and
                means what it says. A ``duration`` is counted from **now**, not from
                when the experiment started, so "01:00:00" reads as "run for one more
                day". Empty, or a zero duration with no ``stop_at``, cancels the stop.

        Returns:
            dict: The resulting ``autostop`` run length and ``autostop_at`` timestamp.

        Raises:
            TimedStopError: If the requested stop is malformed or already past. The
                experiment is left running on its existing schedule.
        """
        now = time.time()
        self._arm_autostop(start_time=now, kwargs=dict(data or {}))

        return {
            "autostop": self._info["autostop"],
            "autostop_at": self._info["autostop_at"],
        }

    def _set_autostop(self, stop_at, reference=None):
        """
        Point the automatic stop at a given time, replacing any existing one.

        Args:
            stop_at (float|None): Unix timestamp to stop at, or None to cancel.
            reference (float): Unix timestamp the reported run length is measured
                from. Defaults to now, which is what a stop re-armed mid-experiment
                wants; arming at the start passes the start time, so a 24 h run reads
                as one day rather than as the 23:59 that measuring from a moment later
                and truncating would give.
        """
        self._cancel_autostop()

        self._info["autostop_at"] = stop_at
        if stop_at is None:
            self._info["autostop"] = False
            return

        self._autostop_at = stop_at
        # The interface has always been given a DD:HH:MM run length rather than a
        # timestamp, so keep feeding it one; autostop_at is what anything new
        # should read.
        if reference is None:
            reference = time.time()
        self._info["autostop"] = format_countdown(stop_at - reference)

        self._autostop_cancel = threading.Event()
        self._autostop_thread = threading.Thread(
            target=self._autostop_supervisor,
            args=(self._autostop_cancel,),
            daemon=True,
            name="autostop_supervisor",
        )
        self._autostop_thread.start()
        logging.info(
            "Experiment will stop automatically at "
            f"{datetime.datetime.fromtimestamp(stop_at).isoformat(timespec='seconds')}"
        )

    def _cancel_autostop(self):
        """
        Cancel any scheduled automatic stop.

        Safe to call when nothing is scheduled, and safe to call from the supervisor
        itself - the thread is never joined, so a supervisor that cancels itself on
        the way out does not deadlock.
        """
        if self._autostop_cancel is not None:
            self._autostop_cancel.set()

        self._autostop_at = None
        self._autostop_cancel = None
        self._autostop_thread = None
        self._info["autostop_at"] = None

    def _autostop_supervisor(self, cancel):
        """
        Wait for the scheduled stop time, then stop the experiment.

        Args:
            cancel (threading.Event): Set when this supervisor has been superseded or
                cancelled. Passed in rather than read off the instance so that a
                supervisor replaced mid-run cannot act on its successor's state.
        """
        while True:
            target = self._autostop_at
            if target is None or cancel.is_set():
                return

            remaining = target - time.time()
            if remaining <= 0:
                logging.info("Automatic stop time reached, stopping the experiment")
                self._autostop_fired = True
                self.stop()
                return

            # Sleep the poll interval, or the remainder if that is shorter, so the
            # stop lands on the second rather than up to a poll interval late.
            if cancel.wait(min(self._AUTOSTOP_POLL_SECONDS, remaining)):
                return

    def _create_backup_filename(self):
        current_time = self.info["time"]
        date_and_time = datetime.datetime.utcfromtimestamp(current_time).strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
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
        return {
            "kernel": os.uname()[2],
            "pi_version": pi.pi_version(),
            "camera": pi.getPiCameraVersion(),
            "SD_CARD_AGE": pi.get_SD_CARD_AGE(),
            "partitions": pi.get_partition_info(),
            "SD_CARD_NAME": pi.get_SD_CARD_NAME(),
        }

    @staticmethod
    def _acquisition_metadata(cam, TrackerClass=None):
        """
        Acquisition context for the METADATA table, one queryable field each.

        Everything here is needed to decide whether two experiments are
        comparable. Sleep scoring depends on the sampling rate and on image
        noise, both of which depend on the FPS cap, the analogue gain, the
        camera tuning and the Pi generation - none of which used to be recorded
        anywhere, so a database could not be audited after the fact (issue #222).
        ``hardware_info`` carries some of this already, but only as one
        stringified blob that cannot be queried or compared across runs.

        Every field is collected defensively: diagnostics must never be the
        reason an experiment fails to start.

        Args:
            cam: The camera instance in use.
            TrackerClass: The tracker class selected for this run.

        Returns:
            dict: Metadata fields, with None where a value is unavailable.
        """

        def _safe(fn, default=None):
            try:
                return fn()
            except Exception as e:
                logging.warning(f"Could not collect acquisition metadata: {e}")
                return default

        def _picamera2_version():
            from importlib.metadata import version

            return version("picamera2")

        def _camera_attr(name):
            """
            Read an acquisition attribute from the camera or its frame grabber.

            The Pi cameras delegate acquisition to a frame-grabber process held
            as ``_p``, so target_fps and the exposure regime live one level down;
            simpler cameras keep them on the camera itself. Both are checked
            because reading only the camera left these two fields empty in the
            database on a real device.
            """
            for obj in (cam, getattr(cam, "_p", None)):
                if obj is not None and getattr(obj, name, None) is not None:
                    return getattr(obj, name)
            return None

        metadata = {
            # Sampling rate: the configured ceiling, and what the camera was
            # actually asked for (they differ for video recording).
            "maxfps_setting": _safe(pi.get_maxfps_setting),
            "target_fps": _safe(lambda: _camera_attr("_target_fps")),
            # Exposure regime. With the gain pinned, the FPS ceiling doubles as
            # an exposure ceiling; 'exposure_decoupled' records whether this
            # build lets auto-exposure integrate beyond 1 / target_fps.
            "gain_setting": _safe(pi.get_gain_setting),
            "exposure_decoupled": _safe(lambda: _camera_attr("_exposure_decoupled")),
            # Camera tuning: what this sensor needs, and what was really loaded.
            # "DEFAULT" means it fell back to libcamera's colour tuning and this
            # run is not comparable with a correctly tuned one.
            "camera_tuning_expected": _safe(pi.get_camera_tuning_file),
            "camera_tuning_loaded": _safe(pi.get_camera_tuning_status),
            "camera_sensor": _safe(lambda: pi.getPiCameraVersion()),
            # Platform: determines whether the FPS ceiling actually binds.
            "pi_version": _safe(pi.pi_version),
            "picamera2_version": _safe(_picamera2_version),
            # Which algorithm produced the positions in this database.
            "tracker_class": (
                getattr(TrackerClass, "__name__", None) if TrackerClass else None
            ),
        }

        return {k: str(v) if v is not None else None for k, v in metadata.items()}

    @property
    def info(self):
        self._update_info()
        # Safety check: ensure we always return a dictionary
        if not isinstance(self._info, dict):
            logging.error(
                f"self._info is not a dictionary ({type(self._info)}), creating emergency fallback"
            )
            self._info = {
                "id": getattr(self, "_machine_id", "unknown"),
                "name": getattr(self, "_name", "unknown"),
                "version": "unknown",
                "error": "info corruption detected and recovered",
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
                    recent_cache_path = cache_files[0]["path"]
                    if os.path.exists(recent_cache_path):
                        with open(recent_cache_path) as f:
                            cache_data = json.load(f)

                        # Check if experiment was stopped gracefully
                        stopped_gracefully = cache_data.get("stopped_gracefully", False)
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
            if (
                key not in self._hidden_options
                or pi.isExperimental()
                or not self._is_a_rPi
            ):
                out[key] = []
                for p in value["possible_classes"]:
                    try:
                        if pi.isExperimental():
                            d = p.__dict__["_description"]
                            d["name"] = p.__name__
                            out[key].append(d)

                        elif (
                            not pi.isExperimental()
                            and "hidden" not in p.__dict__["_description"]
                            or not p.__dict__["_description"]["hidden"]
                        ):
                            d = p.__dict__["_description"]
                            d["name"] = p.__name__
                            out[key].append(d)

                    except KeyError:
                        continue

        out_curated = {}
        for key, value in list(out.items()):
            if len(value) > 0:
                out_curated[key] = value

        return out_curated

    def _parse_one_user_option(self, field, data):

        try:
            subdata = data[field]
        except KeyError:
            logging.warning(f"No field {field}, using default")
            return None, {}

        Class = eval(subdata["name"])
        kwargs = subdata["arguments"]

        return Class, kwargs

    def _parse_user_options(self, data):

        if data is None:
            return

        for key in list(self._option_dict.keys()):

            Class, kwargs = self._parse_one_user_option(key, data)
            # when no field is present in the JSON config, we get the default class

            if Class is None:

                self._option_dict[key]["class"] = self._option_dict[key][
                    "possible_classes"
                ][0]
                self._option_dict[key]["kwargs"] = {}
                continue

            self._option_dict[key]["class"] = Class
            self._option_dict[key]["kwargs"] = kwargs

    def _update_info(self):
        """
        Updates a dictionary with information that relates to the current status of the machine, ie data linked for instance to data acquisition
        Information that is not related to control and it is not experiment-dependent will come from elsewhere
        """

        if self._monit is None:
            return
        t = self._monit.last_time_stamp

        frame_idx = self._monit.last_frame_idx
        wall_time = time.time()
        dt = wall_time - self._last_info_t_stamp
        df = float(frame_idx - self._last_info_frame_idx)

        if self._last_info_t_stamp == 0 or dt > 0:
            f = round(df / dt, 2)
        else:
            f = "NaN"

        if t is not None:  # and p is not None:
            self._info["monitor_info"] = {
                # "last_positions":pos,
                "last_time_stamp": t,
                "fps": f,
                # Acquisition quality, refreshed by the monitor on a slow
                # interval. Rides along with the existing payload so the node
                # needs no new endpoint to display it (issue #222).
                "diagnostics": self._monit.diagnostics,
            }

        if self._drawer:
            frame = self._drawer.last_drawn_frame
            if frame is not None and (wall_time - self._last_img_write_time) >= 1.0:
                cv2.imwrite(
                    self._info["last_drawn_img"],
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 50],
                )
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
                    "db_status": "error",
                }
        else:
            self._info["database_info"] = {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "no_cache",
            }

        # Update backup filename from result writer if available during tracking
        if self._monit and hasattr(self._monit, "_result_writer"):
            try:
                backup_filename = self._monit._result_writer.get_backup_filename()
                if backup_filename:
                    self._info["backup_filename"] = backup_filename
            except Exception as e:
                logging.warning(
                    f"Failed to get backup filename from result writer: {e}"
                )

        self._last_info_t_stamp = wall_time
        self._last_info_frame_idx = frame_idx

    def _start_tracking(
        self,
        camera,
        result_writer,
        rois,
        reference_points,
        TrackerClass,
        tracker_kwargs,
        hardware_connection,
        StimulatorClass,
        stimulator_kwargs,
        time_offset=0,
    ):

        # Here the stimulator passes args. Hardware connection was previously open as thread.
        logging.info(
            f"Creating stimulators: StimulatorClass={StimulatorClass}, hardware_connection={hardware_connection}, stimulator_kwargs={stimulator_kwargs}"
        )
        logging.info(f"Number of ROIs: {len(rois)}")

        # Reason: this used to fall back to DefaultStimulator when construction
        # failed, so a bad parameter or an unknown trigger_type produced an
        # experiment that tracked perfectly, looked healthy in the UI and
        # delivered nothing at all — undetectable until the data came back days
        # later. A stimulator the user asked for must either work or say so.
        stimulators = []
        for i, _roi in enumerate(rois):
            try:
                stimulator = StimulatorClass(hardware_connection, **stimulator_kwargs)
            except Exception as e:
                raise EthoscopeException(
                    f"Could not build {StimulatorClass.__name__} for ROI {i+1} "
                    f"with {stimulator_kwargs}: {e}. Refusing to start an "
                    f"experiment that would silently deliver no stimulus."
                ) from e
            logging.info(
                f"Successfully created stimulator {i+1}/{len(rois)}: {type(stimulator).__name__}"
            )
            stimulators.append(stimulator)

        kwargs = self._monit_kwargs.copy()
        kwargs.update(tracker_kwargs)

        logging.info(f"Creating Monitor with {len(stimulators)} stimulators")
        for i, stimulator in enumerate(stimulators):
            logging.info(f"Stimulator {i+1}: {type(stimulator).__name__}")

        self._monit = Monitor(
            camera,
            TrackerClass,
            rois,
            *self._monit_args,
            reference_points=reference_points,
            stimulators=stimulators,
            time_offset=time_offset,
        )

        self._info["status"] = "running"
        logging.info(
            "Setting monitor status as running: '{}'".format(self._info["status"])
        )

        # Set tracking start time for database metadata
        # Use the original experiment start time from metadata/backup filename, not current time
        if (
            hasattr(self, "_metadata")
            and self._metadata is not None
            and "date_time" in self._metadata
        ):
            # Use experiment start time from metadata (already updated for dbAppender)
            self._tracking_start_time = self._metadata["date_time"]
            logging.info(
                f"Using experiment start time from metadata: {self._tracking_start_time}"
            )

        elif self._info.get("backup_filename"):
            # Extract start time from backup filename as fallback
            try:
                # Format: YYYY-MM-DD_HH-MM-SS_machine_id.db
                timestamp_part = self._info["backup_filename"].split("_")[
                    :2
                ]  # Only take date and time parts
                timestamp_str = "_".join(timestamp_part)
                self._tracking_start_time = time.mktime(
                    time.strptime(timestamp_str, "%Y-%m-%d_%H-%M-%S")
                )
                logging.info(
                    f"Using experiment start time from backup filename: {self._tracking_start_time}"
                )
            except (ValueError, IndexError) as e:
                logging.warning(
                    f"Could not parse time from backup filename {self._info['backup_filename']}: {e}"
                )
                self._tracking_start_time = time.time()
        else:
            # Fallback to current time if no other information available
            self._tracking_start_time = time.time()
            logging.warning(
                "Using current time as tracking start time (no metadata/backup filename available)"
            )

        # Initialize database metadata for tracking
        if self._metadata_cache is not None:
            try:
                self._info["database_info"] = self._metadata_cache.get_database_info()
            except Exception as e:
                logging.warning(
                    f"Failed to get database info from metadata cache for tracking: {e}"
                )
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "error",
                }
        else:
            self._info["database_info"] = {
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "no_cache",
            }

        self._monit.run(result_writer, self._drawer)

    def _set_tracking_from_scratch(self):
        """ """
        CameraClass = self._option_dict["camera"]["class"]
        camera_kwargs = self._option_dict["camera"]["kwargs"]

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
                raise EthoscopeException(
                    "Tracking disabled: No camera hardware available. This ethoscope cannot perform video tracking or recording without camera hardware."
                ) from e
            else:
                raise e

        # Force the light module ON during target detection so wells are evenly
        # illuminated. Released in the finally block; the user-configured schedule
        # is restored by _write_light_schedule() further below.
        self._force_lights_on_for_targets()
        try:
            reference_points, rois = self._detect_and_store_targets(cam)
        finally:
            self._release_lights_after_targets()

        # Handle detection failure
        if reference_points is None or rois is None:
            try:
                cam._close()
                # Add a delay to allow camera hardware to reset
                time.sleep(2.0)
                logging.info(
                    "Camera cleanup completed, hardware should be available for next attempt"
                )
            except Exception as cleanup_error:
                logging.error(f"Error during camera cleanup: {cleanup_error}")
            # Return None to indicate failure instead of raising exception
            return None

        logging.info("Initialising monitor")
        cam.restart()

        ExpInfoClass = self._option_dict["experimental_info"]["class"]
        exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]

        # Debug: log what's being passed to ExperimentalInformation
        logging.info(
            f"DEBUG: Creating ExperimentalInformation with kwargs: {exp_info_kwargs}"
        )

        self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic

        # Debug: log the final experimental_info
        logging.info(
            f"DEBUG: Final experimental_info created: {self._info['experimental_info']}"
        )

        # Write light schedule config for the light daemon service
        self._write_light_schedule()

        # here the hardwareconnection call the interface class without passing any argument!
        hardware_connection = HardwareConnection(HardWareInterfaceClass)

        # creates a unique tracking id to label this tracking run
        self._info["experimental_info"]["run_id"] = secrets.token_hex(8)

        if self._info["experimental_info"]["sensor"]:
            # if is URL:
            sensor = EthoscopeSensor(self._info["experimental_info"]["sensor"])
            logging.info(
                "Using sensor with URL {}".format(
                    self._info["experimental_info"]["sensor"]
                )
            )
        else:
            sensor = None

        # Use current camera start time for experiment timestamp
        experiment_time = cam.start_time
        self._info["time"] = experiment_time

        # Create initial backup filename - result writer may override this later
        self._info["backup_filename"] = self._create_backup_filename()
        logging.info(
            f"Creating initial backup filename: {self._info['backup_filename']}"
        )

        # Determine result writer type
        ResultWriterClass = self._option_dict["result_writer"]["class"]
        if hasattr(ResultWriterClass, "_database_type"):
            result_writer_type = ResultWriterClass._database_type
        else:
            result_writer_type = ResultWriterClass.__name__

        self._info["interactor"] = {}
        self._info["interactor"]["name"] = str(self._option_dict["interactor"]["class"])
        self._info["interactor"].update(self._option_dict["interactor"]["kwargs"])

        # For SQLite, construct the source database file path using consistent directory structure
        # Path: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/{backup_filename}
        sqlite_source_path = None
        if (
            result_writer_type == "SQLite3"
            or result_writer_type == "SQLiteResultWriter"
        ):
            # Create new database with current timestamp
            # Parse backup filename format: YYYY-MM-DD_HH-MM-SS_machine_id.db
            filename_parts = self._info["backup_filename"].replace(".db", "").split("_")
            if len(filename_parts) >= 3:
                backup_date = filename_parts[0]
                backup_time = filename_parts[1]
                etho_id = "_".join(
                    filename_parts[2:]
                )  # Join remaining parts as machine_id might contain underscores
                sqlite_source_path = f"/ethoscope_data/results/{etho_id}/{self._info['name']}/{backup_date}_{backup_time}/{self._info['backup_filename']}"
            else:
                raise ValueError(
                    f"Invalid backup filename format: {self._info['backup_filename']}"
                )

        self._metadata = {
            "machine_id": self._info["id"],
            "machine_name": self._info["name"],
            "date_time": experiment_time,
            "frame_width": cam.width,
            "frame_height": cam.height,
            "version": self._info["version"]["id"],
            "experimental_info": str(self._info["experimental_info"]),
            "selected_options": str(self._option_dict),
            "hardware_info": str(self.hw_info),
            "reference_points": str([(p[0], p[1]) for p in reference_points]),
            "backup_filename": self._info["backup_filename"],
            "result_writer_type": result_writer_type,
            "sqlite_source_path": sqlite_source_path,
        }
        self._metadata.update(self._acquisition_metadata(cam, TrackerClass))

        # This is useful to retrieve the latest run's information after a reboot
        # Now stored in cache files instead of separate pickle file
        experiment_info_to_store = {
            "date_time": self._info["time"],
            "backup_filename": self._info["backup_filename"],
            "user": self._info["experimental_info"]["name"],
            "location": self._info["experimental_info"]["location"],
            "result_writer_type": result_writer_type,
            "sqlite_source_path": sqlite_source_path,
            "run_id": self._info["experimental_info"]["run_id"],
        }

        # hardware_interface is a running thread
        # Use the selected result writer class and pass appropriate arguments
        result_writer_kwargs.update(
            {
                "take_frame_shots": True,
                "erase_old_db": True,  # Always create new database (dbAppender handles append internally)
                "sensor": sensor,
            }
        )

        # Configure database credentials and metadata cache based on result writer type
        if (
            result_writer_type == "SQLite3"
            or result_writer_type == "SQLiteResultWriter"
        ):
            # SQLite uses the consistent directory structure for database file path
            if sqlite_source_path is None:
                raise ValueError(
                    "SQLite source path is None - backup filename parsing failed"
                )

            # Ensure the directory structure exists before creating the database
            sqlite_dir = os.path.dirname(sqlite_source_path)
            os.makedirs(sqlite_dir, exist_ok=True)
            logging.info(f"Created SQLite directory structure: {sqlite_dir}")

            # Create clean SQLite credentials (only database path, no MySQL connection params)
            sqlite_credentials = {"name": sqlite_source_path}
            rw = ResultWriterClass(
                sqlite_credentials, rois, self._metadata, **result_writer_kwargs
            )

            # Get the backup filename from the result writer (may be different from initial one)
            backup_filename_from_writer = rw.get_backup_filename()
            if backup_filename_from_writer:
                self._info["backup_filename"] = backup_filename_from_writer
                logging.info(
                    f"Updated backup filename from result writer: {backup_filename_from_writer}"
                )

            # Initialize SQLite metadata cache for JSON file generation
            # Use clean SQLite credentials (only database path)
            cache_credentials = {"name": sqlite_source_path}
            self._metadata_cache = create_metadata_cache(
                db_credentials=cache_credentials,
                device_name=self._info["name"],
                cache_dir=self._cache_dir,
                database_type="SQLite3",
            )
        elif result_writer_type == "dbAppender":
            # dbAppender handles database discovery and append functionality internally
            rw = ResultWriterClass(
                db_credentials=self._db_credentials,
                rois=rois,
                metadata=self._metadata,
                **result_writer_kwargs,
            )

            # Get the backup filename from the result writer (may be different from initial one)
            backup_filename_from_writer = rw.get_backup_filename()
            if backup_filename_from_writer:
                self._info["backup_filename"] = backup_filename_from_writer
                logging.info(
                    f"Updated backup filename from result writer: {backup_filename_from_writer}"
                )

            # Initialize metadata cache based on detected database type
            # The dbAppender will have created the appropriate writer internally
            if hasattr(rw, "_writer") and hasattr(rw._writer, "_database_type"):
                db_type = rw._writer._database_type

                # Update result_writer_type to the actual database type instead of "dbAppender"
                result_writer_type = db_type
                logging.info(
                    f"dbAppender: Updated result_writer_type from 'dbAppender' to '{db_type}'"
                )

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
                    database_type=cache_db_type,
                )

                # For dbAppender, get the original experiment timestamp from the database
                # This ensures we reuse the existing cache file instead of creating a new one
                try:
                    original_timestamp = self._metadata_cache.get_database_timestamp()
                    if original_timestamp:
                        # Update the experiment time to use the original timestamp
                        experiment_time = original_timestamp
                        logging.info(
                            f"dbAppender: Using original experiment timestamp {original_timestamp} from database"
                        )

                        # Update metadata with original experiment time
                        self._metadata["date_time"] = experiment_time

                        # Update backup filename to match original experiment
                        original_backup_filename = (
                            self._metadata_cache.get_backup_filename()
                        )
                        if original_backup_filename:
                            self._info["backup_filename"] = original_backup_filename
                            logging.info(
                                f"dbAppender: Using original backup filename {original_backup_filename}"
                            )
                        else:
                            # Generate backup filename from original timestamp
                            ts_str = time.strftime(
                                "%Y-%m-%d_%H-%M-%S", time.localtime(original_timestamp)
                            )
                            self._info["backup_filename"] = (
                                f"{ts_str}_{self._info['id']}.db"
                            )
                            logging.info(
                                f"dbAppender: Generated backup filename from original timestamp: {self._info['backup_filename']}"
                            )
                    else:
                        logging.warning(
                            "dbAppender: Could not retrieve original experiment timestamp, using new timestamp"
                        )
                except Exception as e:
                    logging.warning(
                        f"dbAppender: Failed to get original experiment timestamp: {e}"
                    )
            else:
                # Fallback to standard metadata cache
                self._metadata_cache = create_metadata_cache(
                    db_credentials=self._db_credentials,
                    device_name=self._info["name"],
                    cache_dir=self._cache_dir,
                    database_type="MySQL",
                )

            # Update metadata and experiment_info_to_store with the correct result_writer_type
            # (they were created before we knew the actual database type)
            self._metadata["result_writer_type"] = result_writer_type
            self._metadata["sqlite_source_path"] = sqlite_source_path
            experiment_info_to_store["result_writer_type"] = result_writer_type
            experiment_info_to_store["sqlite_source_path"] = sqlite_source_path
        else:
            # MySQL uses standard credentials and metadata cache
            rw = ResultWriterClass(
                self._db_credentials, rois, self._metadata, **result_writer_kwargs
            )

            # Get the backup filename from the result writer (may be different from initial one)
            backup_filename_from_writer = rw.get_backup_filename()
            if backup_filename_from_writer:
                self._info["backup_filename"] = backup_filename_from_writer
                logging.info(
                    f"Updated backup filename from result writer: {backup_filename_from_writer}"
                )

            # Initialize MySQL metadata cache
            self._metadata_cache = create_metadata_cache(
                db_credentials=self._db_credentials,
                device_name=self._info["name"],
                cache_dir=self._cache_dir,
                database_type="MySQL",
            )

        # Store experiment information in cache (replaces last_run_info file)
        if self._metadata_cache:
            # Use the experiment timestamp (which may be original timestamp for dbAppender)
            tracking_start_time = experiment_time
            self._metadata_cache.store_experiment_info(
                tracking_start_time, experiment_info_to_store
            )

        time_offset = 0
        # dbAppender handles append functionality and time offset internally
        if hasattr(rw, "append"):
            time_offset = rw.append()

        return (
            cam,
            rw,
            rois,
            reference_points,
            TrackerClass,
            tracker_kwargs,
            hardware_connection,
            StimulatorClass,
            stimulator_kwargs,
            time_offset,
        )

    def _detect_and_store_targets(self, cam):
        """
        Detect targets using ROI builder and store coordinates in experimental_info.

        Args:
            cam: Camera instance to use for detection

        Returns:
            tuple: (reference_points, rois) or (None, None) if detection failed
        """
        ROIBuilderClass = self._option_dict["roi_builder"]["class"]
        roi_builder_kwargs = self._option_dict["roi_builder"]["kwargs"]

        try:
            # Inside the try: constructing the builder is where a bad or missing
            # template fails, and that escaped as a raw traceback in the device's
            # error field rather than a sentence the user can act on.
            roi_builder = ROIBuilderClass(**roi_builder_kwargs)

            reference_points, rois = roi_builder.build(cam)

            # Handle graceful failure when ROI building returns None values
            if reference_points is None or rois is None:
                logging.warning("ROI building failed: insufficient targets detected.")
                self._roi_build_error = (
                    "ROI building failed: insufficient targets detected. Please "
                    "check your arena has 3 circular targets visible."
                )
                # Save debug image to help user understand the issue
                self._save_roi_debug_image(cam, "Insufficient targets detected")
                return None, None

            # Store target coordinates in experimental_info for API access
            if "experimental_info" in self._info:
                self._info["experimental_info"]["target_coordinates"] = [
                    [float(p[0]), float(p[1])] for p in reference_points
                ]
                logging.info(
                    f"Stored {len(reference_points)} target coordinates in experimental_info"
                )

            return reference_points, rois

        except (EthoscopeException, Exception) as e:
            logging.error(f"Target detection failed: {e}")
            # Reason: keep the actual cause. It used to be logged and then
            # discarded, and every failure - a broken template, an OpenCV type
            # error, a missing file - was reported to the user as "insufficient
            # targets detected", sending them to check the arena and the camera
            # when the fault was elsewhere.
            self._roi_build_error = f"ROI building failed: {e}"
            # Save debug image with exception details
            self._save_roi_debug_image(cam, f"Target detection error: {str(e)}")
            return None, None

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
            if not timestamp.endswith(" "):
                import time

                tz_name = time.tzname[time.daylight]
                timestamp = f"{timestamp.rstrip()} {tz_name}"

            # Calculate text size to position it in bottom right
            text_size = cv2.getTextSize(timestamp, font, font_scale, thickness)[0]
            text_x = (
                debug_frame.shape[1] - text_size[0] - 10
            )  # 10 pixels from right edge
            text_y = debug_frame.shape[0] - 10  # 10 pixels from bottom edge

            cv2.putText(
                debug_frame,
                timestamp,
                (text_x, text_y),
                font,
                font_scale,
                color,
                thickness,
            )

            # Save the debug image
            debug_path = self._info["dbg_img"]
            cv2.imwrite(debug_path, debug_frame)
            logging.info(f"Debug image saved to: {debug_path}")

        except Exception as e:
            logging.error(f"Failed to save debug image: {e}")

    def _initialization_timeout_handler(self):
        """
        Emergency timeout handler that kills the ethoscope process if initialization takes too long.
        This prevents the ethoscope from hanging indefinitely in 'initialising' state.
        """
        time.sleep(120)  # Wait 2 minutes
        if self._info["status"] == "initialising":
            logging.critical(
                "INITIALIZATION TIMEOUT: Ethoscope has been stuck in initializing state for 2 minutes"
            )
            logging.critical(
                "This usually indicates a camera hardware or picamera2 compatibility issue"
            )
            logging.critical("Terminating ethoscope process to prevent indefinite hang")

            # Set error state before terminating
            self._info["status"] = "error"
            self._info["error"] = (
                "Initialization timeout: Process terminated after 2 minutes in initializing state"
            )
            self._info["time"] = time.time()

            # Force kill the current process
            os.kill(os.getpid(), signal.SIGKILL)

    def run(self):
        cam = None
        hardware_connection = None

        # Start timeout watchdog thread
        timeout_thread = threading.Thread(
            target=self._initialization_timeout_handler, daemon=True
        )
        timeout_thread.start()
        logging.info("Started initialization timeout watchdog (2 minute limit)")

        try:
            self._info["status"] = "initialising"
            logging.info("Starting Monitor thread")
            self._info["error"] = None
            self._last_info_t_stamp = 0
            self._last_info_frame_idx = 0

            # Armed before any of the expensive setup, so a malformed stop time is
            # reported straight away rather than after the ROIs have been built, and
            # so a stop scheduled during a long initialisation is still honoured.
            try:
                self._arm_autostop()
            except TimedStopError as e:
                # A stop time the user typed wrong, or one that has already passed.
                # Report it plainly and leave the device free to be started again,
                # rather than burying a readable message in a traceback.
                logging.error(f"Refusing to start: {e}")
                self._info["status"] = "stopped"
                self._info["error"] = str(e)
                return

            # Always create a new tracking instance (pickle resume logic removed)
            tracking_setup = self._set_tracking_from_scratch()

            # Handle graceful failure when tracking setup fails
            if tracking_setup is None:
                logging.warning(
                    "Tracking setup failed. Please check your arena setup and try again."
                )
                self._info["status"] = "stopped"  # Keep device available for restart
                self._info["error"] = self._roi_build_error or (
                    "ROI building failed: insufficient targets detected. Please "
                    "check your arena has 3 circular targets visible."
                )
                # Don't exit, just stop this tracking attempt - device remains available
                return  # Exit gracefully without crashing

            (
                cam,
                rw,
                rois,
                reference_points,
                TrackerClass,
                tracker_kwargs,
                hardware_connection,
                StimulatorClass,
                stimulator_kwargs,
                time_offset,
            ) = tracking_setup

            # Initialization completed successfully
            logging.info("Initialization completed successfully - starting tracking")

            with rw as result_writer:
                # Start tracking directly (pickle saving removed)
                self._start_tracking(
                    cam,
                    result_writer,
                    rois,
                    reference_points,
                    TrackerClass,
                    tracker_kwargs,
                    hardware_connection,
                    StimulatorClass,
                    stimulator_kwargs,
                    time_offset=time_offset,
                )

        except EthoscopeException as e:
            if e.img is not None:
                cv2.imwrite(self._info["dbg_img"], e.img)

            # Check if this is a camera hardware issue that should not cause a permanent failure
            error_msg = str(e).lower()
            if (
                "camera hardware not available" in error_msg
                or "video tracking and recording are disabled" in error_msg
                or "picamera2 compatibility" in error_msg
                or "allocator" in error_msg
            ):
                logging.error(f"Camera initialization failed: {e}")
                self._info["status"] = "stopped"
                self._info["error"] = f"Camera initialization failed: {str(e)}"
                self._info["time"] = time.time()
                # Don't call stop() which would set error traceback - just clean exit
                return
            else:
                # This is an exception-based stop, so it's not graceful
                self.stop(traceback.format_exc())

        except Exception as e:
            # Check if this is a camera-related exception that should not cause permanent failure
            error_msg = str(e).lower()
            if (
                "allocator" in error_msg
                or "picamera" in error_msg
                or "camera" in error_msg
                and "hardware" in error_msg
            ):
                logging.error(f"Camera-related error during initialization: {e}")
                self._info["status"] = "stopped"
                self._info["error"] = f"Camera error: {str(e)}"
                self._info["time"] = time.time()
                # Don't call stop() which would set error traceback - just clean exit
                return
            else:
                # This is an exception-based stop, so it's not graceful
                self.stop(traceback.format_exc())

        finally:
            # Covers every way out of run(), including the graceful return taken when
            # ROI building fails, which never reaches stop().
            self._cancel_autostop()

            try:
                if cam is not None:
                    cam._close()

            except Exception:
                logging.warning("Could not close camera properly")
                pass
            try:
                if hardware_connection is not None:
                    hardware_connection.stop()
            except Exception:
                logging.warning("Could not close hardware connection properly")
                pass

    def _write_light_schedule(self):
        """Write light schedule config file for the light daemon.

        The schedule supports both wall-clock 24 h cycles and arbitrary
        T-cycles. For T-cycles the anchor (ZT0 unix timestamp) is sourced
        from the incubator at the node and passed through experimental_info
        — never computed on the device — so every device in the same
        incubator shares the same phase.
        """
        try:
            schedule_dir = os.path.dirname(self.LIGHT_SCHEDULE_FILE)
            os.makedirs(schedule_dir, exist_ok=True)

            exp_info = self._info.get("experimental_info", {})
            lights_on = exp_info.get("lights_on", "")
            lights_off = exp_info.get("lights_off", "")

            # Period: integer minutes, default 1440 (24h). Tolerate strings.
            period_raw = exp_info.get("light_period_minutes", 1440)
            try:
                period_minutes = (
                    int(period_raw) if period_raw not in (None, "") else 1440
                )
            except (TypeError, ValueError):
                period_minutes = 1440
            if period_minutes <= 0:
                period_minutes = 1440

            # Anchor: optional unix timestamp. Empty string / None / unparseable → None.
            anchor_raw = exp_info.get("light_cycle_anchor", "")
            try:
                anchor = float(anchor_raw) if anchor_raw not in (None, "") else None
            except (TypeError, ValueError):
                anchor = None

            # Fade timing + peak brightness. Defaults mirror the firmware so an
            # unconfigured ethoscope behaves like a binary on/off transition.
            def _coerce_int(raw, default, lo=None, hi=None):
                try:
                    v = int(raw) if raw not in (None, "") else default
                except (TypeError, ValueError):
                    return default
                if lo is not None and v < lo:
                    return lo
                if hi is not None and v > hi:
                    return hi
                return v

            fade_in_seconds = _coerce_int(exp_info.get("fade_in_seconds"), 1, lo=0)
            fade_out_seconds = _coerce_int(exp_info.get("fade_out_seconds"), 1, lo=0)
            max_light = _coerce_int(exp_info.get("max_light"), 100, lo=0, hi=100)
            # crepuscular: any truthy value → 1; defaults to legacy hard-transition behaviour.
            crepuscular = bool(_coerce_int(exp_info.get("crepuscular"), 0))

            schedule = {
                "lights_on": lights_on,
                "lights_off": lights_off,
                "active": bool(lights_on and lights_off),
                "period_minutes": period_minutes,
                "anchor": anchor,
                "fade_in_seconds": fade_in_seconds,
                "fade_out_seconds": fade_out_seconds,
                "max_light": max_light,
                "crepuscular": crepuscular,
                "updated_at": time.time(),
            }

            # Atomic write: write to temp file then rename
            tmp_file = self.LIGHT_SCHEDULE_FILE + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(schedule, f)
            os.replace(tmp_file, self.LIGHT_SCHEDULE_FILE)

            if lights_on and lights_off:
                period_str = (
                    "" if period_minutes == 1440 else f", T={period_minutes // 60}h"
                )
                logging.info(
                    "Light schedule written: on=%s, off=%s%s",
                    lights_on,
                    lights_off,
                    period_str,
                )
            else:
                logging.info("No light schedule configured for this experiment")
        except Exception as e:
            logging.warning("Failed to write light schedule: %s", e)

    def _force_lights_on_for_targets(self):
        """Force the LED on during target detection on light-equipped ethoscopes.

        Talks to the light daemon over its Unix socket. Best-effort: any failure
        (no light hardware, daemon down, permission issue) is logged and
        swallowed so it never blocks tracking start.
        """
        try:
            from ethoscope.hardware.interfaces.light_daemon import (
                LightDaemonClient,
                LightDaemonUnavailable,
            )
            from ethoscope.utils.pi import has_light_hardware
        except ImportError as e:
            logging.debug("Light daemon client unavailable: %s", e)
            return

        try:
            if not has_light_hardware():
                return
        except Exception as e:
            logging.debug("has_light_hardware() check failed: %s", e)
            return

        try:
            LightDaemonClient().force_on()
            logging.info("Light forced ON for target detection phase")
        except LightDaemonUnavailable as e:
            logging.warning("Could not force lights on for target detection: %s", e)

    def _release_lights_after_targets(self):
        """Drop any forced-on state so the light schedule resumes."""
        try:
            from ethoscope.hardware.interfaces.light_daemon import (
                LightDaemonClient,
                LightDaemonUnavailable,
            )
            from ethoscope.utils.pi import has_light_hardware
        except ImportError:
            return

        try:
            if not has_light_hardware():
                return
        except Exception:
            return

        try:
            LightDaemonClient().release()
        except LightDaemonUnavailable as e:
            logging.warning(
                "Could not release light force after target detection: %s", e
            )

    def _clear_light_schedule(self):
        """Clear the light schedule config file so daemon turns lights off."""
        try:
            schedule_dir = os.path.dirname(self.LIGHT_SCHEDULE_FILE)
            os.makedirs(schedule_dir, exist_ok=True)

            schedule = {
                "lights_on": "",
                "lights_off": "",
                "active": False,
                "fade_in_seconds": 1,
                "fade_out_seconds": 1,
                "max_light": 100,
                "crepuscular": False,
                "updated_at": time.time(),
            }

            tmp_file = self.LIGHT_SCHEDULE_FILE + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(schedule, f)
            os.replace(tmp_file, self.LIGHT_SCHEDULE_FILE)
            logging.info("Light schedule cleared")
        except Exception as e:
            logging.warning("Failed to clear light schedule: %s", e)

    def stop(self, error=None):
        """ """
        # We stop only if we are actually running - not when the thread simply dies
        if self.info["status"] in ["running", "starting", "initialising"]:

            self._info["status"] = "stopping"
            self._info["time"] = time.time()

            self._cancel_autostop()

            # Clear light schedule so the daemon turns off the LED
            self._clear_light_schedule()

            # we reset all the user data of the latest experiment except the run_id
            # a new run_id will be created when we start another experiment
            if (
                "experimental_info" in self._info
                and "run_id" in self._info["experimental_info"]
            ):
                self._info["experimental_info"] = {
                    "run_id": self._info["experimental_info"]["run_id"]
                }

            if self._monit is not None:
                self._monit.stop()
                self._monit = None

                if self._auto_SQL_backup_at_stop:
                    logging.info("Performing a SQL dump of the database.")
                    t = Thread(target=pi.SQL_dump)
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
                    if error:
                        stop_reason = "error"
                    elif self._autostop_fired:
                        stop_reason = "autostop"
                    else:
                        stop_reason = "user_stop"

                    self._metadata_cache.finalize_cache(
                        self._tracking_start_time,
                        graceful=is_graceful,
                        stop_reason=stop_reason,
                    )
                    logging.info(
                        f"Finalized database cache file for tracking session (graceful={is_graceful}, reason={stop_reason})"
                    )
                except Exception as e:
                    logging.warning(f"Failed to finalize cache file: {e}")

            # Update database info after stopping
            if self._metadata_cache is not None:
                try:
                    self._info["database_info"] = (
                        self._metadata_cache.get_database_info()
                    )
                except Exception as e:
                    logging.warning(
                        f"Failed to get database info from metadata cache after stopping: {e}"
                    )
                    self._info["database_info"] = {
                        "db_size_bytes": 0,
                        "table_counts": {},
                        "last_db_update": 0,
                        "db_status": "error",
                    }
            else:
                self._info["database_info"] = {
                    "db_size_bytes": 0,
                    "table_counts": {},
                    "last_db_update": 0,
                    "db_status": "no_cache",
                }

            if "backup_filename" in self._info:
                # Initialize experimental_info structure if not exists
                if "experimental_info" not in self._info:
                    self._info["experimental_info"] = {"current": {}, "previous": {}}
                elif (
                    not isinstance(self._info["experimental_info"], dict)
                    or "previous" not in self._info["experimental_info"]
                ):
                    # Handle legacy format - preserve existing experimental_info as current
                    existing_info = (
                        self._info["experimental_info"]
                        if isinstance(self._info["experimental_info"], dict)
                        else {}
                    )
                    self._info["experimental_info"] = {
                        "current": existing_info,
                        "previous": {},
                    }

                # Store previous experiment information in nested structure
                self._info["experimental_info"]["previous"].update(
                    {
                        "date_time": self._info["time"],
                        "backup_filename": self._info["backup_filename"],
                        "user": self._info["experimental_info"]
                        .get("current", {})
                        .get("name", "")
                        or self._info["experimental_info"].get("name", ""),
                        "location": self._info["experimental_info"]
                        .get("current", {})
                        .get("location", "")
                        or self._info["experimental_info"].get("location", ""),
                    }
                )

            if error is not None:
                logging.error("Monitor closed with an error:")
                logging.error(error)
            else:
                logging.info("Monitor closed all right")

    def __del__(self):
        """ """

        self.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)
