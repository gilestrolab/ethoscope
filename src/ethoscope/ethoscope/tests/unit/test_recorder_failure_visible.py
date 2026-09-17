"""
A recording or a stream that dies must say so.

``ControlThreadVideoRecording.run()`` sets the status to "recording"/"streaming"
and returns as soon as it has handed the camera to the capture thread. Nothing
revisited that status afterwards, so a capture thread that raised left the device
reporting itself busy with ``error: None`` for ever — the node believed it and
offered a live stream that never carried a frame, and the only trace was a
traceback in the listener's journal.
"""

import os
import socket
import tempfile
import threading
import time

import numpy as np
import pytest

try:
    from ethoscope.control import record as record_module
    from ethoscope.control.record import (
        GeneralVideoRecorder,
        Streamer,
        cameraCaptureThread,
    )
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.control import record as record_module
    from ethoscope.control.record import (
        GeneralVideoRecorder,
        Streamer,
        cameraCaptureThread,
    )


class FakeCamera:
    """A camera that yields grey frames, and optionally fails after a few."""

    isPiCamera = False
    width, height = 960, 720

    fail_after = None  # set by the test

    def __init__(self, *args, **kwargs):
        self.fps = 15.0
        self.closed = False

    def __iter__(self):
        i = 0
        while True:
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("the camera stopped delivering frames")
            yield i, np.full((720, 960), 128, dtype="uint8")
            i += 1
            time.sleep(0.005)

    def _close(self):
        self.closed = True


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def stream_port(monkeypatch):
    """Point the streamer at an ephemeral port instead of the fixed 8887."""
    port = _free_port()
    monkeypatch.setattr(record_module, "STREAMING_PORT", port)
    return port


def _make_streamer():
    return Streamer(FakeCamera, {}, video_prefix="", img_path="")


class TestCaptureThreadRecordsItsFailure:
    """The thread keeps the traceback where the status poll can find it."""

    def test_a_failing_capture_thread_records_the_traceback(self, stream_port):
        """A camera that stops mid-stream leaves the reason on the thread."""
        camera = type("FailingCamera", (FakeCamera,), {"fail_after": 3})
        recorder = GeneralVideoRecorder(
            camera, {}, img_path="", video_prefix="", stream=True, record_video=False
        )
        recorder.start_recording()
        recorder._p.join(timeout=10)

        assert not recorder.is_alive()
        assert recorder.error is not None
        assert "stopped delivering frames" in recorder.error

    def test_a_port_already_taken_is_reported_not_swallowed(self, stream_port):
        """The failure that started this: 8887 held by a previous, leaked stream."""
        squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        squatter.bind(("", stream_port))
        squatter.listen(1)
        try:
            recorder = _make_streamer()
            recorder.start_recording()
            recorder._p.join(timeout=10)

            assert not recorder.is_alive()
            assert "Address already in use" in recorder.error
        finally:
            squatter.close()

    def test_a_clean_stop_leaves_no_error(self, stream_port):
        """Stopping on request is not a failure and must not be reported as one."""
        recorder = _make_streamer()
        recorder.start_recording()
        time.sleep(0.2)
        recorder.stop()

        assert not recorder.is_alive()
        assert recorder.error is None

    def test_a_failed_run_frees_the_streaming_port(self, stream_port):
        """Teardown runs on the failure path too, so the next start is not poisoned.

        A stream server left bound is what turned one failure into every later
        start failing as well, for an unrelated-looking reason.
        """
        camera = type("FailingCamera", (FakeCamera,), {"fail_after": 2})
        recorder = GeneralVideoRecorder(
            camera, {}, img_path="", video_prefix="", stream=True, record_video=False
        )
        recorder.start_recording()
        recorder._p.join(timeout=10)
        assert recorder.error is not None

        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("", stream_port))  # must not raise
        finally:
            probe.close()

    def test_the_camera_is_released_on_failure(self, stream_port):
        """The camera is handed back even when acquisition ends on an exception."""
        camera = type("FailingCamera", (FakeCamera,), {"fail_after": 1})
        recorder = GeneralVideoRecorder(
            camera, {}, img_path="", video_prefix="", stream=True, record_video=False
        )
        recorder.start_recording()
        recorder._p.join(timeout=10)

        assert recorder._p.camera.closed is True


