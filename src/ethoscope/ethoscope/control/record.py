import datetime
import json
import logging
import os
import queue

# streaming socket
import socket
import tempfile
import threading
import time
import traceback
from collections import OrderedDict

# from cv2 import VideoWriter, VideoWriter_fourcc, imwrite
import cv2

from ethoscope.control.tracking import ControlThread, ExperimentalInformation
from ethoscope.hardware.input.cameras import OurPiCameraAsync, V4L2Camera
from ethoscope.utils.debug import EthoscopeException
from ethoscope.utils.description import DescribedObject
from ethoscope.utils.scheduler import (  # noqa: F401
    TimedStop,
    TimedStopError,
    timedStop,  # resolved by name from configurations saved by earlier versions
)

STREAMING_PORT = 8887

# Boundary token used to delimit JPEG frames in the multipart/x-mixed-replace stream.
# Consumers (browsers, OpenCV/Bonsai, the node proxy) split the byte stream on it.
STREAM_BOUNDARY = b"frame"

# HTTP/1.0 response sent once per client before the multipart body starts. Using a standard
# MJPEG response means any HTTP client (browser <img>, OpenCV VideoCapture, the node proxy)
# can consume the stream directly with no Python-specific decoding.
STREAM_HTTP_HEADER = (
    b"HTTP/1.0 200 OK\r\n"
    b"Connection: close\r\n"
    b"Cache-Control: no-cache, private\r\n"
    b"Pragma: no-cache\r\n"
    b"Content-Type: multipart/x-mixed-replace; boundary=" + STREAM_BOUNDARY + b"\r\n"
    b"\r\n"
)

# Name of the marker file dropped into a video session folder when a recording terminates.
# Its presence tells downstream tools (e.g. the node's h264_to_mp4 converter) that the .h264
# chunks in that folder are final and safe to merge into an mp4.
RECORDING_MARKER_FILENAME = "recording.info"


