"""Choose the runs to extract and assign each to a train / val / test split.

Splits are by machine, never by frame. Machine ids are not unique to a device
(cloned SD cards share one) and devices get renamed, so a split group is a
connected component of the graph joining every machine id to every name it was
recorded under. No id and no name can then appear in two splits.

Usage::

    python -m dl_tracking.select_runs --census /mnt/cache/dl_tracking/census.parquet \\
        --out /mnt/cache/dl_tracking/runs.parquet --per-group-year 3
"""

from __future__ import annotations

import argparse
import logging
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

MIN_SNAPSHOTS = 50
MIN_TUBE_ASPECT = 5.0  # ROI width / height; circular wells and arenas are ~1
FRAME_SHAPE = [960, 1280]
SPLIT_FRACTIONS = {"test": 0.15, "val": 0.10}  # the rest is train
# Machines behind the video test sets: always test, never train.
VIDEO_TEST_NAMES = {"ETHOSCOPE_012", "ETHOSCOPE_044"}


def split_groups(ids: pd.Series, names: pd.Series) -> pd.Series:
    """
    Label each row with the connected component of its machine id and name.

    Args:
        ids (pd.Series): Machine ids.
        names (pd.Series): Machine names, aligned with ``ids``.

    Returns:
        pd.Series: A group label per row (the component's smallest node).
    """
    parent: dict[str, str] = {}

    def find(a: str) -> str:
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, n in zip(ids, names, strict=True):
        union(f"id:{i}", f"name:{n}")
    return pd.Series([find(f"id:{i}") for i in ids], index=ids.index)


def _seq(value) -> list:
    """
    Return a census list field as a list; failed DBs store NaN there instead.

    Args:
        value: The field (a list, a numpy array after parquet, or NaN/None).

    Returns:
        list: The items, or an empty list.
    """
    return list(value) if isinstance(value, list | tuple | np.ndarray) else []


def usable(census: pd.DataFrame) -> pd.Series:
    """
    Tell which census rows are tube-layout runs worth extracting.

    Args:
        census (pd.DataFrame): The census table.

    Returns:
        pd.Series: Boolean mask.
    """

    def aspect(m) -> float:
        rois = _seq(m)
        return float(np.median([r[3] / max(r[4], 1) for r in rois])) if rois else 0.0

    shape = census.snap_shape.map(lambda s: _seq(s)[:2] == FRAME_SHAPE)
    return (
        census.error.isna()
        # Reason: non-monotonic tables hold the run twice (a 2022 backup bug); the
        # rowid bisection would return rows from the wrong copy.
        & (census.monotonic == 1)
        & (census.n_snap >= MIN_SNAPSHOTS)
        & (census.roi_map.map(aspect) >= MIN_TUBE_ASPECT)
        & shape
        & census.tracker.isin(["AdaptiveBGModel"])
    )


def assign_splits(groups: pd.Series, names: pd.Series, seed: int = 0) -> pd.Series:
    """
    Assign whole groups to splits, filling test and val to their share of runs.

    Args:
        groups (pd.Series): Group label per run.
        names (pd.Series): Machine name per run (to pin the video-test machines).
        seed (int): Shuffle seed.

    Returns:
        pd.Series: ``train``, ``val`` or ``test`` per run.
    """
    pinned = set(groups[names.isin(VIDEO_TEST_NAMES)])
    sizes = groups.value_counts()
    order = sorted(sizes.index, key=lambda g: zlib.crc32(f"{seed}:{g}".encode()))
    split: dict[str, str] = dict.fromkeys(pinned, "test")
    target = {k: v * len(groups) for k, v in SPLIT_FRACTIONS.items()}
    filled = {"test": sum(sizes[g] for g in pinned), "val": 0}
    for g in order:
        if g in split:
            continue
        for name in ("test", "val"):
            if filled[name] + sizes[g] <= target[name]:
                split[g] = name
                filled[name] += sizes[g]
                break
        else:
            split[g] = "train"
    return groups.map(split)


def select(census: pd.DataFrame, per_group_year: int, seed: int = 0) -> pd.DataFrame:
    """
    Keep usable runs, cap them per (group, year) for diversity, and assign splits.

    Groups and splits are computed on the whole census before capping, so the
    assignment of a machine does not depend on how many of its runs are kept.

    Args:
        census (pd.DataFrame): The census table.
        per_group_year (int): Maximum runs kept per (group, year).
        seed (int): Sampling and split seed.

    Returns:
        pd.DataFrame: The selected census rows plus ``group``, ``year``, ``split``.
    """
    df = census.copy()
    df["group"] = split_groups(df.machine_id, df.machine_name)
    df["year"] = df.run_dt.str[:4].astype(int)
    df["split"] = assign_splits(df.group, df.machine_name, seed)
    df = df[usable(df)]
    return (
        df.sample(frac=1.0, random_state=seed)
        .groupby(["group", "year"], group_keys=False)
        .head(per_group_year)
        .sort_values("path")
    )


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--census", type=Path, default=Path("/mnt/cache/dl_tracking/census.parquet")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("/mnt/cache/dl_tracking/runs.parquet")
    )
    parser.add_argument("--per-group-year", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    runs = select(pd.read_parquet(args.census), args.per_group_year, args.seed)
    runs.to_parquet(args.out)
    logging.info("%d runs, %d groups", len(runs), runs.group.nunique())
    logging.info("by split:\n%s", runs.split.value_counts().to_string())
    logging.info("by year:\n%s", runs.year.value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
