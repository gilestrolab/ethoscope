"""Read-only access to ethoscope tracking databases.

Everything here opens databases with ``mode=ro`` and never writes. The ROI tables
carry no index on ``t``, but rows are appended in time order, so a time window is
found by bisecting on ``rowid`` (O(log n) page reads) instead of scanning a table
that can hold millions of rows.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

RESULTS_ROOTS = (
    Path("/mnt/data/results"),
    Path("/mnt/archive/Archive/ethoscope_results/results"),
)
ROI_COLUMNS = ("t", "x", "y", "w", "h", "phi", "xy_dist_log10x1000", "is_inferred")
_CLASS_RE = re.compile(
    r"'(\w+)': \{'possible_classes': \[.*?\], 'class': <class '([\w\.]+)'>"
)


def _inferred(value) -> int:
    """
    Normalise ``is_inferred``, stored as 0/1 by the old writers and as text by SQLite3.

    Args:
        value: The stored value.

    Returns:
        int: 1 if the row is inferred, else 0.
    """
    return 1 if str(value).lower() in ("1", "true") else 0


def _normalise(rows: list[tuple]) -> np.ndarray:
    """
    Convert fetched ROI rows to an ``(n, 8)`` float array with 0/1 ``is_inferred``.

    Args:
        rows (list[tuple]): Rows in :data:`ROI_COLUMNS` order.

    Returns:
        np.ndarray: The rows.
    """
    out = [(*r[:-1], _inferred(r[-1])) for r in rows]
    return np.array(out, dtype=np.float64).reshape(-1, len(ROI_COLUMNS))


@dataclass(frozen=True)
class RunKey:
    """Identity of one recording, independent of which root holds it."""

    machine_id: str
    run_dt: str
    filename: str


def run_key(path: Path) -> RunKey:
    """
    Build the identity of a DB from its ``<machine_id>/<NAME>/<date_time>/<file>`` path.

    Args:
        path (Path): Path to a ``.db`` file under a results root.

    Returns:
        RunKey: The machine id, run folder name and file name.
    """
    return RunKey(path.parts[-4], path.parts[-2], path.parts[-1])


def list_runs(roots: tuple[Path, ...] = RESULTS_ROOTS) -> dict[RunKey, Path]:
    """
    List every DB under the given roots, the first root winning on duplicates.

    Args:
        roots (tuple[Path, ...]): Results roots, in order of preference.

    Returns:
        dict[RunKey, Path]: One path per recording.
    """
    runs: dict[RunKey, Path] = {}
    for root in roots:
        for path in root.glob("*/*/*/*.db"):
            runs.setdefault(run_key(path), path)
    return runs


def connect(path: Path) -> sqlite3.Connection:
    """
    Open a DB strictly read-only.

    Args:
        path (Path): The ``.db`` file.

    Returns:
        sqlite3.Connection: A read-only connection.
    """
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def tables(conn: sqlite3.Connection) -> set[str]:
    """
    Return the table names of a DB.

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        set[str]: Table names.
    """
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {r[0] for r in rows}


def read_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    """
    Return the METADATA table as a dict (empty if the table is missing).

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        dict[str, str]: Field to value, both as stored.
    """
    if "METADATA" not in tables(conn):
        return {}
    return {
        str(f): str(v) for f, v in conn.execute("SELECT field, value FROM METADATA")
    }


def selected_classes(selected_options: str) -> dict[str, str]:
    """
    Extract the chosen class of each option group from a ``selected_options`` repr.

    The value is a Python repr containing ``<class ...>`` objects, so it cannot be
    evaluated; a regex over the ``'class': <class 'x.y.Z'>`` entries is enough.

    Args:
        selected_options (str): The METADATA ``selected_options`` value.

    Returns:
        dict[str, str]: Option group (``tracker``, ``roi_builder``...) to class name.
    """
    return {k: v.rsplit(".", 1)[-1] for k, v in _CLASS_RE.findall(selected_options)}


def experimental_info(meta: dict[str, str]) -> dict:
    """
    Parse the ``experimental_info`` field, tolerating Python-2-era reprs.

    Args:
        meta (dict[str, str]): Output of :func:`read_metadata`.

    Returns:
        dict: The parsed dict, or an empty dict if it cannot be parsed.
    """
    raw = meta.get("experimental_info", "")
    try:
        # Reason: 2016-era values are Python 2 reprs with u'' prefixes.
        value = ast.literal_eval(re.sub(r"\bu'", "'", raw))
    except (ValueError, SyntaxError):
        return {}
    return value if isinstance(value, dict) else {}


def roi_map(conn: sqlite3.Connection) -> np.ndarray:
    """
    Return the ROI bounding boxes as an ``(n, 5)`` int array: idx, x, y, w, h.

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        np.ndarray: One row per ROI, sorted by index.
    """
    rows = conn.execute("SELECT roi_idx, x, y, w, h FROM ROI_MAP ORDER BY roi_idx")
    return np.array(rows.fetchall(), dtype=np.int64).reshape(-1, 5)


def max_rowid(conn: sqlite3.Connection, table: str) -> int:
    """
    Return the largest rowid of a table (0 if empty), without scanning it.

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): Table name.

    Returns:
        int: The largest rowid.
    """
    return conn.execute(f"SELECT max(rowid) FROM {table}").fetchone()[0] or 0


def t_at_rowid(conn: sqlite3.Connection, table: str, rowid: int) -> int | None:
    """
    Return ``t`` of the first row at or after ``rowid`` (rowids may have gaps).

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): Table name.
        rowid (int): Rowid to start from.

    Returns:
        int | None: The time in ms, or None past the end of the table.
    """
    row = conn.execute(
        f"SELECT t FROM {table} WHERE rowid >= ? ORDER BY rowid LIMIT 1", (rowid,)
    ).fetchone()
    return None if row is None else int(row[0])


def rowid_at_time(conn: sqlite3.Connection, table: str, t: int) -> int:
    """
    Return the smallest rowid whose ``t`` is >= ``t``, by bisection on rowid.

    Assumes ``t`` is non-decreasing in rowid, which the census verifies per DB.

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): Table name.
        t (int): Time in ms.

    Returns:
        int: A rowid in ``[1, max_rowid + 1]``; ``max_rowid + 1`` if every row is
        earlier than ``t``.
    """
    lo, hi = 1, max_rowid(conn, table) + 1
    while lo < hi:
        mid = (lo + hi) // 2
        t_mid = t_at_rowid(conn, table, mid)
        if t_mid is not None and t_mid < t:
            lo = mid + 1
        else:
            hi = mid
    return lo


def rows_between(conn: sqlite3.Connection, table: str, t0: int, t1: int) -> np.ndarray:
    """
    Return the ROI rows with ``t0 <= t < t1`` as an ``(n, 8)`` float array.

    Columns follow :data:`ROI_COLUMNS`. ``is_inferred`` is stored as int or as text
    depending on the writer, so it is normalised to 0/1.

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): ROI table name, e.g. ``ROI_3``.
        t0 (int): Start time in ms (inclusive).
        t1 (int): End time in ms (exclusive).

    Returns:
        np.ndarray: The rows, in time order.
    """
    first = rowid_at_time(conn, table, t0)
    cols = ", ".join(ROI_COLUMNS)
    cursor = conn.execute(
        f"SELECT {cols} FROM {table} WHERE rowid >= ? ORDER BY rowid", (first,)
    )
    out = []
    for row in cursor:
        if row[0] >= t1:
            break
        out.append(row)
    return _normalise(out)


def snapshot_times(conn: sqlite3.Connection) -> np.ndarray:
    """
    Return ``(rowid, t)`` of every snapshot, reading no image data.

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        np.ndarray: ``(n, 2)`` int array in time order; empty if there are none.
    """
    if "IMG_SNAPSHOTS" not in tables(conn):
        return np.zeros((0, 2), dtype=np.int64)
    rows = conn.execute("SELECT rowid, t FROM IMG_SNAPSHOTS ORDER BY t").fetchall()
    return np.array(rows, dtype=np.int64).reshape(-1, 2)


def read_snapshot(
    conn: sqlite3.Connection, rowid: int, flags: int = cv2.IMREAD_GRAYSCALE
) -> np.ndarray | None:
    """
    Decode one snapshot as a greyscale image.

    Args:
        conn (sqlite3.Connection): Open connection.
        rowid (int): Snapshot rowid (from :func:`snapshot_times`).
        flags (int): ``cv2.imdecode`` flags; ``IMREAD_REDUCED_GRAYSCALE_4`` is a
            fast option when only statistics are needed.

    Returns:
        np.ndarray | None: The image, or None if the blob does not decode.
    """
    row = conn.execute("SELECT img FROM IMG_SNAPSHOTS WHERE rowid = ?", (rowid,))
    blob = row.fetchone()
    if blob is None or blob[0] is None:
        return None
    return cv2.imdecode(np.frombuffer(blob[0], np.uint8), flags)


def nearest_real(
    conn: sqlite3.Connection, table: str, rowid: int, forward: bool
) -> np.ndarray | None:
    """
    Return the first non-inferred row after (or last before) ``rowid``, exclusive.

    Inferred rows only repeat the last detection for up to 30 s, so the walk is
    short; when the fly was lost for longer the tracker wrote nothing at all.

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): ROI table name.
        rowid (int): Starting rowid (not itself returned).
        forward (bool): Walk towards later rows if True, earlier if False.

    Returns:
        np.ndarray | None: One row in :data:`ROI_COLUMNS` order, or None.
    """
    op, order = (">", "ASC") if forward else ("<", "DESC")
    cursor = conn.execute(
        f"SELECT {', '.join(ROI_COLUMNS)} FROM {table} "
        f"WHERE rowid {op} ? ORDER BY rowid {order}",
        (rowid,),
    )
    for row in cursor:
        if not _inferred(row[-1]):
            return _normalise([row])[0]
    return None


def rows_at_rowids(
    conn: sqlite3.Connection, table: str, rowids: np.ndarray
) -> np.ndarray:
    """
    Return the rows at the given rowids (missing ones skipped), inferred as 0/1.

    Args:
        conn (sqlite3.Connection): Open connection.
        table (str): ROI table name.
        rowids (np.ndarray): Rowids to fetch.

    Returns:
        np.ndarray: ``(n, 8)`` array in :data:`ROI_COLUMNS` order.
    """
    marks = ",".join(str(int(r)) for r in rowids)
    rows = conn.execute(
        f"SELECT {', '.join(ROI_COLUMNS)} FROM {table} WHERE rowid IN ({marks})"
    ).fetchall()
    return _normalise(rows)
