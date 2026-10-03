"""
A camera dropout mid-run, end to end: the run continues into the same database.

The repository's 20-tube video is played with a 3-s stretch missing, as a camera
that dropped out and was reopened would leave it, and reports the dropout as the
Pi camera does. Both trackers must keep tracking after the gap, the run's times
must stay monotonic, and CAMERA_EVENTS must hold the gap's two ends.
"""

import sqlite3
from pathlib import Path

import pytest

from ethoscope.core.monitor import Monitor
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.io import SQLiteResultWriter
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.trackers.deep_tube import DeepTubeTracker

VIDEO = Path(__file__).parents[1] / "static_files/videos/arena_10x2_sortTubes.mp4"
GAP_AT, GAP_FRAMES = 40, 60  # ~3 s of the ~20 fps video


class DroppingVideo(MovieVirtualCamera):
    """The video with a stretch missing, reported as a camera dropout."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dropouts = 0

    def _next_time_image(self):
        t, image = super()._next_time_image()
        if self._frame_idx == GAP_AT and self._dropouts == 0:
            for _ in range(GAP_FRAMES):
                t, image = super()._next_time_image()
            self._dropouts = 1
        return t, image

    def camera_state(self):
        return {"dropouts": self._dropouts, "recovering": False,
                "last_power": "under-voltage", "gave_up": False}  # fmt: skip


def track(tracker_class, db_path):
    cam = DroppingVideo(str(VIDEO), max_duration=8)
    _, rois = FileBasedROIBuilder(template_name="sleep_monitor_20tube").build(cam)
    cam.restart()
    cam._dropouts = 0
    try:
        with SQLiteResultWriter(
            {"name": str(db_path)}, rois, take_frame_shots=False
        ) as writer:
            Monitor(cam, tracker_class, rois).run(result_writer=writer)
    finally:
        cam._close()


@pytest.mark.integration
@pytest.mark.parametrize("tracker_class", [AdaptiveBGModel, DeepTubeTracker])
def test_a_run_continues_through_a_camera_dropout(tracker_class, tmp_path):
    db = tmp_path / "run.db"
    track(tracker_class, db)
    con = sqlite3.connect(db)
    events = con.execute(
        "SELECT t, event, detail FROM CAMERA_EVENTS ORDER BY t"
    ).fetchall()
    assert [e[1] for e in events] == ["dropout", "recovered"]
    gap_start, gap_end = events[0][0], events[1][0]
    assert gap_end - gap_start > 2500 and "under-voltage" in events[0][2]

    times = [t for (t,) in con.execute("SELECT t FROM ROI_1 ORDER BY id")]
    assert times == sorted(times)  # monotonic, through the gap
    after = [t for t in times if t >= gap_end]
    assert len(after) > 20, "tracking did not continue after the dropout"
    assert not [t for t in times if gap_start < t < gap_end]