class _StubRecorder:
    """Stands in for GeneralVideoRecorder in the control-thread tests."""

    def __init__(self, alive, error=None):
        self._alive = alive
        self.error = error
        self.stopped = False

    def is_alive(self):
        return self._alive

    def stop(self):
        self.stopped = True


def _make_control_thread(recorder, capture_started, status="streaming"):
    """A ControlThreadVideoRecording with only the fields _recorder_died() reads."""
    control = record_module.ControlThreadVideoRecording.__new__(
        record_module.ControlThreadVideoRecording
    )
    control._recorder = recorder
    control._capture_started = capture_started
    control._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_test_")
    control._info = {"status": status, "error": None}
    control.stopped_with = None

    def fake_stop(error=None):
        control.stopped_with = error
        control._info["status"] = "stopped"
        control._info["error"] = error

    control.stop = fake_stop
    return control


class TestControlThreadNoticesTheDeath:
    """The status poll turns a dead capture thread into a reported error."""

    def test_a_dead_thread_stops_the_device_and_names_the_reason(self):
        recorder = _StubRecorder(alive=False, error="Traceback: boom")
        control = _make_control_thread(recorder, capture_started=True)

        assert control._recorder_died() is True
        assert control.stopped_with == "Traceback: boom"
        assert control._info["status"] == "stopped"

    def test_a_thread_that_exited_without_a_traceback_still_reports(self):
        """Not every death leaves an exception; the device must not stay 'streaming'."""
        recorder = _StubRecorder(alive=False, error=None)
        control = _make_control_thread(recorder, capture_started=True)

        assert control._recorder_died() is True
        assert "streaming" in control.stopped_with
        assert control._info["status"] == "stopped"

    def test_a_live_thread_is_left_alone(self):
        recorder = _StubRecorder(alive=True)
        control = _make_control_thread(recorder, capture_started=True)

        assert control._recorder_died() is False
        assert control.stopped_with is None
        assert control._info["status"] == "streaming"

    def test_a_poll_before_the_thread_starts_is_not_a_death(self):
        """run() sets the status before start_recording(); a poll in between must
        not read a not-yet-started thread as a dead one."""
        recorder = _StubRecorder(alive=False)
        control = _make_control_thread(recorder, capture_started=False)

        assert control._recorder_died() is False
        assert control.stopped_with is None

    def test_stop_disarms_the_check(self):
        """stop() clears the flag first, so a poll during its 10 s join cannot
        mistake the thread it is joining for one that died."""
        control = record_module.ControlThreadVideoRecording.__new__(
            record_module.ControlThreadVideoRecording
        )
        control._capture_started = True
        control._tmp_dir = tempfile.mkdtemp(prefix="ethoscope_test_")

        # The flag is cleared before anything else in stop(); assert on the real
        # method by driving it with the minimum state it touches.
        control._info = {"status": "streaming", "error": None}
        control._recorder = None
        control._autostop_fired = False
        control._cancel_autostop = lambda: None
        control._clear_light_schedule = lambda: None
        record_module.ControlThreadVideoRecording.stop(control)

        assert control._capture_started is False
        assert control._info["status"] == "stopped"


class TestStreamServerStillWorks:
    """The refactor must not have changed what a healthy stream does."""

    def test_a_healthy_stream_serves_mjpeg(self, stream_port):
        recorder = _make_streamer()
        recorder.start_recording()
        try:
            deadline = time.time() + 10
            data = b""
            while time.time() < deadline and b"--frame" not in data:
                try:
                    with socket.create_connection(
                        ("127.0.0.1", stream_port), timeout=2
                    ) as client:
                        client.sendall(b"GET / HTTP/1.0\r\n\r\n")
                        client.settimeout(5)
                        while len(data) < 4096:
                            chunk = client.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                except OSError:
                    time.sleep(0.2)

            assert b"multipart/x-mixed-replace" in data
            assert b"--frame" in data
            assert recorder.error is None
            assert recorder.is_alive()
        finally:
            recorder.stop()


def test_no_thread_leaks():
    """The capture threads above must not still be running at teardown."""
    leaked = [t for t in threading.enumerate() if "cameraCaptureThread" in repr(t)]
    assert leaked == []
