"""
DeepTubeTracker end to end: camera, ROI builder, Monitor and SQLite writer on a real video.

Both trackers track the first seconds of the repository's 20-tube video into their
own database, and the databases must have the same layout, so that nothing
downstream (backups, the node, ethoscopy) can tell which tracker wrote one except by
its METADATA.
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
SECONDS = 5


def track(tracker_class, db_path):
    """Track the first seconds of the video into ``db_path``; return the ROIs."""
    cam = MovieVirtualCamera(str(VIDEO), max_duration=SECONDS)
    _, rois = FileBasedROIBuilder(template_name="sleep_monitor_20tube").build(cam)
    cam.restart()
    try:
        monitor = Monitor(cam, tracker_class, rois)
        with SQLiteResultWriter(
            {"name": str(db_path)}, rois, take_frame_shots=False
        ) as writer:
            monitor.run(result_writer=writer)
    finally:
        cam._close()
    return rois


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    out = {}
    for cls in (AdaptiveBGModel, DeepTubeTracker):
        path = tmp_path_factory.mktemp(cls.__name__) / "run.db"
        rois = track(cls, path)
        out[cls.__name__] = (sqlite3.connect(path), rois)
    yield out
    for con, _ in out.values():
        con.close()


@pytest.mark.integration
def test_both_trackers_write_the_same_tables(dbs):
    (abg, _), (deep, _) = dbs["AdaptiveBGModel"], dbs["DeepTubeTracker"]
    for table in ("ROI_1", "ROI_20", "VAR_MAP"):
        layout = f"PRAGMA table_info({table})"
        assert abg.execute(layout).fetchall() == deep.execute(layout).fetchall()
    var_map = "SELECT * FROM VAR_MAP ORDER BY var_name"
    assert abg.execute(var_map).fetchall() == deep.execute(var_map).fetchall()


@pytest.mark.integration
def test_every_tube_is_tracked_inside_its_roi(dbs):
    con, rois = dbs["DeepTubeTracker"]
    for roi in rois:
        _, _, w, h = roi.rectangle
        rows = con.execute(f"SELECT x, y, is_inferred FROM ROI_{roi.idx}").fetchall()
        assert len(rows) > 50, f"ROI {roi.idx}: {len(rows)} rows"
        assert all(0 <= x < w and 0 <= y < h for x, y, _ in rows)
        # BOOLEAN columns come back as the text '0' / '1', for either tracker
        assert sum(int(inf) for *_, inf in rows) / len(rows) < 0.05
