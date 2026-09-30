"""Build the queue of tube crops that need a human.

Round 1 holds two kinds of item:

- ``never_detected``: tubes the tracker (almost) never saw during a whole run,
  shown at ``N_TIMES`` times. To the tracker an empty tube and a fly dead from the
  start look the same; a person tells them apart at a glance.
- ``audit_confident`` / ``audit_gapfill``: a small random sample of automatic
  labels, shown with their marker, to measure how often they are wrong.

Usage::

    python -m dl_tracking.review.queue --pack /mnt/cache/dl_tracking/data/pack \\
        --runs /mnt/cache/dl_tracking/runs.parquet --out /mnt/cache/dl_tracking/review
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .. import dataset as D

N_TIMES = 4
AUDIT_BLOCK = 5
COLUMNS = [
    "item_id",
    "group",
    "kind",
    "sid",
    "run_id",
    "roi_idx",
    "t",
    "roi_x",
    "roi_y",
    "roi_w",
    "roi_h",
    "px",
    "py",
]


def never_detected_items(
    labels: pd.DataFrame, max_tubes: int, seed: int
) -> pd.DataFrame:
    """
    One group per never-detected tube: ``N_TIMES`` snapshots spread over its run.

    Args:
        labels (pd.DataFrame): Packed labels.
        max_tubes (int): Cap on tubes (sampled at random, one per run first).
        seed (int): Sampling seed.

    Returns:
        pd.DataFrame: Queue rows without a proposal.
    """
    nd = labels[labels.status == "never_detected"]
    tubes = (
        nd[["run_id", "roi_idx"]].drop_duplicates().sample(frac=1.0, random_state=seed)
    )
    # Reason: spread the budget over runs before taking a second tube from any run.
    tubes["rank"] = tubes.groupby("run_id").cumcount()
    tubes = tubes.sort_values("rank", kind="stable").head(max_tubes)
    out = []
    for rid, roi in tubes[["run_id", "roi_idx"]].itertuples(index=False):
        rows = nd[(nd.run_id == rid) & (nd.roi_idx == roi)].sort_values("t")
        pick = rows.iloc[np.unique(np.linspace(0, len(rows) - 1, N_TIMES).astype(int))]
        out.append(
            pick.assign(
                group=f"nd:{rid}:{roi}", kind="never_detected", px=np.nan, py=np.nan
            )
        )
    return pd.concat(out) if out else pd.DataFrame(columns=COLUMNS)


def audit_items(rows: pd.DataFrame, status: str, n: int, seed: int) -> pd.DataFrame:
    """
    A random sample of automatic labels, one crop per group, with its marker.

    Args:
        rows (pd.DataFrame): Output of :func:`dataset.training_rows`.
        status (str): ``confident`` or ``gapfill``.
        n (int): Sample size.
        seed (int): Sampling seed.

    Returns:
        pd.DataFrame: Queue rows with the label as proposal.
    """
    pick = rows[rows.status == status]
    pick = pick.sample(min(n, len(pick)), random_state=seed)
    # Reason: audits are independent crops, so show them AUDIT_BLOCK to a card.
    block = np.arange(len(pick)) // AUDIT_BLOCK
    return pick.assign(
        kind=f"audit_{status}",
        px=pick.x,
        py=pick.y,
        group=[f"a:{status}:{b}" for b in block],
    )


def build(
    labels: pd.DataFrame,
    runs: pd.DataFrame | None,
    max_tubes: int = 300,
    n_confident: int = 150,
    n_gapfill: int = 100,
    seed: int = 0,
) -> pd.DataFrame:
    """
    Assemble round 1: never-detected tubes first, then the audits, interleaved.

    Args:
        labels (pd.DataFrame): Packed labels.
        runs (pd.DataFrame | None): Runs table; if given, only its runs are used.
        max_tubes (int): Never-detected tubes to review.
        n_confident (int): Confident labels to audit.
        n_gapfill (int): Gap-filled labels to audit.
        seed (int): Sampling seed.

    Returns:
        pd.DataFrame: The queue, in review order.
    """
    if runs is not None:
        labels = labels[labels.run_id.isin(runs.machine_id + "_" + runs.run_dt)]
    labels = labels[D.fits_canvas(labels)]
    rows = D.training_rows(labels)
    parts = [
        never_detected_items(labels, max_tubes, seed),
        audit_items(rows, "confident", n_confident, seed),
        audit_items(rows, "gapfill", n_gapfill, seed),
    ]
    q = pd.concat(parts, ignore_index=True)
    q["item_id"] = (
        q.run_id + ":" + q.roi_idx.astype(str) + ":" + q.sid.astype(int).astype(str)
    )
    return q[COLUMNS]


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", type=Path, required=True)
    ap.add_argument("--runs", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-tubes", type=int, default=300)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    runs = pd.read_parquet(args.runs) if args.runs else None
    q = build(pd.read_parquet(args.pack / "labels.parquet"), runs, args.max_tubes)
    q.to_parquet(args.out / "queue.parquet")
    print(q.kind.value_counts().to_string())


if __name__ == "__main__":
    main()
