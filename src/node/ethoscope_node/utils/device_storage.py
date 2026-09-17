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

The same listing answers a second question, asked before a run starts rather than
after it ends: does this device still have room? :func:`assess_free_space` reads the
``df`` line the device serves alongside its runs, compares it against the configured
gates, and phrases the result — including how much of it could be reclaimed, which is
only knowable from the classification above.
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

# The percentage of its data partition at which a device counts as short of space.
# Overridden by ``alerts.storage_start_warning_percent``.
#
# Deliberately not the same as ``alerts.storage_warning_threshold`` (80), which
# governs notifications: a message at 80% costs nothing, whereas a dialog in front
# of every start at 80% would be dismissed unread within a week — and 80% of a 32 GB
# card still leaves ~6 GB, ample for a tracking run.
DEFAULT_PERCENT_THRESHOLD = 90

# The percentage rule only fires when free space is also below this, so that a large
# disk does not cry wolf: 91% of a 1 TB volume is still 90 GB free, which is not a
# problem and must not be reported as one. The absolute rule below has no such
# qualifier. Overridden by ``alerts.storage_percent_warning_ceiling_gb``.
DEFAULT_PERCENT_CEILING_GB = 25

# Free space a device should have before each kind of run. Video recording writes
# about two orders of magnitude more per day than tracking, so the two are held to
# different bars. Overridden by ``alerts.min_free_gb_tracking`` / ``..._video``.
DEFAULT_MIN_FREE_GB = {"tracking": 2, "video": 10}

# Which device root each kind of run is written to.
ACTION_ROOTS = {"tracking": "results", "video": "videos"}

# Suffixes df uses in its human-readable form. P is included because df will print
# it; nothing here is that large.
_SIZE_UNITS = {
    "B": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
    "P": 1024**5,
}


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


def thresholds_for(action: str, alerts: dict | None = None) -> dict:
    """
    Resolve the gates for one kind of run from the node's alert configuration.

    Args:
        action (str): ``"tracking"`` or ``"video"``. Anything else is treated as
            tracking, which is the lower bar.
        alerts (dict | None): The configuration's ``alerts`` section, if any.

    Returns:
        dict: ``{"percent": int, "min_free_bytes": int}``.
    """
    alerts = alerts if isinstance(alerts, dict) else {}
    if action not in DEFAULT_MIN_FREE_GB:
        action = "tracking"

    percent = _number(alerts.get("storage_start_warning_percent"))
    if percent is None:
        percent = DEFAULT_PERCENT_THRESHOLD

    min_free_gb = _number(alerts.get(f"min_free_gb_{action}"))
    if min_free_gb is None:
        min_free_gb = DEFAULT_MIN_FREE_GB[action]

    ceiling_gb = _number(alerts.get("storage_percent_warning_ceiling_gb"))
    if ceiling_gb is None:
        ceiling_gb = DEFAULT_PERCENT_CEILING_GB

    return {
        "percent": int(percent),
        "min_free_bytes": int(min_free_gb * 1024**3),
        "percent_ceiling_bytes": int(ceiling_gb * 1024**3),
    }


def assess_free_space(
    disk: dict | None,
    totals: dict | None,
    action: str = "tracking",
    thresholds: dict | None = None,
    runs: list[dict] | None = None,
) -> dict:
    """
    Judge whether a device has room for a run, and phrase the answer.

    A figure we cannot read never raises the alarm. The caller is about to start an
    experiment, and a ``df`` line that failed to parse is not a reason to stand in
    their way — so every unknown resolves to "no warning".

    Args:
        disk (dict | None): The device's ``df`` line as served with its run listing:
            ``Size``, ``Used``, ``Avail``, ``Use%``, in df's human-readable form.
        totals (dict | None): :func:`summarise` output for the same listing.
        action (str): ``"tracking"`` or ``"video"``; picks which free-space bar
            applies.
        thresholds (dict | None): ``{"percent", "min_free_bytes"}``. Defaults for the
            action when omitted.
        runs (list[dict] | None): Classified runs, used only to quote the size of the
            most recent run of the same kind.

    Returns:
        dict: ``warn`` plus every figure behind it, and ``reasons``, the sentences to
        show the user.
    """
    disk = disk if isinstance(disk, dict) else {}
    totals = totals if isinstance(totals, dict) else {}
    thresholds = thresholds if isinstance(thresholds, dict) else thresholds_for(action)

    used_percent = _parse_percent(disk.get("Use%"))
    avail_bytes = _parse_df_size(disk.get("Avail"))

    # A full-looking percentage only counts when the space actually left is small
    # too; a figure we could not read cannot suppress it.
    ceiling = thresholds.get("percent_ceiling_bytes")
    roomy = ceiling is not None and avail_bytes is not None and avail_bytes >= ceiling

    triggered_by = []
    if used_percent is not None and used_percent >= thresholds["percent"] and not roomy:
        triggered_by.append("percent")
    if avail_bytes is not None and avail_bytes < thresholds["min_free_bytes"]:
        triggered_by.append("free_space")

    assessment = {
        "warn": bool(triggered_by),
        "action": action,
        "triggered_by": triggered_by,
        "used_percent": used_percent,
        "avail_bytes": avail_bytes,
        "used_bytes": _parse_df_size(disk.get("Used")),
        "size_bytes": _parse_df_size(disk.get("Size")),
        "reclaimable_bytes": int(_number(totals.get("reclaimable_bytes")) or 0),
        "backed_up_runs": int(_number(totals.get("backed_up_runs")) or 0),
        "pending_runs": int(_number(totals.get("pending_runs")) or 0),
        "last_run": _latest_run(runs, ACTION_ROOTS.get(action)),
        "thresholds": dict(thresholds),
        "reasons": [],
    }
    if assessment["warn"]:
        assessment["reasons"] = _space_reasons(assessment)
    return assessment


