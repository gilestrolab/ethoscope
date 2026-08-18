"""
Unit tests for the recording-complete marker written by the device on recording stop.

Covers the standalone ``write_recording_marker`` helper (atomic, valid JSON) and that
``ControlThreadVideoRecording.stop()`` drops a ``recording.info`` marker into the session
folder when a recording actually took place.
"""

import json
import os

import pytest

try:
    from ethoscope.control.record import (
        RECORDING_MARKER_FILENAME,
        ControlThreadVideoRecording,
        write_recording_marker,
    )
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.control.record import (
        RECORDING_MARKER_FILENAME,
        ControlThreadVideoRecording,
        write_recording_marker,
    )


class TestWriteRecordingMarker:
    def test_writes_valid_json(self, tmp_path):
        session_dir = str(tmp_path)
        info = {"status": "completed", "fps": 15, "resolution": "1920x1088"}
        path = write_recording_marker(session_dir, info)

        assert path == os.path.join(session_dir, RECORDING_MARKER_FILENAME)
        with open(path) as fh:
            assert json.load(fh) == info

    def test_atomic_no_tmp_leftover(self, tmp_path):
        write_recording_marker(str(tmp_path), {"status": "completed"})
        leftovers = [p for p in os.listdir(tmp_path) if p.endswith(".tmp")]
        assert leftovers == []


class TestStopWritesMarker:
    def _make_thread(self, session_dir):
        """Build a ControlThreadVideoRecording without running __init__ (no hardware)."""
        thread = ControlThreadVideoRecording.__new__(ControlThreadVideoRecording)
        thread._recorder = None
        thread._machine_id = "MACHINE123"
        thread._device_name = "ETHOSCOPE_TEST"
        thread._recording_start_time = 1000.0
        thread._recording_fps = 15
        thread._recording_resolution = "1920x1088"
        thread._output_video_full_prefix = os.path.join(session_dir, "prefix")
        thread._info = {"status": "stopped", "time": 0, "error": None}
        # stop() clears the light schedule; stub it out for the unit test.
        thread._clear_light_schedule = lambda: None
        return thread

    def test_clean_stop_writes_completed_marker(self, tmp_path):
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)
        thread = self._make_thread(session_dir)

        thread.stop()

        marker = os.path.join(session_dir, RECORDING_MARKER_FILENAME)
        assert os.path.exists(marker)
        with open(marker) as fh:
            data = json.load(fh)
        assert data["status"] == "completed"
        assert data["fps"] == 15
        assert data["resolution"] == "1920x1088"
        assert data["machine_id"] == "MACHINE123"
        assert data["error"] is None
        assert data["stop_reason"] == "user_stop"

    def test_error_stop_writes_error_marker(self, tmp_path):
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)
        thread = self._make_thread(session_dir)

        thread.stop(error="boom traceback")

        with open(os.path.join(session_dir, RECORDING_MARKER_FILENAME)) as fh:
            data = json.load(fh)
        assert data["status"] == "error"
        assert data["error"] == "boom traceback"
        assert data["stop_reason"] == "error"

    def test_autostop_marker_records_why_it_stopped(self, tmp_path):
        # A recording that ran its scheduled length is a clean completion, but the
        # marker has to say it ended on the timer rather than by hand.
        session_dir = str(tmp_path / "session")
        os.makedirs(session_dir)
        thread = self._make_thread(session_dir)
        thread._autostop_fired = True

        thread.stop()

        with open(os.path.join(session_dir, RECORDING_MARKER_FILENAME)) as fh:
            data = json.load(fh)
        assert data["status"] == "completed"
        assert data["stop_reason"] == "autostop"

    def test_no_session_dir_writes_no_marker(self, tmp_path):
        # Simulates streaming / early failure: prefix points at a dir that was never created.
        thread = self._make_thread(str(tmp_path / "never_created"))
        thread.stop()
        assert not os.path.exists(
            tmp_path / "never_created" / RECORDING_MARKER_FILENAME
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
