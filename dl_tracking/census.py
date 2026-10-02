"""Census of every tracking DB: layout, snapshots, row counts, lighting, quirks.

Read-only. One JSON line per DB is appended to ``<out>.jsonl`` as results arrive,
so an interrupted run resumes where it stopped; ``--finalise`` turns the lines
into ``<out>.parquet``.

Usage::

    python -m dl_tracking.census --out /mnt/cache/dl_tracking/census --workers 16
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from . import db_io

# Reason: the results array is IOPS-bound (~2 s of random reads per DB at first
# draft), so every probe below is a deliberate trade of disk time for information.
N_LUM_SAMPLES = 4
N_MONOTONIC_PROBES = 8


def is_monotonic(conn: sqlite3.Connection, table: str, n_probes: int) -> bool:
    """
    Check that ``t`` is non-decreasing at evenly spaced rowids of a table.

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): Table name.
        n_probes (int): Number of rowids to probe.

    Returns:
        bool: True if every probe is >= the previous one.
    """
    top = db_io.max_rowid(conn, table)
    if top == 0:
        return True
    probes = np.unique(np.linspace(1, top, n_probes).astype(int))
    ts = [db_io.t_at_rowid(conn, table, int(r)) for r in probes]
    ts = [t for t in ts if t is not None]
    return all(b >= a for a, b in zip(ts, ts[1:], strict=False))


def snapshot_stats(conn: sqlite3.Connection) -> dict:
    """
    Count snapshots and decode a few, evenly spaced, for shape and luminance.

    Snapshot rowids run 1..n, so ``max(rowid)`` counts them and evenly spaced
    rowids sample them without scanning the table.

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        dict: ``n_snap``, ``snap_t`` (first and last t), ``snap_shape`` (full
        resolution) and ``snap_lum`` (means at 1/4 scale, in time order).
    """
    table = "IMG_SNAPSHOTS"
    out = {"n_snap": 0, "snap_t": None, "snap_shape": None, "snap_lum": []}
    if table not in db_io.tables(conn) or (top := db_io.max_rowid(conn, table)) == 0:
        return out
    out["n_snap"] = top
    out["snap_t"] = [
        db_io.t_at_rowid(conn, table, 1),
        db_io.t_at_rowid(conn, table, top),
    ]
    for rowid in np.unique(np.linspace(1, top, N_LUM_SAMPLES).astype(int)):
        img = db_io.read_snapshot(conn, int(rowid), cv2.IMREAD_REDUCED_GRAYSCALE_4)
        if img is None:
            continue
        out["snap_lum"].append(round(float(img.mean()), 1))
        if out["snap_shape"] is None:
            full = db_io.read_snapshot(conn, int(rowid), cv2.IMREAD_UNCHANGED)
            out["snap_shape"] = list(full.shape) if full is not None else None
    return out


def census_one(path: Path) -> dict:
    """
    Summarise one DB. Never raises: failures are reported in the ``error`` field.

    Args:
        path (Path): The ``.db`` file.

    Returns:
        dict: One census record (JSON-serialisable).
    """
    key = db_io.run_key(path)
    rec: dict = {
        "path": str(path),
        "machine_id": key.machine_id,
        "machine_name": path.parts[-3],
        "run_dt": key.run_dt,
        "file_size": path.stat().st_size,
        "error": None,
    }
    if rec["file_size"] == 0:
        rec["error"] = "empty file"
        return rec
    try:
        with db_io.connect(path) as conn:
            tabs = db_io.tables(conn)
            meta = db_io.read_metadata(conn)
            classes = db_io.selected_classes(meta.get("selected_options", ""))
            rec.update(
                meta_machine_name=meta.get("machine_name"),
                frame_w=meta.get("frame_width"),
                frame_h=meta.get("frame_height"),
                version=meta.get("version"),
                writer=meta.get("result_writer_type"),
                tracker=classes.get("tracker"),
                roi_builder=classes.get("roi_builder"),
                camera=classes.get("camera"),
                user=db_io.experimental_info(meta).get("name"),
            )
            rois = db_io.roi_map(conn) if "ROI_MAP" in tabs else np.zeros((0, 5))
            rec["roi_map"] = rois.tolist()
            roi_tables = [
                f"ROI_{int(i)}" for i in rois[:, 0] if f"ROI_{int(i)}" in tabs
            ]
            rec["roi_rows"] = [db_io.max_rowid(conn, t) for t in roi_tables]
            if roi_tables:
                first = roi_tables[0]
                rec["roi_schema"] = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name = ?", (first,)
                ).fetchone()[0]
                rec["t_first"] = db_io.t_at_rowid(conn, first, 1)
                last = db_io.max_rowid(conn, first)
                rec["t_last"] = db_io.t_at_rowid(conn, first, last) if last else None
                rec["monotonic"] = is_monotonic(conn, first, N_MONOTONIC_PROBES)
            rec.update(snapshot_stats(conn))
    except Exception as exc:  # noqa: BLE001 - a census must survive any bad file
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def run(out: Path, workers: int) -> None:
    """
    Census every DB not yet in ``<out>.jsonl``, appending results as they arrive.

    Args:
        out (Path): Output stem; writes ``<out>.jsonl``.
        workers (int): Parallel worker processes.
    """
    jsonl = out.with_suffix(".jsonl")
    done = set()
    if jsonl.exists():
        done = {json.loads(line)["path"] for line in jsonl.open()}
    todo = [p for p in db_io.list_runs().values() if str(p) not in done]
    logging.info("%d DBs to census (%d already done)", len(todo), len(done))
    with Pool(workers) as pool, jsonl.open("a") as fh:
        for i, rec in enumerate(pool.imap_unordered(census_one, todo, chunksize=4)):
            fh.write(json.dumps(rec) + "\n")
            if i % 500 == 0:
                fh.flush()
                logging.info("%d / %d", i, len(todo))


def finalise(out: Path) -> pd.DataFrame:
    """
    Convert ``<out>.jsonl`` into ``<out>.parquet``.

    Args:
        out (Path): Output stem.

    Returns:
        pd.DataFrame: The census table.
    """
    df = pd.read_json(out.with_suffix(".jsonl"), lines=True)
    df.to_parquet(out.with_suffix(".parquet"))
    return df


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=Path("/mnt/cache/dl_tracking/census")
    )
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--finalise", action="store_true", help="only build the parquet"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if not args.finalise:
        run(args.out, args.workers)
    finalise(args.out)


if __name__ == "__main__":
    main()