def _space_reasons(assessment: dict) -> list[str]:
    """The sentences shown to the user, the most concrete first."""
    reasons = []

    percent = assessment["used_percent"]
    avail = assessment["avail_bytes"]
    size = assessment["size_bytes"]
    if percent is not None and avail is not None and size:
        reasons.append(
            f"Disk {percent}% full — {_human(avail)} free of {_human(size)}."
        )
    elif avail is not None:
        reasons.append(f"Only {_human(avail)} of free space left.")
    elif percent is not None:
        reasons.append(f"Disk {percent}% full.")

    last_run = assessment["last_run"]
    if last_run:
        label = "recording" if assessment["action"] == "video" else "tracking"
        when = f" ({_run_day(last_run.get('date'))})" if last_run.get("date") else ""
        reasons.append(
            f"Its most recent {label} run used "
            f"{_human(last_run['size_bytes'])}{when}."
        )

    if assessment["reclaimable_bytes"] > 0:
        backed_up = assessment["backed_up_runs"]
        runs_are = "run is" if backed_up == 1 else "runs are"
        reasons.append(
            f"{_human(assessment['reclaimable_bytes'])} can be freed: "
            f"{backed_up} {runs_are} already backed up to the node."
        )
    elif assessment["pending_runs"]:
        pending = assessment["pending_runs"]
        if pending == 1:
            reasons.append(
                "Its one run is not backed up yet, so there is nothing here that "
                "is safe to delete."
            )
        else:
            reasons.append(
                f"None of its {pending} runs are backed up yet, so there is "
                "nothing here that is safe to delete."
            )
    else:
        # Reason: no runs at all on a full device means the space went somewhere
        # else entirely — a leftover image file, an unrotated log — and the
        # Free up space tool will not find it.
        reasons.append(
            "It holds no runs, so the space is taken by something other than "
            "experimental data."
        )

    return reasons


def _latest_run(runs: list[dict] | None, root: str | None) -> dict | None:
    """
    The newest run under one device root, for quoting a realistic size.

    :func:`~ethoscope.utils.storage.list_runs` sorts oldest first by the date-time
    component of the path, so take the last one rather than re-parsing a date string
    we did not build.
    """
    if not root:
        return None

    candidates = [
        run for run in (runs or ()) if isinstance(run, dict) and run.get("root") == root
    ]
    if not candidates:
        return None

    newest = candidates[-1]
    size = int(_number(newest.get("size_bytes")) or 0)
    if size <= 0:
        return None
    return {
        "date": newest.get("date"),
        "size_bytes": size,
        "kind": newest.get("kind") or root,
    }


def _run_day(date: object) -> str:
    """The day out of a run's ``YYYY-MM-DD_HH-MM-SS`` directory name."""
    return str(date).split("_", 1)[0]


def _number(value: object) -> float | None:
    """A float for anything numeric-looking, None otherwise (bools are not numbers)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    # Reason: a Pi with a non-C LC_NUMERIC prints "9,2G". Accept a comma only where
    # df would put a decimal point — one or two digits, nothing after. A grouped
    # "1,024" must stay unreadable rather than become 1.024, which would read as an
    # all-but-empty disk and raise a false alarm.
    head, comma, tail = text.partition(",")
    if comma and "." not in text:
        if head.lstrip("-").isdigit() and tail.isdigit() and len(tail) <= 2:
            text = f"{head}.{tail}"
    try:
        return float(text)
    except ValueError:
        return None


def _parse_percent(value: object) -> int | None:
    """
    Read df's ``Use%`` ("82%", "82", 82) as a whole percentage.

    No upper bound is imposed: a filesystem reporting over 100% is exactly when the
    user most needs to hear about it.
    """
    if value is None or isinstance(value, bool):
        return None
    number = _number(str(value).strip().rstrip("%"))
    if number is None or number < 0:
        return None
    return int(round(number))


def _parse_df_size(value: object) -> int | None:
    """
    Read one df size figure as bytes.

    Handles the human-readable form df serves the device listing ("5.0G", "440K",
    "29G"), an explicit "B", and a bare byte count. Returns None for anything else,
    which the caller treats as "unknown" rather than as zero — the device-side
    equivalent (:func:`ethoscope.utils.pi.check_disk_space`) reads a T suffix as 0,
    and 0 free bytes is an alarm nobody asked for.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None

    text = str(value).strip()
    if text[-1:].upper() == "B":  # "512B", "29GB"
        text = text[:-1]
    if text[-1:].upper() == "I":  # "29GiB" -> "29G"
        text = text[:-1]
    if not text:
        return None

    unit = _SIZE_UNITS.get(text[-1].upper())
    if unit is not None:
        text = text[:-1]
    else:
        unit = 1

    number = _number(text)
    if number is None or number < 0:
        return None
    return int(number * unit)


def _human(size: float) -> str:
    """Format a byte count for a message shown to the user."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
