import datetime
import logging
import os
import pickle

# streaming socket
import socket
import struct
import tempfile
import threading
import time
import traceback
from collections import OrderedDict

# from cv2 import VideoWriter, VideoWriter_fourcc, imwrite
import cv2

from ethoscope.control.tracking import ControlThread
from ethoscope.control.tracking import ExperimentalInformation
from ethoscope.hardware.input.cameras import OurPiCameraAsync
from ethoscope.hardware.input.cameras import V4L2Camera
from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.description import DescribedObject

STREAMING_PORT = 8887


class cameraCaptureThread(threading.Thread):
    """
    This opens a camera process for recording or streaming video - this is not used during tracking
    The camera could be the one from the PI or v4L2

    In the former case, recording best left to the camera class itself because it's the only way to get good FPSs
    Otherwise one can use V4L2 recording and record images coming from the camera queue, but this is slow (1-8FPS depending on resolution)
    For recording, files are saved in chunks of time duration

    In principle, streaming and recording could be done simultaneously ( see https://picamera.readthedocs.io/en/release-1.12/recipes2.html#capturing-images-whilst-recording )
    but for now they are handled independently
    """

    _VIDEO_CHUNCK_DURATION = 30 * 10

    def __init__(
        self,
        cameraClass,
        camera_kwargs,
        img_path,
        video_prefix,
        width,
        height,
        fps,
        bitrate,
        quality,
        stream=False,
        record_video=False,
    ):

        self._img_path = img_path
        self._stream = stream

        self._resolution = (width, height)
        self._fps = fps
        self._bitrate = bitrate
        self.stop_camera_activity = False

        self._video_prefix = video_prefix
        self._record_video = video_prefix is not None and record_video
        if self._record_video:
            self._create_recording_folder()
        logging.info(f"video_prefix_basethread: {video_prefix}")

        try:
            self.camera = cameraClass(
                target_fps=fps,
                target_resolution=(width, height),
                video_prefix=video_prefix,
                record_video=self._record_video,
                quality=quality,
                **camera_kwargs,
            )
        except EthoscopeException as e:
            if "Camera hardware not available" in str(e):
                raise EthoscopeException(
                    "Recording disabled: No camera hardware available."
                ) from e
            else:
                raise e

        # piCamera will record video autonomously without help from this class.
        # However if the user wants to record video with a non-pi camera, we need to fall back to recording here.
        self._local_recording = (
            self._record_video is True and self.camera.isPiCamera is False
        )

        self.video_file_index = 0

        super().__init__()

    def _get_video_chunk_filename(self, ext="h264"):
        """
        we save the files in chunks that will have to be merged togheter at a later point
        this names the next chunck
        """

        self.video_file_index += 1
        w, h = self._resolution
        video_info = f"{w}x{h}@{self.camera.fps}"  # uses effective FPS count, not the desired number
        video_filename = f"{self._video_prefix}_{video_info}_{self.video_file_index:05d}.{ext}"
        return video_filename

    def _create_recording_folder(self):
        """
        Creates a destination folder for the video, if it does not exist
        """
        try:
            video_dirname = os.path.dirname(self._video_prefix)
            if not os.path.exists(video_dirname):
                os.makedirs(video_dirname)
                logging.info(f"Created folder: {video_dirname}")

        except OSError as e:
            raise e

    def _save_preview_frame(self, frame, writing_status):
        """ """
        timestamp = (
            datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S")
            + " FPS: "
            + str(round(self.camera.fps, 2))
            + " "
            + writing_status
        )

        frame = cv2.resize(frame, (640, 480))
        cv2.putText(frame, timestamp, (20, 20), 1, 1, (255, 255, 255))
        self.preview_time = time.time()

        # save the annotated frame for preview
        cv2.imwrite(self._img_path, frame)

    def run(self):
        """
        Iterates the camera object for images and writes them the to a video file, dividing the video in multiple AVI
        Every 5 seconds, updates the preview frame served over the network by the webserver adding some info text on it
        """

        self.start_time = self.preview_time = time.time()
        writer = None

        if self._stream:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("", STREAMING_PORT))
            server_socket.listen(5)
            logging.info("Socket stream initiliased.")

        while not self.stop_camera_activity:

            # waiting for the streaming connection to be established
            if self._stream:
                logging.info("Waiting for a connection to start streaming")
                client_socket, client_address = server_socket.accept()  # blocking call
                logging.info("Connection established!")

            # processing images one by one
            for ix, (_, frame) in enumerate(self.camera):

                if self.stop_camera_activity:
                    break

                if self._local_recording:
                    if writer and writer.isOpened():
                        writer.write(frame)

                    # Wait for the first 150 frames before opening the video writer object - this is done to calcualate a decent approximation of actual FPS
                    if (
                        (time.time() - self.start_time >= self._VIDEO_CHUNCK_DURATION)
                        or ix == 150
                        and writer
                    ):
                        writer.release()

                    writer = cv2.VideoWriter(
                        self._get_video_chunk_filename(ext="h264"),
                        cv2.VideoWriter_fourcc(*"H264"),
                        self.camera.fps,
                        (self.camera.width, self.camera.height),
                    )
                    if not writer.isOpened():
                        logging.error(
                            "Error: failed to open Video writer destination. The Video file cannot be saved."
                        )

                    self.start_time = time.time()

                if self._stream:

                    # annotate frame for streaming
                    frame = cv2.resize(frame, (640, 480))
                    frame = cv2.putText(
                        frame,
                        "FPS: " + str(round(self.camera.fps, 2)),
                        (20, 20),
                        1,
                        1,
                        (255, 255, 255),
                    )
                    _, frame = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                    )

                    # send it to stream
                    data = pickle.dumps(frame)
                    message = struct.pack("Q", len(data)) + data
                    client_socket.sendall(message)

                # AFTER writing, annotates the frame for preview but only once every 5 seconds
                if not self._stream and ((time.time() - self.preview_time) > 5):
                    writing_status = (
                        "CV2 Writing" if writer is not None else "PI Recording"
                    )
                    self._save_preview_frame(frame, writing_status)

        # out of the loop - exit signal received
        self.camera._close()

        if self._stream:
            client_socket.close()
            server_socket.close()

        if writer:
            writer.release()


