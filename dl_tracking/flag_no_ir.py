"""Flag runs recorded while picamera2 ran NoIR cameras on the default colour tuning.

Giorgio (2026-09-30): the camera problem started when the repository moved to
picamera2. The history bounds it. ``370c9491`` (2024-02-02) moved to picamera2,
which runs libcamera's default *colour* tuning on NoIR sensors. NoIR tuning became
an option defaulting to off (``faf84b46``), became unconditional (``217084d9``), and
was actually applied only from ``766de9ab`` (2026-08-26), whose message measures the
effect: frames about three times too dark under IR.

A run is affected when its software commit (METADATA ``version``) lies in
[370c9491, 766de9ab) **and** the device ran picamera2. The device loads legacy
``picamera`` whenever it imports, so the OS image decides: Arch Linux ARM kernels
(``*-rpi-ARCH``) kept legacy picamera; Raspberry Pi OS kernels (``+rpt``, ``-v8``)
have only picamera2. The kernel is read from ``hardware_info`` in METADATA.

Brightness alone does not find these runs: auto-exposure mostly compensated (window
picamera2 runs have a median night luminance of 78 against 89 for legacy picamera),
so the dark-night ratio is reported alongside, not used to flag.

Usage::

    python -m dl_tracking.flag_no_ir --census /mnt/cache/dl_tracking/census.parquet \\
        --out /mnt/cache/dl_tracking/flagged_no_ir_runs.csv
"""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404 - fixed git commands on hashes read from our own DBs
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import db_io
from .select_runs import _seq

WINDOW_START = "370c9491"  # 2024-02-02: picamera2, default colour tuning
WINDOW_END = "766de9ab"  # 2026-08-26: NoIR tuning actually applied
REPO = Path(__file__).resolve().parents[1]
_KERNEL_RE = re.compile(r"'kernel': '([^']+)'")


def _git(*args: str) -> subprocess.CompletedProcess:
    """Run a read-only git command in this repository."""
    return subprocess.run(  # nosec B603 B607 - no shell; callers pass validated hashes
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=False
    )


@cache
def code_window(version: str | None) -> str:
    """
    Place a recording's software commit relative to the affected window.

    Args:
        version (str | None): METADATA ``version`` (a commit hash).

    Returns:
        str: ``before``, ``window``, ``fixed`` or ``unknown`` (no hash, or one this
        clone does not have).
    """
    if not isinstance(version, str) or not version.isalnum():
        return "unknown"
    if _git("cat-file", "-e", f"{version}^{{commit}}").returncode:
        return "unknown"
    if _git("merge-base", "--is-ancestor", WINDOW_END, version).returncode == 0:
        return "fixed"
    if _git("merge-base", "--is-ancestor", WINDOW_START, version).returncode == 0:
        return "window"
    return "before"


def camera_stack(kernel: str | None) -> str:
    """
    Tell which camera library a device used, from its kernel string.

    Args:
        kernel (str | None): ``hardware_info['kernel']``.

    Returns:
        str: ``picamera`` (Arch Linux ARM image), ``picamera2`` (Raspberry Pi OS)
        or ``unknown``.
    """
    if not isinstance(kernel, str):
        return "unknown"
    if "rpi-ARCH" in kernel:
        return "picamera"
    if "+rpt" in kernel or kernel.endswith(("-v8", "-2712")):
        return "picamera2"
    return "unknown"


def read_kernel(path: str) -> str | None:
    """
    Read the kernel string from a run's METADATA ``hardware_info``.

    Args:
        path (str): The DB.

    Returns:
        str | None: The kernel, or None if not recorded or unreadable.
    """
    try:
        with db_io.connect(Path(path)) as conn:
            hw = db_io.read_metadata(conn).get("hardware_info", "")
    except Exception:  # noqa: BLE001 - a flag pass must survive any bad file
        return None
    match = _KERNEL_RE.search(hw)
    return match.group(1) if match else None


def night_day_ratio(census: pd.DataFrame) -> pd.Series:
    """
    Darkest over brightest census luminance sample, per run (NaN without samples).

    Args:
        census (pd.DataFrame): The census table.

    Returns:
        pd.Series: The ratio.
    """
    return census.snap_lum.map(
        lambda v: (
            float(np.min(s) / np.max(s)) if (s := _seq(v)) and np.max(s) > 0 else np.nan
        )
    )


def flag(census: pd.DataFrame, kernel_of=read_kernel) -> pd.DataFrame:
    """
    Return the runs recorded with window code on picamera2 (or an unknown stack).

    Args:
        census (pd.DataFrame): The census table.
        kernel_of: Function from a DB path to its kernel string (injectable for tests).

    Returns:
        pd.DataFrame: One row per run with ``certainty`` = ``picamera2`` (affected)
        or ``stack unknown`` (window code, no kernel recorded).
    """
    df = census[census.error.isna()].copy()
    df["code_window"] = df.version.map(code_window)
    df = df[df.code_window == "window"].copy()
    df["kernel"] = df.path.map(kernel_of)
    df["camera_stack"] = df.kernel.map(camera_stack)
    df = df[df.camera_stack != "picamera"].copy()
    df["certainty"] = np.where(
        df.camera_stack == "picamera2", "picamera2", "stack unknown"
    )
    df["night_day_ratio"] = night_day_ratio(df).round(3)
    cols = [
        "machine_name",
        "machine_id",
        "run_dt",
        "user",
        "version",
        "kernel",
        "certainty",
        "night_day_ratio",
        "n_snap",
        "path",
    ]
    return df.sort_values(["run_dt", "machine_name"])[cols]


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--census", type=Path, default=Path("/mnt/cache/dl_tracking/census.parquet")
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("/mnt/cache/dl_tracking/flagged_no_ir_runs.csv"),
    )
    args = ap.parse_args()
    flagged = flag(pd.read_parquet(args.census))
    flagged.to_csv(args.out, index=False)
    print(
        f"{len(flagged)} runs on {flagged.machine_name.nunique()} machines -> {args.out}"
    )
    print(
        flagged.groupby("certainty")
        .agg(
            runs=("path", "size"),
            machines=("machine_name", "nunique"),
            first=("run_dt", "min"),
            last=("run_dt", "max"),
        )
        .to_string()
    )


if __name__ == "__main__":
    main()
