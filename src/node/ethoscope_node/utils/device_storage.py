"""
Deciding which device runs are safe to delete.

A run directory on an ethoscope may be removed once every file it holds is on the
node. Nothing records that fact: the node keeps no per-file backup ledger, so the
only evidence is the rsync copy itself. This module applies rsync's own criterion —
a file is copied when the destination has the same size and mtime — to the listing
the device serves at ``/data/runs/<id>``, and explains in words why a run is not yet
deletable.

Two details do not follow from that rule alone:

* SQLite runs in WAL mode and rsync is told to skip ``.db-wal``/``.db-shm``/
  ``.db-journal``. A missing sidecar is therefore expected, but a **non-empty**
  write-ahead log means committed rows that the copied ``.db`` does not contain, so
  the run is held back until a checkpoint folds them in.
* ``accessories/h264_to_mp4.py --purge`` deletes the node's ``.h264`` chunks once it
  has merged them into an ``.mp4``. A chunk missing for that reason is still safe, so
  it is accepted when the node's copy of the run holds a settled ``.mp4`` — settled
  meaning no ``.tmp`` sibling and old enough that ffmpeg is no longer writing it.

Checksums are deliberately not used: the backup does not use them either, and hashing
multi-gigabyte files off an SD card would take minutes per run for no practical gain,
since every writer here changes a file's size or mtime.
"""

import os
import time

# rsync's --modify-window: filesystems disagree about mtime resolution, so compare
# with a tolerance rather than for equality.
MTIME_TOLERANCE_S = 2

# How long an .mp4 must have been untouched before we believe the conversion that
# replaced the node's .h264 chunks has finished.
MP4_SETTLE_S = 600

# Sidecars rsync is told to skip; they never need a counterpart on the node.
WAL_SUFFIXES = (".db-wal", ".db-shm", ".db-journal")

# How many unverified files to name in the reason shown to the user.
MAX_REPORTED_MISSING = 5


def _node_run_dir(run: dict, node_dirs: dict[str, str]) -> str | None:
    """Return the node's directory mirroring this run, or None for an unknown root."""
    root = node_dirs.get(run.get("root"))
    if not root:
        return None
    return os.path.join(root, run.get("rel_dir", ""))


def _has_settled_mp4(node_run_dir: str, listdir, stat, now: float) -> bool:
    """True when the node's copy of the run holds a finished merged video."""
    try:
        entries = listdir(node_run_dir)
    except OSError:
        return False

    if any(e.endswith(".tmp") for e in entries):
        return False

    for entry in entries:
        if not entry.endswith(".mp4"):
            continue
        try:
            st = stat(os.path.join(node_run_dir, entry))
        except OSError:
            continue
        if now - st.st_mtime >= MP4_SETTLE_S:
            return True
    return False


def classify_run(
    run: dict,
    node_dirs: dict[str, str],
    stat=os.stat,
    listdir=os.listdir,
    now=None,
) -> dict:
    """
    Decide whether a device run is fully backed up on the node.

    Args:
        run (dict): One entry of the device's ``/data/runs`` listing.
        node_dirs (dict[str, str]): Mapping of root key (``"results"``, ``"videos"``)
            to the node directory rsync mirrors it into.
        stat: ``os.stat``-alike, injectable for testing.
        listdir: ``os.listdir``-alike, injectable for testing.
        now (float | None): Current time, defaults to ``time.time()``.

    Returns:
        dict: A copy of ``run`` with ``backed_up`` (bool), ``reason`` (str, shown to
        the user), ``missing`` (up to five unverified file names), ``date`` (the run's
        date-time component) and ``kind`` (``"results"`` or ``"videos"``).
    """
    now = time.time() if now is None else now
    result = dict(run)
    rel_dir = run.get("rel_dir", "")
    result["date"] = rel_dir.split("/")[-1] if rel_dir else ""
    result["kind"] = run.get("root", "")
    result["missing"] = []

    node_run_dir = _node_run_dir(run, node_dirs)
    if node_run_dir is None:
        result["backed_up"] = False
        result["reason"] = "No backup folder configured for this kind of data"
        return result

    missing: list[str] = []
    mp4_checked = False
    mp4_present = False

    for entry in run.get("files", []):
        name = entry.get("name", "")

        if name.endswith(WAL_SUFFIXES):
            # Reason: rsync never copies these, so absence proves nothing — but a
            # non-empty WAL holds committed rows the copied .db is missing.
            if name.endswith(".db-wal") and entry.get("size", 0) > 0:
                result["backed_up"] = False
                result["reason"] = (
                    f"Un-checkpointed write-ahead log ({_human(entry['size'])}): "
                    "those rows are not on the node yet"
                )
                return result
            continue

        node_file = os.path.join(node_run_dir, name)
        try:
            st = stat(node_file)
        except OSError:
            if name.endswith(".h264"):
                if not mp4_checked:
                    mp4_present = _has_settled_mp4(node_run_dir, listdir, stat, now)
                    mp4_checked = True
                if mp4_present:
                    continue
            missing.append(name)
            continue

        if st.st_size != entry.get("size"):
            missing.append(name)
        elif abs(st.st_mtime - entry.get("mtime", 0)) > MTIME_TOLERANCE_S:
            missing.append(name)

    if missing:
        result["backed_up"] = False
        result["missing"] = sorted(missing)[:MAX_REPORTED_MISSING]
        result["reason"] = (
            f"Not backed up yet: {len(missing)} file(s) missing on the node. "
            "The backup service runs every 5 minutes."
        )
    else:
        result["backed_up"] = True
        result["reason"] = "Backed up"

    return result


def summarise(runs: list[dict]) -> dict:
    """
    Total up a classified listing.

    Args:
        runs (list[dict]): Runs as returned by :func:`classify_run`.

    Returns:
        dict: ``{"reclaimable_bytes", "backed_up_runs", "pending_runs", "total_bytes"}``.
    """
    backed_up = [r for r in runs if r.get("backed_up")]
    return {
        "reclaimable_bytes": sum(r.get("size_bytes", 0) for r in backed_up),
        "backed_up_runs": len(backed_up),
        "pending_runs": len(runs) - len(backed_up),
        "total_bytes": sum(r.get("size_bytes", 0) for r in runs),
    }


def _human(size: float) -> str:
    """Format a byte count for a message shown to the user."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