class GeneralVideoRecorder(DescribedObject):

    _description = {
        "overview": "A video simple recorder. When using the default camera PI, frames should be multiple of 16 in X and 32 in Y.",
        "arguments": [
            {
                "type": "number",
                "name": "width",
                "description": "The width of the frame",
                "default": 1280,
                "min": 480,
                "max": 1980,
                "step": 1,
            },
            {
                "type": "number",
                "name": "height",
                "description": "The height of the frame",
                "default": 960,
                "min": 360,
                "max": 1088,
                "step": 1,
            },
            {
                "type": "number",
                "name": "fps",
                "description": "The target number of frames per seconds",
                "default": 15,
                "min": 1,
                "max": 25,
                "step": 1,
            },
            {
                "type": "number",
                "name": "bitrate",
                "description": "The target bitrate",
                "default": 200000,
                "min": 0,
                "max": 10000000,
                "step": 1000,
            },
            {
                "type": "number",
                "name": "quality",
                "description": "10 is extremely high quality, 40 is extremely low",
                "default": 20,
                "min": 10,
                "max": 40,
                "step": 1,
            },
        ],
    }
    status = "recording"  # this is the default status. The alternative is streaming

    def __init__(
        self,
        cameraClass,
        camera_kwargs,
        img_path,
        video_prefix,
        width=1280,
        height=960,
        fps=15,
        bitrate=200000,
        quality=20,
        stream=False,
        record_video=True,
    ):

        self._stream = stream

        # This used to be a process but it's best handled as a thread. See also commit https://github.com/gilestrolab/ethoscope/commit/c2e8a7f656611cc10379c8e93ff4205220c8807a
        self._p = cameraCaptureThread(
            cameraClass,
            camera_kwargs,
            img_path,
            video_prefix,
            width,
            height,
            fps,
            bitrate,
            quality,
            stream,
        )

    def start_recording(self):
        """ """
        self._p.start()

    def stop(self):
        """
        Stops the camera capture thread and closes any necessary resources.
        """
        logging.info("Stopping camera recording.")
        self._p.stop_camera_activity = True

        if self._stream:
            try:
                self._p.connection.close()
            except Exception:
                pass

        self._p.join(10)


# When using the default camera PI, frames should be multiple of 16 in X and 32 in Y


class HDVideoRecorder(GeneralVideoRecorder):
    _description = {
        "overview": "A preset 1920 x 1088, 15fps, bitrate = 5e5 video recorder. "
        "At this resolution, the field of view is only partial, "
        "so we effectively zoom in the middle of arenas",
        "arguments": [],
    }
    status = "recording"

    def __init__(self, cameraClass, camera_kwargs, video_prefix, img_path):
        super().__init__(
            cameraClass,
            camera_kwargs,
            img_path,
            video_prefix,
            width=1920,
            height=1088,
            quality=28,
            fps=15,
            bitrate=1000000,
        )


