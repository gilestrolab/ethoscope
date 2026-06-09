"""
Unit tests for the node-side h264->mp4 conversion gating helpers.

These cover the readiness gate that prevents the daily cron from converting a recording while
it is still in progress, plus reading the recording FPS from the marker file. No ffmpeg/ffprobe
is exercised here - only the pure folder-inspection logic.
"""

import importlib.util
import json
import os
import time

import pytest

# accessories/h264_to_mp4.py is a standalone script (not an importable package), so load it
# directly from its path relative to this test file (repo root is four levels up).
_MODULE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "accessories", "h264_to_mp4.py"
)
_spec = importlib.util.spec_from_file_location("h264_to_mp4", _MODULE_PATH)
h264_to_mp4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h264_to_mp4)


def _make_chunk(folder, name="rec_00001.h264", age_hours=0):
    """Create a fake .h264 chunk in *folder*, optionally back-dating its mtime."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    open(path, "w").close()
    if age_hours:
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))
    return path


class TestFolderIsReady:
    def test_marker_present_is_ready(self, tmp_path):
        folder = str(tmp_path / "with_marker")
        _make_chunk(folder)
        json.dump(
            {"status": "completed"}, open(os.path.join(folder, "recording.info"), "w")
        )
        assert h264_to_mp4.folder_is_ready(folder) is True

    def test_recent_chunk_no_marker_not_ready(self, tmp_path):
        folder = str(tmp_path / "recent")
        _make_chunk(folder, age_hours=0)
        assert h264_to_mp4.folder_is_ready(folder, max_age_hours=6) is False

    def test_old_chunk_no_marker_ready_via_age(self, tmp_path):
        folder = str(tmp_path / "old")
        _make_chunk(folder, age_hours=7)
        assert h264_to_mp4.folder_is_ready(folder, max_age_hours=6) is True

    def test_no_chunks_not_ready(self, tmp_path):
        folder = str(tmp_path / "empty")
        os.makedirs(folder)
        assert h264_to_mp4.folder_is_ready(folder) is False


class TestReadMarkerFps:
    def test_reads_fps(self, tmp_path):
        folder = str(tmp_path / "f")
        os.makedirs(folder)
        json.dump({"fps": 15}, open(os.path.join(folder, "recording.info"), "w"))
        assert h264_to_mp4.read_marker_fps(folder) == 15.0

    def test_missing_marker_returns_none(self, tmp_path):
        folder = str(tmp_path / "f")
        os.makedirs(folder)
        assert h264_to_mp4.read_marker_fps(folder) is None

    def test_corrupt_marker_returns_none(self, tmp_path):
        folder = str(tmp_path / "f")
        os.makedirs(folder)
        with open(os.path.join(folder, "recording.info"), "w") as fh:
            fh.write("{not valid json")
        assert h264_to_mp4.read_marker_fps(folder) is None

    def test_marker_without_fps_returns_none(self, tmp_path):
        folder = str(tmp_path / "f")
        os.makedirs(folder)
        json.dump(
            {"status": "completed"}, open(os.path.join(folder, "recording.info"), "w")
        )
        assert h264_to_mp4.read_marker_fps(folder) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
