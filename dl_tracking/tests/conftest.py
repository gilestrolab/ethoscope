"""Synthetic tracking DBs in the two schemas found in the archive."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import cv2
import numpy as np
import pytest

from dl_tracking import dataset, extract

OLD_ROI = (
    "id int(11), t int(11), x smallint(6), y smallint(6), w smallint(6), "
    "h smallint(6), phi smallint(6), xy_dist_log10x1000 smallint(6), "
    "is_inferred tinyint(1), has_interacted smallint(6)"
)
NEW_ROI = (
    "id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER, x INTEGER, y INTEGER, "
    "w INTEGER, h INTEGER, phi INTEGER, xy_dist_log10x1000 INTEGER, "
    "is_inferred TEXT, has_interacted INTEGER"
)


def make_db(
    path: Path,
    roi_rows: dict[int, list[tuple]],
    snapshot_t: list[int],
    schema: str = OLD_ROI,
    options: str = "",
) -> Path:
    """
    Write a small tracking DB.

    Args:
        path (Path): Where to write, as ``<root>/<id>/<NAME>/<dt>/<file>.db``.
        roi_rows (dict[int, list[tuple]]): ROI index to rows of
            ``(t, x, y, w, h, phi, xy_dist, is_inferred)``.
        snapshot_t (list[int]): Times of grey 1280x960 snapshots to store.
        schema (str): ROI table column definitions.
        options (str): Value of the METADATA ``selected_options`` field.

    Returns:
        Path: ``path``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE METADATA (field char(100), value varchar(3000))")
    meta = {
        "machine_name": "ETHOSCOPE_001",
        "frame_width": "1280",
        "frame_height": "960",
        "experimental_info": "{'name': u'Esteban', 'location': u'inc 4'}",
        "selected_options": options,
    }
    conn.executemany("INSERT INTO METADATA VALUES (?, ?)", meta.items())
    conn.execute(
        "CREATE TABLE ROI_MAP (roi_idx smallint(6), roi_value smallint(6), "
        "x smallint(6), y smallint(6), w smallint(6), h smallint(6))"
    )
    for idx, rows in roi_rows.items():
        conn.execute(
            "INSERT INTO ROI_MAP VALUES (?, ?, ?, ?, ?, ?)",
            (idx, idx, 40, 100 + 64 * idx, 560, 60),
        )
        conn.execute(f"CREATE TABLE ROI_{idx} ({schema})")
        conn.executemany(
            f"INSERT INTO ROI_{idx} (t, x, y, w, h, phi, xy_dist_log10x1000, "
            "is_inferred, has_interacted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            rows,
        )
    conn.execute("CREATE TABLE IMG_SNAPSHOTS (id int(11), t int(11), img longblob)")
    for i, t in enumerate(snapshot_t):
        img = np.full((960, 1280), 60 + 20 * i, np.uint8)
        blob = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 50])[1].tobytes()
        conn.execute("INSERT INTO IMG_SNAPSHOTS VALUES (?, ?, ?)", (0, t, blob))
    conn.commit()
    conn.close()
    return path


def still_rows(t0: int, t1: int, step: int, x: float, y: float, inferred=0) -> list:
    """
    Rows of a fly sitting at (x, y) from ``t0`` to ``t1`` (exclusive).

    Args:
        t0 (int): Start time in ms.
        t1 (int): End time in ms.
        step (int): Frame interval in ms.
        x (float): x position.
        y (float): y position.
        inferred (int | str): ``is_inferred`` value as the writer stores it.

    Returns:
        list: Rows for :func:`make_db`.
    """
    return [(t, x, y, 24, 11, 10, -2750, inferred) for t in range(t0, t1, step)]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A two-ROI DB: ROI_1 has one row every 200 ms for 60 s, ROI_2 is empty."""
    path = tmp_path / "abc123" / "ETHOSCOPE_001" / "2016-03-07_12-23-39" / "run.db"
    options = (
        "{'tracker': {'possible_classes': [<class 'ethoscope.trackers.adaptive_bg_"
        "tracker.AdaptiveBGModel'>], 'class': <class 'ethoscope.trackers.adaptive_bg_"
        "tracker.AdaptiveBGModel'>, 'kwargs': {}}}"
    )
    return make_db(
        path,
        {1: still_rows(0, 60_000, 200, 100, 30), 2: []},
        [0, 30_000, 59_800],
        options=options,
    )


@pytest.fixture
def packed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Extract and pack a synthetic 20-min run (flat grey snapshots, two tubes)."""
    monkeypatch.setattr(extract, "TMP_DIR", tmp_path)
    roi1 = still_rows(0, 1_200_000, 1000, 100, 30)
    roi2 = still_rows(0, 600_000, 1000, 400, 30) + still_rows(
        600_000, 1_200_000, 1000, 150, 30
    )
    path = tmp_path / "src" / "abc" / "E1" / "2020-01-01_00-00-00" / "r.db"
    make_db(path, {1: roi1, 2: roi2}, [700_000, 800_000, 900_000])
    extract.extract_run(
        {"path": str(path), "machine_id": "abc", "run_dt": "2020-01-01_00-00-00"},
        tmp_path / "out",
    )
    dataset.pack(tmp_path / "out")
    return tmp_path / "out" / "pack"