class StandardVideoRecorder(GeneralVideoRecorder):
    _description = {
        "overview": "A preset 1280 x 960, 15fps, bitrate = 2e5 video recorder.",
        "arguments": [],
    }
    status = "recording"

    def __init__(self, cameraClass, camera_kwargs, video_prefix, img_path):
        super().__init__(
            cameraClass,
            camera_kwargs,
            img_path,
            video_prefix,
            width=1280,
            height=960,
            fps=15,
            bitrate=500000,
        )


class Streamer(GeneralVideoRecorder):
    _description = {
        "overview": "A preset 960 x 720, 15fps, bitrate = 2e5 streamer. Active on port 8887.",
        "arguments": [],
        "hidden": True,
    }
    status = "streaming"

    def __init__(self, cameraClass, camera_kwargs, video_prefix, img_path):
        logging.info(f"video_prefix_streamer: {video_prefix}")
        super().__init__(
            cameraClass,
            camera_kwargs,
            img_path="",
            video_prefix="",
            width=960,
            height=720,
            fps=15,
            bitrate=500000,
            stream=True,
            record_video=False,
        )


class timedStop(DescribedObject):
    _description = {
        "overview": "Automatically stops the experiment at the given time.",
        "arguments": [
            {
                "type": "str",
                "name": "timer",
                "description": "Countdown timer to automatically stop the experiment. Days(DD):Hours(HH):Minutes(MM). ",
                "default": "00:00:00",
            },
        ],
    }

    def __init__(self, timer="00:00:00"):
        self.timer = timer
        self.countdown = self._convert_to_seconds(timer)
        self.autostop = self.countdown > 0

    def _convert_to_seconds(self, time_str):
        """
        Converts a time string from "DD:HH:MM" format into total seconds.

        Args:
        time_str (str): The time string in "DD:HH:MM" format.

        Returns:
        int: Total number of seconds.

        Raises:
        ValueError: If the format is incorrect or values are out of expected range.
        """
        # Split the string by ':' and check if it has exactly three parts
        parts = time_str.split(":")
        if len(parts) != 3:
            raise ValueError("Time format must be DD:HH:MM")

        try:
            # Parse days, hours, and minutes from the parts
            days, hours, minutes = int(parts[0]), int(parts[1]), int(parts[2])

            # Sanity checks for hours and minutes range
            if not (0 <= hours < 24):
                raise ValueError("Hours must be between 0 and 23")
            if not (0 <= minutes < 60):
                raise ValueError("Minutes must be between 0 and 59")

            # Convert all to seconds
            total_seconds = days * 86400 + hours * 3600 + minutes * 60
            return total_seconds

        except ValueError as e:
            raise ValueError(
                "Error in countdown format. Use DD:HH:MM (days, hours, minutes)"
            ) from e


