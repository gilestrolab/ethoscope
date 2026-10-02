"""End-to-end test of the extractor on a synthetic run."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dl_tracking import extract

from .conftest import make_db, still_rows


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """
    A 20-min run at 1 fps with snapshots at 5, 11, 12.5 and 15 min.

    ROI_1: a still fly lost between 12 and 13 min, found again in place.
    ROI_2: never detected. ROI_3: a normal fly whose blob is tiny at 15 min.
    """
    monkeypatch.setattr(extract, "TMP_DIR", tmp_path / "tmp")
    (tmp_path / "tmp").mkdir()
    roi1 = still_rows(0, 720_000, 1000, 100, 30) + still_rows(
        780_000, 1_200_000, 1000, 101, 30
    )
    roi3 = still_rows(0, 1_200_000, 1000, 300, 25)
    roi3[900] = (900_000, 300, 25, 8, 4, 0, -2750, 0)
    path = tmp_path / "src" / "abc" / "ETHOSCOPE_001" / "2020-01-01_00-00-00" / "r.db"
    make_db(path, {1: roi1, 2: [], 3: roi3}, [300_000, 660_000, 750_000, 900_000])
    return {"path": str(path), "machine_id": "abc", "run_dt": "2020-01-01_00-00-00"}


def test_extract_run_statuses(run: dict, tmp_path: Path) -> None:
    """Each tube gets the status its track implies; warm-up snapshots are skipped."""
    out = tmp_path / "out"
    summary = extract.extract_run(run, out)
    assert summary["error"] is None
    labels = pd.read_parquet(out / "labels" / "abc_2020-01-01_00-00-00.parquet")
    got = {(r.roi_idx, r.t): r.status for r in labels.itertuples()}
    assert 300_000 not in {t for _, t in got}  # inside the 10-min warm-up
    assert got[(1, 660_000)] == "confident"
    assert got[(1, 750_000)] == "gapfill"
    assert got[(2, 750_000)] == "never_detected"
    assert got[(3, 900_000)] == "rejected_size"
    gap = labels[(labels.roi_idx == 1) & (labels.t == 750_000)].iloc[0]
    assert (gap.x, gap.gap_ms) == (100.5, 61_000)
    snaps = pd.read_parquet(out / "snaps" / "abc_2020-01-01_00-00-00.parquet")
    assert len(snaps) == 3 and snaps.jpeg.map(len).min() > 100
    assert not any((tmp_path / "tmp").iterdir())  # the local copy is gone


def test_missing_roi_table_is_never_detected(run: dict, tmp_path: Path) -> None:
    """A ROI with no table (never a single detection) is never_detected, not an error."""
    with sqlite3.connect(run["path"]) as conn:
        conn.execute("DROP TABLE ROI_2")
    out = tmp_path / "out"
    assert extract.extract_run(run, out)["error"] is None
    labels = pd.read_parquet(out / "labels" / "abc_2020-01-01_00-00-00.parquet")
    assert set(labels[labels.roi_idx == 2].status) == {"never_detected"}


def test_extract_run_is_resumable(run: dict, tmp_path: Path) -> None:
    """A run whose labels exist is skipped."""
    out = tmp_path / "out"
    extract.extract_run(run, out)
    assert extract.extract_run(run, out).get("skipped") is True


def test_extract_run_reports_bad_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt DB is reported in the summary and leaves no output behind."""
    monkeypatch.setattr(extract, "TMP_DIR", tmp_path)
    bad = tmp_path / "src" / "x" / "E" / "d" / "bad.db"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(np.random.default_rng(0).bytes(8192))
    summary = extract.extract_run(
        {"path": str(bad), "machine_id": "x", "run_dt": "d"}, tmp_path / "out"
    )
    assert summary["error"].startswith("DatabaseError")
    assert not (tmp_path / "out" / "labels").exists()


def test_choose_snapshots_spreads_over_run() -> None:
    """One snapshot per time bin, all after the warm-up, repeatable per seed."""
    snaps = np.column_stack([np.arange(1, 1001), 300_000 * np.arange(1000)])
    a = extract.choose_snapshots(snaps, 25, 1)
    assert len(a) == 25 and a[:, 1].min() >= extract.WARMUP_MS
    assert np.all(np.diff(a[:, 1]) > 0)
    assert np.array_equal(a, extract.choose_snapshots(snaps, 25, 1))
    assert len(extract.choose_snapshots(snaps[:5], 25, 1)) == 3  # 2 in warm-up
