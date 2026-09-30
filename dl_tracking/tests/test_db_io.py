"""Tests for the read-only DB helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from dl_tracking import db_io
from dl_tracking.census import census_one

from .conftest import NEW_ROI, make_db, still_rows


def test_rowid_at_time_finds_first_row_at_or_after(db_path: Path) -> None:
    """Bisection lands on the first row with t >= the requested time."""
    with db_io.connect(db_path) as conn:
        assert db_io.rowid_at_time(conn, "ROI_1", 0) == 1
        assert db_io.rowid_at_time(conn, "ROI_1", 1000) == 6
        assert db_io.rowid_at_time(conn, "ROI_1", 1001) == 7
        # Reason: past the end, bisection returns max_rowid + 1 (300 rows).
        assert db_io.rowid_at_time(conn, "ROI_1", 10**9) == 301


def test_rows_between_is_half_open(db_path: Path) -> None:
    """Rows are returned for t0 <= t < t1, in time order."""
    with db_io.connect(db_path) as conn:
        rows = db_io.rows_between(conn, "ROI_1", 1000, 2000)
    assert rows.shape == (5, len(db_io.ROI_COLUMNS))
    assert rows[0, 0] == 1000 and rows[-1, 0] == 1800


def test_rows_between_empty_table(db_path: Path) -> None:
    """An empty ROI table yields an empty array of the right width."""
    with db_io.connect(db_path) as conn:
        rows = db_io.rows_between(conn, "ROI_2", 0, 10**9)
    assert rows.shape == (0, len(db_io.ROI_COLUMNS))


def test_rowid_gaps_are_tolerated(tmp_path: Path) -> None:
    """Deleted rows leave rowid gaps; bisection still finds the right row."""
    path = make_db(
        tmp_path / "a" / "E" / "d" / "r.db", {1: still_rows(0, 10_000, 100, 5, 5)}, []
    )
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM ROI_1 WHERE rowid BETWEEN 40 AND 60")
    with db_io.connect(path) as conn:
        rid = db_io.rowid_at_time(conn, "ROI_1", 4500)
        # Reason: rowids 40-60 held t = 3900..5900; the next surviving row is t = 6000.
        assert db_io.t_at_rowid(conn, "ROI_1", rid) == 6000


def test_text_is_inferred_is_normalised(tmp_path: Path) -> None:
    """The SQLite3 writer stores is_inferred as text; it comes back as 0/1."""
    rows = still_rows(0, 1000, 100, 5, 5, "False") + still_rows(
        1000, 2000, 100, 5, 5, "True"
    )
    path = make_db(tmp_path / "a" / "E" / "d" / "r.db", {1: rows}, [], schema=NEW_ROI)
    with db_io.connect(path) as conn:
        got = db_io.rows_between(conn, "ROI_1", 0, 2000)
    assert got[:10, -1].tolist() == [0] * 10 and got[10:, -1].tolist() == [1] * 10


def test_connection_is_read_only(db_path: Path) -> None:
    """Writing through a db_io connection fails."""
    with db_io.connect(db_path) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM ROI_1")


def test_metadata_parsing(db_path: Path) -> None:
    """Chosen classes and Python-2 experimental_info reprs are parsed."""
    with db_io.connect(db_path) as conn:
        meta = db_io.read_metadata(conn)
    assert db_io.selected_classes(meta["selected_options"]) == {
        "tracker": "AdaptiveBGModel"
    }
    assert db_io.experimental_info(meta)["name"] == "Esteban"
    assert db_io.experimental_info({"experimental_info": "not a dict {"}) == {}


def test_snapshots(db_path: Path) -> None:
    """Snapshot times are listed without image data and decode as grey images."""
    with db_io.connect(db_path) as conn:
        snaps = db_io.snapshot_times(conn)
        img = db_io.read_snapshot(conn, int(snaps[1, 0]))
    assert snaps[:, 1].tolist() == [0, 30_000, 59_800]
    assert img.shape == (960, 1280) and abs(float(img.mean()) - 80) < 3


def test_census_one(db_path: Path) -> None:
    """The census records layout, row counts and snapshot statistics."""
    rec = census_one(db_path)
    assert rec["error"] is None
    assert rec["roi_rows"] == [300, 0]
    assert rec["n_snap"] == 3 and rec["snap_shape"] == [960, 1280]
    assert rec["monotonic"] is True and rec["tracker"] == "AdaptiveBGModel"
    assert rec["t_first"] == 0 and rec["t_last"] == 59_800


def test_census_one_empty_and_corrupt(tmp_path: Path) -> None:
    """Zero-byte and non-SQLite files are reported, not raised."""
    empty = tmp_path / "a" / "E" / "d" / "empty.db"
    empty.parent.mkdir(parents=True)
    empty.touch()
    assert census_one(empty)["error"] == "empty file"
    junk = empty.with_name("junk.db")
    junk.write_bytes(np.random.default_rng(0).bytes(4096))
    assert census_one(junk)["error"].startswith("DatabaseError")


def test_list_runs_prefers_first_root(tmp_path: Path) -> None:
    """A run present in both roots is taken from the first."""
    rel = Path("abc") / "ETHOSCOPE_001" / "2020-01-01_00-00-00" / "r.db"
    for root in ("data", "archive"):
        (tmp_path / root / rel).parent.mkdir(parents=True)
        (tmp_path / root / rel).touch()
    (tmp_path / "archive" / "xyz" / "E" / "d").mkdir(parents=True)
    (tmp_path / "archive" / "xyz" / "E" / "d" / "only.db").touch()
    runs = db_io.list_runs((tmp_path / "data", tmp_path / "archive"))
    assert len(runs) == 2
    assert runs[db_io.run_key(tmp_path / "data" / rel)] == tmp_path / "data" / rel
