"""Extract labelled snapshots from tracking DBs.

Each DB is copied to local NVMe first: the results array sustains ~300 random
reads/s but reads a file sequentially in seconds, and the labelling below makes
thousands of small queries. Per run, two parquet files are written:

- ``snaps/<run_id>.parquet``: ``snap_rowid, t, jpeg`` (the original blobs);
- ``labels/<run_id>.parquet``: one row per (snapshot, ROI) with a ``status`` of
  ``confident``, ``gapfill``, ``rejected_size`` / ``rejected_hop`` (detected but
  untrustworthy; the tracker's position is kept), ``missed`` (not detected, not
  gap-fillable) or ``never_detected`` (the tube's table is near-empty: an empty tube
  or a fly dead from the start, for human review).

Extraction records facts, not decisions: thresholds that depend on the whole run
(such as the contrast a gap-filled label needs) are applied when the dataset is
assembled.

Usage::

    python -m dl_tracking.extract --runs runs.parquet --out /mnt/cache/dl_tracking/data
"""

from __future__ import annotations

import argparse
import logging
import shutil
import zlib
from dataclasses import asdict
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from . import db_io
from . import labels as L

N_SNAPSHOTS = 25
WARMUP_MS = 10 * 60 * 1000  # AdaptiveBGModel is still building its background
NEVER_DETECTED_ROWS = 1000  # fewer rows than this in a whole run
N_SIZE_SAMPLES = 2000
TMP_DIR = Path("/mnt/cache/dl_tracking/tmp")


def write_atomic(df: pd.DataFrame, path: Path) -> None:
    """
    Write a parquet file so that it either exists complete or not at all.

    A run counts as finished when its labels file exists; a file cut short by an
    interrupted write would otherwise be taken for a finished run and never redone.

    Args:
        df (pd.DataFrame): The table.
        path (Path): Destination.
    """
    tmp = path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp)
    tmp.replace(path)


def run_id(rec: dict) -> str:
    """
    Name a run uniquely across machines.

    Args:
        rec (dict): Census record.

    Returns:
        str: ``<machine_id>_<run_dt>``.
    """
    return f"{rec['machine_id']}_{rec['run_dt']}"


def choose_snapshots(snaps: np.ndarray, n: int, seed: int) -> np.ndarray:
    """
    Pick up to ``n`` snapshots after the warm-up, one at random in each of ``n``
    equal time bins, so that every part of the run (day and night) is represented.

    Args:
        snaps (np.ndarray): ``(rowid, t)`` rows from :func:`db_io.snapshot_times`.
        n (int): Number wanted.
        seed (int): Random seed (derived from the run, so extraction is repeatable).

    Returns:
        np.ndarray: The chosen ``(rowid, t)`` rows, in time order.
    """
    snaps = snaps[snaps[:, 1] >= WARMUP_MS]
    if len(snaps) <= n:
        return snaps
    rng = np.random.default_rng(seed)
    edges = np.linspace(0, len(snaps), n + 1).astype(int)
    idx = [
        rng.integers(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True) if b > a
    ]
    return snaps[idx]


def label_roi(
    conn, table: str, n_rows: int, snaps: np.ndarray, params: L.LabelParams
) -> list[dict]:
    """
    Label one ROI in every chosen snapshot.

    Args:
        conn: Open connection to the local copy.
        table (str): ROI table name.
        n_rows (int): ``max(rowid)`` of the table.
        snaps (np.ndarray): Chosen ``(rowid, t)`` snapshot rows.
        params (L.LabelParams): Label thresholds.

    Returns:
        list[dict]: One record per snapshot (without image-derived fields).
    """
    if n_rows < NEVER_DETECTED_ROWS:
        return [{"status": "never_detected"} for _ in snaps]
    sample = db_io.rows_at_rowids(
        conn, table, np.unique(np.linspace(1, n_rows, N_SIZE_SAMPLES).astype(int))
    )
    bounds = L.size_bounds(sample, params)
    out = []
    for _, t in snaps:
        t = int(t)
        window = db_io.rows_between(
            conn, table, t - params.window_ms, t + params.window_ms
        )
        lab = L.detection_label(window, t, bounds, params)
        if lab is None:
            rowid = db_io.rowid_at_time(conn, table, t)
            before = db_io.nearest_real(conn, table, rowid, forward=False)
            after = db_io.nearest_real(conn, table, rowid - 1, forward=True)
            lab = L.gapfill_label(before, after, t, params)
        out.append({"status": lab.kind, **asdict(lab)} if lab else {"status": "missed"})
    return out


