"""
Device data storage helpers.

Tracking and recording data live in *run directories*, one per experiment::

    /ethoscope_data/results/<machine_id>/<machine_name>/<YYYY-MM-DD_HH-MM-SS>/...
    /ethoscope_data/videos/<machine_id>/<machine_name>/<YYYY-MM-DD_HH-MM-SS>/...

This module lists those runs with the size and mtime of every file they hold, and
removes the ones the node asks for. Deciding *whether* a run may go is the node's
job: it owns the rsync copies, so it is the only party that can tell a backed-up run
from one that is not. The device's part is to describe its files faithfully and to
refuse anything that is not a well-formed run directory under one of its data roots.

Only files at run depth or deeper are ever reported as runs; anything shallower (a
stray ``videos/index.html``, say) is counted under ``other`` and can never be
removed through this module.
"""

import os
import re
import shutil
import stat
from collections.abc import Iterable

# <machine_id>/<machine_name>/<date_time> — the three components under a data root
# that make a run directory.
RUN_DEPTH = 3
RUN_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
RUN_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")


def list_runs(roots: dict[str, str]) -> dict:
    """
    Describe every run directory under the given data roots.

    Args:
        roots (dict[str, str]): Mapping of root key (``"results"``, ``"videos"``) to
            the absolute directory holding that kind of data. Missing directories
            are skipped.

    Returns:
        dict: ``{"runs": [...], "other": {"files": n, "size_bytes": n}}``. Each run is
        ``{"root", "rel_dir", "path", "size_bytes", "files": [{"name", "size",
        "mtime"}]}`` where ``rel_dir`` is the run's path relative to its root and
        every ``name`` is relative to the run directory. Runs are sorted by their
        date-time component, oldest first.
    """
    runs: dict[str, dict] = {}
    other_files = 0
    other_bytes = 0

    for key, root in roots.items():
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            continue

        for dirpath, _dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            parts = [] if rel_dir == os.curdir else rel_dir.split(os.sep)

            for filename in filenames:
                full = os.path.join(dirpath, filename)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                # Reason: only regular files are data; a symlink's size says nothing
                # about what it points at, so it neither counts nor gets reported.
                if not stat.S_ISREG(st.st_mode):
                    continue

                if len(parts) < RUN_DEPTH:
                    other_files += 1
                    other_bytes += st.st_size
                    continue

                run_rel = os.sep.join(parts[:RUN_DEPTH])
                run_path = os.path.join(root, run_rel)
                run = runs.setdefault(
                    run_path,
                    {
                        "root": key,
                        "rel_dir": run_rel,
                        "path": run_path,
                        "size_bytes": 0,
                        "files": [],
                    },
                )
                run["files"].append(
                    {
                        "name": os.path.relpath(full, run_path),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
                run["size_bytes"] += st.st_size

    ordered = sorted(
        runs.values(), key=lambda r: (r["rel_dir"].split(os.sep)[-1], r["root"])
    )
    return {
        "runs": ordered,
        "other": {"files": other_files, "size_bytes": other_bytes},
    }


def validate_run_dir(path: str, roots: dict[str, str]) -> tuple[str, str]:
    """
    Check that ``path`` names a run directory under one of the data roots.

    Symlinks are resolved first, so a link pointing outside the roots is rejected
    along with relative paths, ``..`` tricks, and paths at the wrong depth.

    Args:
        path (str): Absolute path of the directory to validate.
        roots (dict[str, str]): Same mapping as for :func:`list_runs`.

    Returns:
        tuple[str, str]: ``(root_key, resolved_path)``.

    Raises:
        ValueError: If the path is not a well-formed run directory under a root.
    """
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError(f"not an absolute path: {path!r}")

    real = os.path.realpath(path)

    for key, root in roots.items():
        root_real = os.path.realpath(root)
        rel = os.path.relpath(real, root_real)
        if rel == os.curdir or rel.startswith(os.pardir) or os.path.isabs(rel):
            continue

        parts = rel.split(os.sep)
        if len(parts) != RUN_DEPTH:
            raise ValueError(
                f"not a run directory (expected {RUN_DEPTH} levels): {path}"
            )
        if not all(RUN_COMPONENT_RE.match(p) for p in parts):
            raise ValueError(f"unexpected characters in run path: {path}")
        if not RUN_DATETIME_RE.match(parts[-1]):
            raise ValueError(f"run directory is not named after a date-time: {path}")
        return key, real

    raise ValueError(f"outside the device data folders: {path}")


def _tree_size(path: str) -> int:
    """Sum the sizes of the regular files below ``path``."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for filename in filenames:
            try:
                st = os.lstat(os.path.join(dirpath, filename))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                total += st.st_size
    return total


def remove_runs(
    paths: Iterable[str],
    roots: dict[str, str],
    protected: Iterable[str | None] = (),
) -> dict:
    """
    Delete run directories, one at a time, reporting each outcome.

    Every path is validated with :func:`validate_run_dir`; a run that holds one of
    the ``protected`` files (the database currently being written, typically) is
    refused. A failure on one run never stops the others.

    Args:
        paths (Iterable[str]): Absolute run directories to delete.
        roots (dict[str, str]): Same mapping as for :func:`list_runs`.
        protected (Iterable[str | None]): Files that must survive; ``None`` entries
            are ignored so callers can pass fields that may be unset.

    Returns:
        dict: ``{"removed": [{"path", "freed_bytes"}], "failed": [{"path", "error"}],
        "freed_bytes": n}``.
    """
    protected_real = {os.path.realpath(p) for p in protected if p}
    removed: list[dict] = []
    failed: list[dict] = []
    freed = 0

    for path in paths:
        try:
            _, real = validate_run_dir(path, roots)
            for keep in protected_real:
                if keep == real or keep.startswith(real + os.sep):
                    raise ValueError("run holds the database currently in use")
            if not os.path.isdir(real):
                raise FileNotFoundError("no such run directory")

            size = _tree_size(real)
            shutil.rmtree(real)
            removed.append({"path": path, "freed_bytes": size})
            freed += size
        except Exception as e:
            failed.append({"path": path, "error": str(e)})

    return {"removed": removed, "failed": failed, "freed_bytes": freed}
