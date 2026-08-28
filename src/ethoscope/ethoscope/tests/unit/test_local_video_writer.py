"""
Unit tests for the local (non-Pi) video writer in ``record.py``.

A Pi camera records by itself, in the camera class; any other camera falls back to
writing the frames that come out of the acquisition queue with ``cv2.VideoWriter``.
That fallback used to construct a *new* writer on every single frame - the
construction sat outside the rotation test - so each file received at most one
frame, no writer was ever released, and the chunk index climbed with the frame
counter. These tests pin the intended behaviour: one writer opened after the FPS
warm-up, reused for every frame, rotated only when a chunk is full.
"""

import os
import threading

import pytest

try:
    from ethoscope.control import record
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))
    from ethoscope.control import record


class FakeWriter:
    """Stands in for cv2.VideoWriter, recording what was asked of it."""

    instances = []

    def __init__(self, filename, fourcc, fps, size, opens=True):
        self.filename = filename
        self.fps = fps
        self.size = size
        self.frames_written = 0
        self.released = False
        self._opens = opens
        FakeWriter.instances.append(self)

    def isOpened(self):
        return self._opens and not self.released

    def write(self, frame):
        self.frames_written += 1

    def release(self):
        self.released = True


class FakeCamera:
    """Yields a fixed number of frames, then asks the capture thread to stop."""

    def __init__(self, thread, n_frames, fps=15.0, width=64, height=48):
        self._thread = thread
        self._n_frames = n_frames
        self.fps = fps
        self.width = width
        self.height = height
        self.isPiCamera = False
        self.closed = False

    def __iter__(self):
        for i in range(self._n_frames):
            yield (i, "frame")
        # Exhausting the camera would otherwise send run() round its outer loop.
        self._thread.stop_camera_activity = True

    def _close(self):
        self.closed = True


def _make_recorder(tmp_path, n_frames, chunk_duration=None, writer_opens=True):
    """
    Build a cameraCaptureThread for the local-recording path, without a camera.

    Args:
        tmp_path: pytest tmp_path, used as the video prefix directory.
        n_frames (int): how many frames the fake camera produces.
        chunk_duration (float): overrides _VIDEO_CHUNCK_DURATION; 0 makes every
            frame after the warm-up rotate the chunk.
        writer_opens (bool): whether the fake writers report themselves open.

    Returns:
        cameraCaptureThread: ready to have run() called on it.
    """
    obj = record.cameraCaptureThread.__new__(record.cameraCaptureThread)
    obj.stop_camera_activity = False
    obj._stream = False
    obj._local_recording = True
    obj._resolution = (64, 48)
    obj._video_prefix = str(tmp_path / "prefix")
    obj._img_path = str(tmp_path / "last_img.jpg")
    obj.video_file_index = 0
    obj._stream_lock = threading.Lock()
    obj.camera = FakeCamera(obj, n_frames)

    if chunk_duration is not None:
        obj._VIDEO_CHUNCK_DURATION = chunk_duration

    FakeWriter.instances = []
    obj._writer_opens = writer_opens
    return obj


@pytest.fixture
def patched_writer(monkeypatch):
    """Replace cv2.VideoWriter, as seen by record.py, with FakeWriter."""
    created = {"opens": True}

    def factory(filename, fourcc, fps, size):
        return FakeWriter(filename, fourcc, fps, size, opens=created["opens"])

    monkeypatch.setattr(record.cv2, "VideoWriter", factory)
    return created


class TestWarmUp:
    """The writer cannot be opened before the measured FPS has settled."""

    def test_no_writer_before_the_warm_up_is_over(self, tmp_path, patched_writer):
        """Fewer frames than the warm-up produces no file at all."""
        recorder = _make_recorder(
            tmp_path, n_frames=record.cameraCaptureThread._FRAMES_BEFORE_RECORDING - 1
        )
        recorder.run()

        assert FakeWriter.instances == []

    def test_one_writer_takes_every_frame_after_the_warm_up(
        self, tmp_path, patched_writer
    ):
        """Expected use: a single chunk, holding every post-warm-up frame."""
        warm_up = record.cameraCaptureThread._FRAMES_BEFORE_RECORDING
        recorder = _make_recorder(tmp_path, n_frames=warm_up + 10)
        recorder.run()

        assert len(FakeWriter.instances) == 1
        writer = FakeWriter.instances[0]
        # Frames warm_up .. warm_up+9 inclusive; the writer opens on the first of them.
        assert writer.frames_written == 10
        assert writer.fps == recorder.camera.fps
        assert writer.released is True  # run() releases on the way out
        assert writer.filename.endswith("_00001.h264")


class TestChunkRotation:
    """Rotation closes the old file and opens the next one, and only then."""

    def test_full_chunk_rotates_and_releases_the_previous_writer(
        self, tmp_path, patched_writer
    ):
        """Edge case: a chunk duration of zero rotates on every frame."""
        warm_up = record.cameraCaptureThread._FRAMES_BEFORE_RECORDING
        recorder = _make_recorder(tmp_path, n_frames=warm_up + 3, chunk_duration=0)
        recorder.run()

        assert len(FakeWriter.instances) == 3
        assert [w.frames_written for w in FakeWriter.instances] == [1, 1, 1]
        assert all(w.released for w in FakeWriter.instances)
        assert [os.path.basename(w.filename)[-11:] for w in FakeWriter.instances] == [
            "_00001.h264",
            "_00002.h264",
            "_00003.h264",
        ]


class TestWriterThatWillNotOpen:
    """A destination that cannot be opened must not take frames, or crash."""

    def test_frames_are_not_written_to_a_closed_writer(
        self, tmp_path, patched_writer, caplog
    ):
        """Failure case: cv2 refuses the codec or the path."""
        patched_writer["opens"] = False
        warm_up = record.cameraCaptureThread._FRAMES_BEFORE_RECORDING
        recorder = _make_recorder(tmp_path, n_frames=warm_up + 5)

        recorder.run()

        assert len(FakeWriter.instances) == 1
        assert FakeWriter.instances[0].frames_written == 0
        assert "failed to open Video writer" in caplog.text
        assert recorder.camera.closed is True