class ControlThreadVideoRecording(ControlThread):

    _evanescent = False
    _option_dict = OrderedDict(
        [
            (
                "experimental_info",
                {
                    "possible_classes": [ExperimentalInformation],
                },
            ),
            (
                "recorder",
                {
                    "possible_classes": [
                        StandardVideoRecorder,
                        HDVideoRecorder,
                        GeneralVideoRecorder,
                        Streamer,
                    ],
                },
            ),
            (
                "time_control",
                {
                    "possible_classes": [timedStop],
                },
            ),
            (
                "camera",
                {
                    "possible_classes": [OurPiCameraAsync, V4L2Camera],
                },
            ),
        ]
    )

    for k in _option_dict:
        _option_dict[k]["class"] = _option_dict[k]["possible_classes"][0]
        _option_dict[k]["kwargs"] = {}

    _tmp_last_img_file = "last_img.jpg"
    _dbg_img_file = "dbg_img.png"
    _log_file = "ethoscope.log"

    _hidden_options = {"camera"}

    def __init__(
        self, machine_id, name, version, ethoscope_dir, data=None, *args, **kwargs
    ):

        # for FPS computation
        self._last_info_t_stamp = 0
        self._last_info_frame_idx = 0

        # Manage disk space before starting video recording
        try:
            from ethoscope.utils import pi

            space_result = pi.manage_disk_space(ethoscope_dir)
            if space_result.get("cleanup_performed", False):
                logging.info(
                    f"Disk space cleanup completed: {space_result.get('cleanup_summary', {}).get('files_deleted', 0)} files removed"
                )
        except Exception as e:
            logging.warning(f"Disk space management failed, continuing anyway: {e}")

        # Metadata
        self._recorder = None
        self._machine_id = machine_id
        self._device_name = name
        self._video_root_dir = ethoscope_dir
        self._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_")

        # todo add 'data' -> how monitor was started to metadata
        self._info = {
            "status": "stopped",
            "time": time.time(),
            "error": None,
            "log_file": os.path.join(ethoscope_dir, self._log_file),
            "dbg_img": os.path.join(ethoscope_dir, self._dbg_img_file),
            "last_drawn_img": os.path.join(self._tmp_dir, self._tmp_last_img_file),
            "id": machine_id,
            "name": name,
            "version": version,
            "experimental_info": {},
            "autostop": False,
        }

        self._parse_user_options(data)
        super(ControlThread, self).__init__()

    @property
    def controltype(self):
        return "recording"

    def _update_info(self):
        if self._recorder is None:
            return
        self._last_info_t_stamp = time.time()

    def _parse_one_user_option(self, field, data):

        try:
            subdata = data[field]
        except KeyError:
            logging.warning(f"No field {field}, using default")
            return None, {}

        Class = eval(subdata["name"])
        kwargs = subdata["arguments"]

        return Class, kwargs

    def run(self):

        try:
            self._info["status"] = "initialising"
            logging.info("Starting Monitor thread")
            self._info["error"] = None

            self._last_info_t_stamp = 0
            self._last_info_frame_idx = 0

            ExpInfoClass = self._option_dict["experimental_info"]["class"]
            exp_info_kwargs = self._option_dict["experimental_info"]["kwargs"]
            self._info["experimental_info"] = ExpInfoClass(**exp_info_kwargs).info_dic
            self._info["time"] = time.time()

            date_time = datetime.datetime.fromtimestamp(self._info["time"])
            formatted_time = date_time.strftime("%Y-%m-%d_%H-%M-%S")

            try:
                code = self._info["experimental_info"]["code"]
            except KeyError:
                code = "NA"
                logging.warning("No code field in experimental info")

            file_prefix = f"{formatted_time}_{self._machine_id}_{code}"
            self._output_video_full_prefix = os.path.join(
                self._video_root_dir,
                self._machine_id,
                self._device_name,
                formatted_time,
                file_prefix,
            )

            RecorderClass = self._option_dict["recorder"]["class"]
            recorder_kwargs = self._option_dict["recorder"][
                "kwargs"
            ]  # {'width': 1280, 'height': 960, 'fps': 25, 'bitrate': 200000, 'quality' : 20}

            cameraClass = self._option_dict["camera"]["class"]
            camera_kwargs = self._option_dict["camera"]["kwargs"]

            try:
                self._recorder = RecorderClass(
                    cameraClass,
                    camera_kwargs,
                    video_prefix=self._output_video_full_prefix,
                    img_path=self._info["last_drawn_img"],
                    **recorder_kwargs,
                )
            except EthoscopeException as e:
                if "Camera hardware not available" in str(e):
                    logging.error("Cannot start recording: No camera hardware detected")
                    raise EthoscopeException(
                        "Recording disabled: No camera hardware available. This ethoscope cannot perform video recording without camera hardware."
                    ) from e
                else:
                    raise e

            self._info["status"] = self._recorder.status  # "recording" or "streaming"
            logging.info(f"Started {self._recorder.status}")

            self._recorder.start_recording()

            # Setting up a timer to stop the recording
            self._timer = self._option_dict["time_control"]["class"](
                **self._option_dict["time_control"]["kwargs"]
            )
            if self._timer.autostop:
                timer = threading.Timer(self._timer.countdown, self.stop)
                timer.start()
                self._info["autostop"] = self._timer.timer

        except Exception:
            self.stop(traceback.format_exc())

        # for testing purposes
        if self._evanescent:
            self.stop()
            os._exit(0)

    def stop(self, error=None):
        """ """
        self._info["status"] = "stopping"
        self._info["time"] = time.time()
        self._info["experimental_info"] = {}

        if self._recorder is not None:
            logging.info("Control thread asking recorder to stop")
            self._recorder.stop()
            self._recorder = None

        self._info["status"] = "stopped"
        self._info["time"] = time.time()
        self._info["error"] = error

        if error is not None:
            logging.error("Recorder closed with an error:")
            logging.error(error)
        else:
            logging.info("Recorder closed all right")