def write_recording_marker(session_dir, info_dict):
    """
    Atomically write the recording-complete marker file into a video session folder.

    Args:
        session_dir (str): Directory holding the .h264 chunks of one recording session.
        info_dict (dict): JSON-serialisable metadata (status, timestamps, fps, resolution...).

    Returns:
        str: Full path of the marker file written.
    """
    marker_path = os.path.join(session_dir, RECORDING_MARKER_FILENAME)
    tmp_path = marker_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(info_dict, f, indent=2)
    # Reason: os.replace is atomic on POSIX, so a reader (or rsync) never sees a half-written marker
    os.replace(tmp_path, marker_path)
    return marker_path


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

    # Frames acquired before the local (non-Pi) video writer is opened, so that
    # the measured camera FPS it is built with has had time to settle.
    _FRAMES_BEFORE_RECORDING = 150

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

        # Streaming server state (only used when self._stream is True).
        # One shared TCP server fans the same encoded frame out to every connected client
        # via a per-client bounded queue, so a slow client drops frames instead of stalling
        # the camera loop, and the JPEG is only ever encoded once per frame.
        self._stream_server_socket = None
        self._stream_clients = []  # list of (client_socket, queue.Queue)
        self._stream_lock = threading.Lock()

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
        video_filename = (
            f"{self._video_prefix}_{video_info}_{self.video_file_index:05d}.{ext}"
        )
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
            self._start_stream_server()

        while not self.stop_camera_activity:

            # processing images one by one
            for ix, (_, frame) in enumerate(self.camera):

                if self.stop_camera_activity:
                    break

                if self._local_recording:
                    # cv2.VideoWriter is fixed at construction to one frame rate and
                    # cannot be retimed afterwards, so the first frames are spent
                    # letting self.camera.fps settle into a usable estimate. The
                    # writer is then opened once and rotated only when a chunk is
                    # full. Reason: the construction used to sit outside this test,
                    # so a new writer was built for every single frame - each file
                    # got at most one frame, none of them were ever released, and
                    # the chunk index climbed with the frame counter.
                    chunk_full = (
                        writer is not None
                        and time.time() - self.start_time >= self._VIDEO_CHUNCK_DURATION
                    )

                    if (
                        writer is None and ix >= self._FRAMES_BEFORE_RECORDING
                    ) or chunk_full:
                        if writer is not None:
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

                    if writer is not None and writer.isOpened():
                        writer.write(frame)

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
                    ok, jpg = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90]
                    )

                    # Encode once, then fan the same MJPEG part out to every client.
                    if ok:
                        jpg_bytes = jpg.tobytes()
                        chunk = (
                            b"--" + STREAM_BOUNDARY + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: "
                            + str(len(jpg_bytes)).encode()
                            + b"\r\n\r\n"
                            + jpg_bytes
                            + b"\r\n"
                        )
                        self._broadcast_stream_frame(chunk)

                # AFTER writing, annotates the frame for preview but only once every 5 seconds
                if not self._stream and ((time.time() - self.preview_time) > 5):
                    writing_status = (
                        "CV2 Writing" if writer is not None else "PI Recording"
                    )
                    self._save_preview_frame(frame, writing_status)

        # out of the loop - exit signal received
        self.camera._close()

        if self._stream:
            self._stop_stream_server()

        if writer:
            writer.release()

    def _start_stream_server(self):
        """Open the MJPEG TCP server and start accepting clients in the background."""
        self._stream_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._stream_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stream_server_socket.bind(("", STREAMING_PORT))
        self._stream_server_socket.listen(5)
        threading.Thread(target=self._accept_stream_clients, daemon=True).start()
        logging.info("MJPEG stream server initialised on port %d.", STREAMING_PORT)

    def _accept_stream_clients(self):
        """Accept incoming HTTP clients and hand each one its own writer thread."""
        while not self.stop_camera_activity:
            try:
                client_socket, _ = self._stream_server_socket.accept()
            except OSError:
                break  # server socket has been closed during shutdown

            try:
                # Consume the HTTP request line/headers (best effort) so the client
                # socket is drained, then send the multipart response header.
                client_socket.settimeout(2)
                try:
                    client_socket.recv(4096)
                except OSError:
                    pass
                client_socket.settimeout(None)
                client_socket.sendall(STREAM_HTTP_HEADER)
            except OSError:
                try:
                    client_socket.close()
                except OSError:
                    pass
                continue

            client_queue = queue.Queue(maxsize=10)
            with self._stream_lock:
                self._stream_clients.append((client_socket, client_queue))
            threading.Thread(
                target=self._serve_stream_client,
                args=(client_socket, client_queue),
                daemon=True,
            ).start()
            logging.info("Streaming client connected.")

    def _serve_stream_client(self, client_socket, client_queue):
        """Drain one client's queue to its socket; drop the client on any write error."""
        try:
            while not self.stop_camera_activity:
                try:
                    chunk = client_queue.get(timeout=5)
                except queue.Empty:
                    continue
                if chunk is None:  # shutdown sentinel
                    break
                client_socket.sendall(chunk)
        except OSError:
            pass  # client went away
        finally:
            with self._stream_lock:
                self._stream_clients = [
                    (s, q) for (s, q) in self._stream_clients if s is not client_socket
                ]
            try:
                client_socket.close()
            except OSError:
                pass
            logging.info("Streaming client disconnected.")

    def _broadcast_stream_frame(self, chunk):
        """Queue one already-encoded MJPEG part for every connected client."""
        with self._stream_lock:
            clients = list(self._stream_clients)
        for _, client_queue in clients:
            try:
                client_queue.put_nowait(chunk)
            except queue.Full:
                pass  # slow client: drop this frame rather than stall the camera loop

    def _stop_stream_server(self):
        """Signal all client writers to stop and close the server socket."""
        with self._stream_lock:
            clients = list(self._stream_clients)
        for _, client_queue in clients:
            try:
                client_queue.put_nowait(None)
            except queue.Full:
                pass
        if self._stream_server_socket is not None:
            try:
                self._stream_server_socket.close()
            except OSError:
                pass
            self._stream_server_socket = None


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
            record_video=record_video,
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
                    "possible_classes": [TimedStop],
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
            "autostop_at": None,
        }

        self._init_autostop_state()
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

            # Armed before the camera is opened, so a malformed stop time is reported
            # without first spinning up a recording that is about to be torn down.
            try:
                self._arm_autostop(self._info["time"])
            except TimedStopError as e:
                # A stop time the user typed wrong, or one that has already passed.
                # Report it plainly and leave the device free to be started again,
                # rather than burying a readable message in a traceback.
                logging.error(f"Refusing to start: {e}")
                self._info["status"] = "stopped"
                self._info["error"] = str(e)
                return

            # Write light schedule config for the light daemon service
            self._write_light_schedule()

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

            # Stash metadata needed for the recording-complete marker written in stop().
            # Presets (HD/Standard) pass empty recorder_kwargs, so read the resolved values
            # from the underlying capture thread rather than from recorder_kwargs.
            self._recording_start_time = self._info["time"]
            self._recording_fps = recorder_kwargs.get("fps")
            self._recording_resolution = None
            try:
                capture_thread = self._recorder._p
                self._recording_fps = capture_thread._fps
                width, height = capture_thread._resolution
                self._recording_resolution = f"{width}x{height}"
            except AttributeError:
                # Streamer (and any non-recording recorder) has no capture thread; that's fine,
                # stop() only writes a marker when an actual recording folder exists.
                pass

            self._recorder.start_recording()

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

        self._cancel_autostop()

        # Clear light schedule so the daemon turns off the LED
        self._clear_light_schedule()

        self._info["experimental_info"] = {}

        if self._recorder is not None:
            logging.info("Control thread asking recorder to stop")
            self._recorder.stop()
            self._recorder = None

        self._info["status"] = "stopped"
        self._info["time"] = time.time()
        self._info["error"] = error

        # Drop a marker into the session folder so downstream conversion knows the .h264
        # chunks are final. Written after the recorder has fully stopped (all chunks flushed).
        # Guarded so it can never break shutdown; the isdir() check naturally skips streaming,
        # which does not create a recording folder.
        try:
            session_dir = os.path.dirname(
                getattr(self, "_output_video_full_prefix", "")
            )
            if session_dir and os.path.isdir(session_dir):
                write_recording_marker(
                    session_dir,
                    {
                        "status": "error" if error is not None else "completed",
                        "stop_reason": (
                            "error"
                            if error is not None
                            else ("autostop" if self._autostop_fired else "user_stop")
                        ),
                        "start_time": getattr(self, "_recording_start_time", None),
                        "stop_time": self._info["time"],
                        "fps": getattr(self, "_recording_fps", None),
                        "resolution": getattr(self, "_recording_resolution", None),
                        "machine_id": self._machine_id,
                        "device_name": self._device_name,
                        "error": error,
                    },
                )
        except Exception as e:
            logging.warning(f"Could not write recording marker file: {e}")

        if error is not None:
            logging.error("Recorder closed with an error:")
            logging.error(error)
        else:
            logging.info("Recorder closed all right")