def extract_run(rec: dict, out: Path, params: L.LabelParams = L.LabelParams()) -> dict:
    """
    Copy one DB locally, label its chosen snapshots, write parquet, delete the copy.

    Args:
        rec (dict): Census record (needs ``path``, ``machine_id``, ``run_dt``).
        out (Path): Output root (``snaps/`` and ``labels/`` are created under it).
        params (L.LabelParams): Label thresholds.

    Returns:
        dict: ``run_id``, counts per status, and ``error`` (None on success).
    """
    rid = run_id(rec)
    summary: dict = {"run_id": rid, "error": None}
    if (out / "labels" / f"{rid}.parquet").exists():
        return {**summary, "skipped": True}
    local = TMP_DIR / f"{rid}.db"
    try:
        shutil.copyfile(rec["path"], local)
        with db_io.connect(local) as conn:
            rois = db_io.roi_map(conn)
            snaps = choose_snapshots(
                db_io.snapshot_times(conn), N_SNAPSHOTS, zlib.crc32(rid.encode())
            )
            blobs = [
                conn.execute(
                    "SELECT img FROM IMG_SNAPSHOTS WHERE rowid = ?", (int(r),)
                ).fetchone()[0]
                for r, _ in snaps
            ]
            images = [
                cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE)
                for b in blobs
            ]
            records = []
            tables = db_io.tables(conn)
            for idx, x0, y0, w, h in rois:
                table = f"ROI_{int(idx)}"
                # Reason: the writer creates a ROI's table with its first row, so a
                # fly never detected (dead from the start) has no table at all.
                n_rows = db_io.max_rowid(conn, table) if table in tables else 0
                for (srow, t), img, lab in zip(
                    snaps,
                    images,
                    label_roi(conn, table, n_rows, snaps, params),
                    strict=True,
                ):
                    if "x" in lab and img is not None:
                        crop = img[y0 : y0 + h, x0 : x0 + w]
                        lab["contrast"] = L.local_contrast(crop, lab["x"], lab["y"])
                    records.append(
                        {
                            "run_id": rid,
                            "snap_rowid": int(srow),
                            "t": int(t),
                            "roi_idx": int(idx),
                            "roi_x": int(x0),
                            "roi_y": int(y0),
                            "roi_w": int(w),
                            "roi_h": int(h),
                            "roi_rows": n_rows,
                            **lab,
                        }
                    )
        (out / "snaps").mkdir(parents=True, exist_ok=True)
        (out / "labels").mkdir(parents=True, exist_ok=True)
        write_atomic(
            pd.DataFrame({"snap_rowid": snaps[:, 0], "t": snaps[:, 1], "jpeg": blobs}),
            out / "snaps" / f"{rid}.parquet",
        )
        # Reason: labels are written last, so their presence marks a finished run.
        labels = pd.DataFrame(records)
        write_atomic(labels, out / "labels" / f"{rid}.parquet")
        summary.update(labels["status"].value_counts().to_dict() if len(labels) else {})
    except Exception as exc:  # noqa: BLE001 - one bad DB must not stop the batch
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        # Reason: opening a WAL-mode DB, even read-only, creates -wal and -shm files.
        for leftover in (local, Path(f"{local}-wal"), Path(f"{local}-shm")):
            leftover.unlink(missing_ok=True)
    return summary


def _extract(args: tuple[dict, Path]) -> dict:
    """Pool adapter for :func:`extract_run`."""
    return extract_run(*args)


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs", type=Path, required=True, help="parquet of census rows"
    )
    parser.add_argument("--out", type=Path, default=Path("/mnt/cache/dl_tracking/data"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    runs = pd.read_parquet(args.runs).to_dict("records")
    log = args.out / "extract_log.jsonl"
    args.out.mkdir(parents=True, exist_ok=True)
    with Pool(args.workers) as pool, log.open("a") as fh:
        jobs = [(r, args.out) for r in runs]
        for i, summary in enumerate(pool.imap_unordered(_extract, jobs)):
            fh.write(pd.Series(summary).to_json() + "\n")
            fh.flush()
            if i % 50 == 0:
                logging.info("%d / %d  %s", i, len(runs), summary)


if __name__ == "__main__":
    main()
