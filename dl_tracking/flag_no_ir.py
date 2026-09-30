"""Flag runs whose night snapshots are far darker than their day snapshots.

Giorgio reported (2026-09-30) that a camera-settings bug once kept IR mode from
being used, leaving very dark images. Under working IR the backlight keeps night
frames nearly as bright as day frames; a run whose darkest census luminance sample
is below ``RATIO_MAX`` of its brightest has dark nights. The census holds four
samples per run, so a run whose samples all fell in daylight is missed.

The flag is the image signature, not a date range: the repository's history does
not pin the bug. The strongest cluster in the data is commits 028bfb56..e87e6c53
(Sept 2023 - March 2024; about half of those runs, on 26 machines), gone from
aaa462e6 (June 2024). Each flagged run is written with its commit and commit date,
so that the period can be confirmed by eye.

Usage::

    python -m dl_tracking.flag_no_ir --census /mnt/cache/dl_tracking/census.parquet \\
        --out /mnt/cache/dl_tracking/flagged_no_ir_runs.csv
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404 - fixed git command on hashes read from our own DBs
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

from .select_runs import _seq

RATIO_MAX = 0.4
REPO = Path(__file__).resolve().parents[1]


@cache
def commit_date(version: str | None) -> str | None:
    """
    Return the date of a recording's software commit, if this clone has it.

    Args:
        version (str | None): METADATA ``version`` (a commit hash).

    Returns:
        str | None: ``YYYY-MM-DD``, or None for a missing, malformed or unknown hash.
    """
    if not isinstance(version, str) or not version.isalnum():
        return None
    res = subprocess.run(  # nosec B603 B607 - no shell; the hash is alphanumeric
        [
            "git",
            "-C",
            str(REPO),
            "show",
            "-s",
            "--format=%ad",
            "--date=short",
            f"{version}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return (res.stdout.strip() or None) if res.returncode == 0 else None


def luminance(census: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise each run's snapshot luminance samples (1/4-scale means).

    Args:
        census (pd.DataFrame): The census table.

    Returns:
        pd.DataFrame: ``lum_min``, ``lum_median``, ``lum_max`` and
        ``night_day_ratio`` (min / max); NaN without samples.
    """
    stats = census.snap_lum.map(
        lambda v: (
            (np.min(s), np.median(s), np.max(s)) if (s := _seq(v)) else (np.nan,) * 3
        )
    )
    out = pd.DataFrame(
        stats.tolist(), index=census.index, columns=["lum_min", "lum_median", "lum_max"]
    )
    out["night_day_ratio"] = out.lum_min / out.lum_max
    return out


def flag(census: pd.DataFrame, ratio_max: float = RATIO_MAX) -> pd.DataFrame:
    """
    Return the runs with dark nights, with their commit and its date.

    Args:
        census (pd.DataFrame): The census table.
        ratio_max (float): Flag runs whose night/day luminance ratio is below this.

    Returns:
        pd.DataFrame: Flagged runs, sorted by date and machine.
    """
    df = census[census.error.isna()].join(luminance(census))
    df = df[df.night_day_ratio < ratio_max].copy()
    df["commit_date"] = df.version.map(commit_date)
    cols = [
        "machine_name",
        "machine_id",
        "run_dt",
        "user",
        "version",
        "commit_date",
        "lum_min",
        "lum_median",
        "lum_max",
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
    ap.add_argument("--ratio-max", type=float, default=RATIO_MAX)
    args = ap.parse_args()
    flagged = flag(pd.read_parquet(args.census), args.ratio_max)
    flagged.round(3).to_csv(args.out, index=False)
    print(
        f"{len(flagged)} runs on {flagged.machine_name.nunique()} machines -> {args.out}"
    )
    print(flagged.run_dt.str[:4].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
