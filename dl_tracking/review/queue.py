"""Build the queue of tube crops that need a human.

Round 1 holds two kinds of item:

- ``never_detected``: tubes the tracker (almost) never saw during a whole run,
  shown at ``N_TIMES`` times. To the tracker an empty tube and a fly dead from the
  start look the same; a person tells them apart at a glance.
- ``audit_confident`` / ``audit_gapfill``: a small random sample of automatic
  labels, shown with their marker, to measure how often they are wrong.

Round 2 (``--round2``, appended after round 1) holds crops AdaptiveBGModel missed,
as a trained locator sees them: the uncertain ones, and small audits of its
confident calls either way (:func:`model_items`).

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
UNSURE = (0.15, 0.85)  # locator presence band that round 2 asks a person about
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
    tubes = nd[["run_id", "roi_idx"]].drop_duplicates()
    picked = _tube_strips(nd, _spread_over_runs(tubes, max_tubes, seed))
    return (
        picked.assign(
            group="nd:" + picked.run_id + ":" + picked.roi_idx.astype(str),
            kind="never_detected",
            px=np.nan,
            py=np.nan,
        )
        if len(picked)
        else pd.DataFrame(columns=COLUMNS)
    )


def _spread_over_runs(tubes: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """
    Take ``n`` tubes at random, one per run before a second from any run.

    Args:
        tubes (pd.DataFrame): Candidate ``run_id``, ``roi_idx`` pairs.
        n (int): How many to take.
        seed (int): Sampling seed.

    Returns:
        pd.DataFrame: The chosen pairs.
    """
    tubes = tubes.sample(frac=1.0, random_state=seed)
    tubes = tubes.assign(rank=tubes.groupby("run_id").cumcount())
    return tubes.sort_values("rank", kind="stable").head(n)[["run_id", "roi_idx"]]


def _tube_strips(rows: pd.DataFrame, tubes: pd.DataFrame) -> pd.DataFrame:
    """
    For each tube, ``N_TIMES`` of its snapshots spread evenly over its run.

    Args:
        rows (pd.DataFrame): One row per (snapshot, tube), with ``t``.
        tubes (pd.DataFrame): ``run_id``, ``roi_idx`` pairs to pick for.

    Returns:
        pd.DataFrame: The picked rows.
    """
    out = []
    for rid, roi in tubes.itertuples(index=False):
        g = rows[(rows.run_id == rid) & (rows.roi_idx == roi)].sort_values("t")
        out.append(g.iloc[np.unique(np.linspace(0, len(g) - 1, N_TIMES).astype(int))])
    return pd.concat(out) if out else rows.iloc[:0]


def tube_model_items(
    scored: pd.DataFrame, n_seen: int = 100, n_none: int = 20, seed: int = 0
) -> pd.DataFrame:
    """
    Round 3: never-detected tubes as a trained locator sees them, four times each.

    Tubes where the locator sees a fly somewhere (presence above ``UNSURE[1]`` in
    any snapshot) hold both its false detections and the dead flies; a small
    sample of tubes it calls empty throughout checks that call. A ring is shown
    wherever the locator leans towards a fly.

    Args:
        scored (pd.DataFrame): Never-detected crops with ``px``, ``py``, ``presence``.
        n_seen (int): Tubes where the locator sees something.
        n_none (int): Tubes it calls empty everywhere.
        seed (int): Sampling seed.

    Returns:
        pd.DataFrame: Queue rows.
    """
    lo, hi = UNSURE
    peak = scored.groupby(["run_id", "roi_idx"]).presence.max().reset_index()
    parts = []
    for kind, sel, n in (
        ("tube_model_seen", peak.presence > hi, n_seen),
        ("tube_model_none", peak.presence < lo, n_none),
    ):
        picked = _tube_strips(
            scored, _spread_over_runs(peak[sel][["run_id", "roi_idx"]], n, seed)
        )
        show = picked.presence >= lo
        parts.append(
            picked.assign(
                kind=kind,
                px=picked.px.where(show),
                py=picked.py.where(show),
                group="t:" + picked.run_id + ":" + picked.roi_idx.astype(str),
            )
        )
    q = pd.concat(parts, ignore_index=True)
    q["item_id"] = (
        q.run_id + ":" + q.roi_idx.astype(str) + ":" + q.sid.astype(int).astype(str)
    )
    return q[COLUMNS]


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


def model_items(
    scored: pd.DataFrame,
    n_unsure: int = 100,
    n_conf: int = 40,
    n_none: int = 20,
    seed: int = 0,
) -> pd.DataFrame:
    """
    Round 2: crops AdaptiveBGModel missed, as a trained locator sees them.

    ``scored`` holds the locator's position (``px``, ``py``, ROI-relative) and
    ``presence`` for each missed crop. Only the uncertain ones (presence within
    ``UNSURE``) need a person; small random samples of the confident calls either
    way measure how often those are wrong. A ring is shown wherever the locator
    leans towards a fly (presence at or above the lower bound).

    Args:
        scored (pd.DataFrame): Missed crops with ``px``, ``py``, ``presence``.
        n_unsure (int): Uncertain crops to review (spread over runs).
        n_conf (int): Confident-fly crops to audit.
        n_none (int): Confident-empty crops to audit.
        seed (int): Sampling seed.

    Returns:
        pd.DataFrame: Queue rows.
    """
    lo, hi = UNSURE
    parts = []
    for kind, sel, n in (
        ("model_unsure", scored.presence.between(lo, hi), n_unsure),
        ("model_conf", scored.presence > hi, n_conf),
        ("model_none", scored.presence < lo, n_none),
    ):
        pool = scored[sel].sample(frac=1.0, random_state=seed)
        pool = pool.assign(rank=pool.groupby("run_id").cumcount())
        pick = pool.sort_values("rank", kind="stable").head(n)
        show = pick.presence >= lo
        block = np.arange(len(pick)) // AUDIT_BLOCK
        parts.append(
            pick.assign(
                kind=kind,
                px=pick.px.where(show),
                py=pick.py.where(show),
                group=[f"m:{kind}:{b}" for b in block],
            )
        )
    q = pd.concat(parts, ignore_index=True)
    q["item_id"] = (
        q.run_id + ":" + q.roi_idx.astype(str) + ":" + q.sid.astype(int).astype(str)
    )
    return q[COLUMNS]


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
    ap.add_argument(
        "--round2",
        type=Path,
        default=None,
        help="scored missed crops; appends round-2 items to the queue",
    )
    ap.add_argument(
        "--round3",
        type=Path,
        default=None,
        help="scored never-detected crops; appends round-3 tubes to the queue",
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    runs = pd.read_parquet(args.runs) if args.runs else None
    if args.round2 or args.round3:
        q = pd.read_parquet(args.out / "queue.parquet")
        scored = pd.read_parquet(args.round2 or args.round3)
        new = model_items(scored) if args.round2 else tube_model_items(scored)
        q = pd.concat([q, new[~new.item_id.isin(q.item_id)]], ignore_index=True)
    else:
        q = build(pd.read_parquet(args.pack / "labels.parquet"), runs, args.max_tubes)
    q.to_parquet(args.out / "queue.parquet")
    print(q.kind.value_counts().to_string())


if __name__ == "__main__":
    main()
