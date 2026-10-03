"""
Unit tests for the node-side h264->mp4 conversion gating helpers.

These cover the readiness gate that prevents the daily cron from converting a recording while
it is still in progress, plus reading the recording FPS from the marker file. No ffmpeg/ffprobe
is exercised here - only the pure folder-inspection logic.
"""

import importlib.util
import io
import json
import os
import time
import types

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
        _make_chunk(folder)
        later = time.time() + 7 * 3600
        assert h264_to_mp4.folder_is_ready(folder, max_age_hours=6, now=later) is True

    def test_an_old_chunk_that_just_arrived_is_not_ready(self, tmp_path):
        """A device hours behind its backup: the chunk was written long ago (mtime,
        kept by rsync) but has only just landed here, so more may follow."""
        folder = str(tmp_path / "behind")
        _make_chunk(folder, age_hours=12)
        assert h264_to_mp4.folder_is_ready(folder, max_age_hours=6) is False

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


def _chunks(folder, n, start=1, size=10):
    """Create chunks ``rec_<start>..`` of *size* bytes; return their names."""
    os.makedirs(folder, exist_ok=True)
    names = []
    for i in range(start, start + n):
        name = f"rec_{i:05d}.h264"
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"x" * size)
        names.append(name)
    return names


def _manifest(folder, names, video="rec_merged.mp4"):
    """Write a merged video and the chunk list naming *names*."""
    open(os.path.join(folder, video), "wb").write(b"mp4")
    h264_to_mp4.write_manifest(os.path.join(folder, video), names, 15)


class FakeFfmpeg:
    """Stands in for subprocess.Popen: writes the output file, exits with *rc*."""

    def __init__(self, rc=0):
        self.rc = rc

    def __call__(self, cmd, **kwargs):
        with open(cmd[cmd.index("-y") + 1], "wb") as f:
            f.write(b"merged" if self.rc == 0 else b"half")
        proc = types.SimpleNamespace(stdout=io.StringIO(""), returncode=self.rc)
        proc.poll = lambda: self.rc
        proc.wait = lambda: self.rc
        return proc


class TestChunks:
    def test_index_and_listing_skip_hidden_and_unnumbered_files(self, tmp_path):
        folder = str(tmp_path)
        _chunks(folder, 2)
        open(
            os.path.join(folder, ".rec_00003.h264.Ab12Cd"), "w"
        ).close()  # rsync in transit
        open(os.path.join(folder, "notes.h264"), "w").close()
        assert h264_to_mp4.chunk_index("x_00042.h264") == 42
        assert h264_to_mp4.list_chunks(folder) == ["rec_00001.h264", "rec_00002.h264"]

    def test_contiguity(self):
        assert h264_to_mp4.chunks_contiguous(["a_00001.h264", "a_00002.h264"])
        assert not h264_to_mp4.chunks_contiguous(["a_00001.h264", "a_00003.h264"])
        assert not h264_to_mp4.chunks_contiguous(["a_00002.h264"])  # chunk 1 purged
        assert not h264_to_mp4.chunks_contiguous([])


class TestNeedsMerge:
    def test_unmerged_folder(self, tmp_path):
        _chunks(str(tmp_path), 3)
        assert h264_to_mp4.needs_merge(str(tmp_path))[0] is True

    def test_merged_folder_with_every_chunk_listed(self, tmp_path):
        folder = str(tmp_path)
        _manifest(folder, _chunks(folder, 3))
        assert h264_to_mp4.needs_merge(folder) == (False, "merged")

    def test_chunks_that_arrived_after_the_merge(self, tmp_path):
        """ETHOSCOPE_361: a video of the first 21 chunks, then 20 more arrived."""
        folder = str(tmp_path)
        _manifest(folder, _chunks(folder, 2))
        _chunks(folder, 2, start=3)
        merge, reason = h264_to_mp4.needs_merge(folder)
        assert merge is True and reason.startswith("2 chunk(s)")

    def test_a_video_without_a_list_is_stale_when_chunks_arrived_after_it(
        self, tmp_path
    ):
        folder = str(tmp_path)
        _chunks(folder, 2)
        open(os.path.join(folder, "rec_merged.mp4"), "wb").write(b"mp4")
        time.sleep(0.02)
        _chunks(folder, 1, start=3)
        assert h264_to_mp4.needs_merge(folder)[0] is True

    def test_a_video_without_a_list_newer_than_its_chunks_is_left(self, tmp_path):
        folder = str(tmp_path)
        _chunks(folder, 2)
        time.sleep(0.02)
        open(os.path.join(folder, "rec_merged.mp4"), "wb").write(b"mp4")
        assert h264_to_mp4.needs_merge(folder)[0] is False

    def test_a_gap_or_purged_start_is_never_merged(self, tmp_path):
        """Merging chunks 3-4 after 1-2 were purged would overwrite the video of 1-2."""
        folder = str(tmp_path)
        _chunks(folder, 2, start=3)
        open(os.path.join(folder, "rec_merged.mp4"), "wb").write(b"mp4")
        assert h264_to_mp4.needs_merge(folder)[0] is False


class TestProcessVideo:
    def test_writes_the_video_then_its_chunk_list(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        folder = str(tmp_path / "run")
        names = _chunks(folder, 3, size=7)
        monkeypatch.setattr(h264_to_mp4.subprocess, "Popen", FakeFfmpeg(0))
        assert h264_to_mp4.process_video(folder, user_fps=15) is True
        video = os.path.join(folder, "rec_merged.mp4")
        manifest = h264_to_mp4.read_manifest(video)
        assert open(video, "rb").read() == b"merged"
        assert [c["name"] for c in manifest["chunks"]] == names
        assert {c["size"] for c in manifest["chunks"]} == {7}
        assert sorted(os.listdir(folder)) == sorted(
            names + ["rec_merged.mp4", "rec_merged.mp4.json"]
        )

    def test_a_failed_merge_leaves_the_previous_video_and_list(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        folder = str(tmp_path / "run")
        _manifest(folder, _chunks(folder, 2))
        _chunks(folder, 1, start=3)
        monkeypatch.setattr(h264_to_mp4.subprocess, "Popen", FakeFfmpeg(1))
        assert h264_to_mp4.process_video(folder, user_fps=15) is False
        video = os.path.join(folder, "rec_merged.mp4")
        assert open(video, "rb").read() == b"mp4"
        assert len(h264_to_mp4.read_manifest(video)["chunks"]) == 2
        assert not [n for n in os.listdir(folder) if n.endswith((".part", ".tmp"))]


class TestPurge:
    def test_deletes_only_listed_chunks_of_the_listed_size(self, tmp_path):
        folder = str(tmp_path / "run")
        names = _chunks(folder, 3)
        _manifest(folder, names[:2])
        with open(os.path.join(folder, names[1]), "ab") as f:
            f.write(b"grown")  # no longer the chunk that was merged
        h264_to_mp4.purge_h264_files(str(tmp_path))
        assert h264_to_mp4.list_chunks(folder) == names[1:]

    def test_a_video_without_a_list_keeps_its_chunks(self, tmp_path):
        folder = str(tmp_path / "run")
        names = _chunks(folder, 2)
        open(os.path.join(folder, "rec_merged.mp4"), "wb").write(b"mp4")
        h264_to_mp4.purge_h264_files(str(tmp_path))
        assert h264_to_mp4.list_chunks(folder) == names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
