"""Turn review answers into labels, and report what the audits say.

Each answered crop becomes one label row: ``human_fly`` at the clicked position,
or ``human_empty``; ``unsure`` answers are dropped. The last answer for a crop wins.
Human labels replace any automatic label for the same (snapshot, tube) in
training (:func:`dl_tracking.train.split_rows`), and in validation and test they
are what the false-detection target is measured on.

Usage::

    python -m dl_tracking.review.ingest --review /mnt/cache/dl_tracking/review
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

MOVED_PX = 4.0  # an audited ring moved further than this was wrong
STILL_PX = 10.0  # a dead fly's clicks agree to within this (it shifts as it dries)
# Review kinds that show one never-detected tube at several times (rounds 1 and 3).
TUBE_KINDS = ("never_detected", "tube_model_seen", "tube_model_none")
KEEP = ["run_id", "sid", "roi_idx", "t", "roi_x", "roi_y", "roi_w", "roi_h"]


def latest_answers(path: Path) -> pd.DataFrame:
    """
    Read ``answers.jsonl``, keeping the last answer for each crop.

    Args:
        path (Path): The answers file.

    Returns:
        pd.DataFrame: One row per answered crop.
    """
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["item_id", "kind", "state", "x", "y", "moved_px"])
    rows = [json.loads(line) for line in path.open()]
    return pd.DataFrame(rows).drop_duplicates("item_id", keep="last")


def human_labels(queue: pd.DataFrame, answers: pd.DataFrame) -> pd.DataFrame:
    """
    Convert answers to label rows (``human_fly`` / ``human_empty``).

    Args:
        queue (pd.DataFrame): ``queue.parquet``.
        answers (pd.DataFrame): Output of :func:`latest_answers`.

    Returns:
        pd.DataFrame: Label rows with ``status``, ``x``, ``y`` (NaN when empty),
        ``present`` and ``shape_ok`` (False: a click gives no size or angle).
    """
    queue = queue.reset_index(drop=True)  # the server indexes it by item_id
    a = answers[answers.state.isin(["fly", "empty"])]
    out = queue[["item_id", *KEEP]].merge(
        a[["item_id", "state", "x", "y"]], on="item_id"
    )
    out["present"] = out.state == "fly"
    out["status"] = np.where(out.present, "human_fly", "human_empty")
    out.loc[~out.present, ["x", "y"]] = np.nan
    out["shape_ok"] = False
    out[["w", "h", "phi"]] = np.nan
    return out.drop(columns=["item_id", "state"])


def propagate(
    labels: pd.DataFrame, queue: pd.DataFrame, pack_labels: pd.DataFrame
) -> pd.DataFrame:
    """
    Extend never-detected-tube answers to the tube's other snapshots.

    Tubes are sealed, so a tube answered empty at every time shown is empty for the
    whole run. A fly in a never-detected tube is almost always dead (Giorgio,
    2026-10-01): it stays put while it dehydrates and changes shape. So between two
    consecutive fly clicks within ``STILL_PX`` of each other it was there
    throughout, at a position interpolated between the clicks. Nothing is
    propagated past an empty strip, across a larger jump, or beyond the first and
    last clicks.

    Args:
        labels (pd.DataFrame): Output of :func:`human_labels`.
        queue (pd.DataFrame): ``queue.parquet``.
        pack_labels (pd.DataFrame): The pack's labels (every snapshot of each tube).

    Returns:
        pd.DataFrame: New label rows (``source`` = ``propagated``) for snapshots
        that were not themselves answered.
    """
    queue = queue.reset_index(drop=True)
    nd = queue[queue.kind.isin(TUBE_KINDS)][["run_id", "roi_idx", "sid"]]
    shown = labels.merge(nd, on=["run_id", "roi_idx", "sid"])
    answered = set(zip(labels.sid, labels.roi_idx, strict=True))
    tubes = pack_labels[pack_labels.status == "never_detected"]
    out = []
    for (rid, roi), g in shown.groupby(["run_id", "roi_idx"]):
        g = g.sort_values("t")
        snaps = tubes[(tubes.run_id == rid) & (tubes.roi_idx == roi)].sort_values("t")
        snaps = snaps[
            [
                (s, r) not in answered
                for s, r in zip(snaps.sid, snaps.roi_idx, strict=True)
            ]
        ]
        if not g.present.any():  # empty at every time shown: empty throughout
            out.append(snaps.assign(present=False, x=np.nan, y=np.nan))
            continue
        for a, b in zip(g.iloc[:-1].itertuples(), g.iloc[1:].itertuples(), strict=True):
            if (
                not (a.present and b.present)
                or np.hypot(b.x - a.x, b.y - a.y) > STILL_PX
            ):
                continue
            mid = snaps[(snaps.t > a.t) & (snaps.t < b.t)]
            f = (mid.t - a.t) / (b.t - a.t)
            out.append(
                mid.assign(
                    present=True, x=a.x + f * (b.x - a.x), y=a.y + f * (b.y - a.y)
                )
            )
    if not out:
        return labels.iloc[:0].assign(source=pd.Series(dtype=str))
    new = pd.concat(out, ignore_index=True)[KEEP + ["present", "x", "y"]]
    new["status"] = np.where(new.present, "human_fly", "human_empty")
    new["shape_ok"] = False
    new[["w", "h", "phi"]] = np.nan
    return new.assign(source="propagated")


def audit_report(queue: pd.DataFrame, answers: pd.DataFrame) -> dict:
    """
    Summarise how often each kind of proposal was wrong.

    A proposal with a ring is wrong when the reviewer removed it (no fly) or moved
    it by more than ``MOVED_PX``; one without a ring is wrong when the reviewer
    placed one.

    Args:
        queue (pd.DataFrame): ``queue.parquet``.
        answers (pd.DataFrame): Output of :func:`latest_answers`.

    Returns:
        dict: Per kind: answered, unsure, fly, empty, and the wrong rate.
    """
    queue = queue.reset_index(drop=True)
    m = queue[["item_id", "kind", "px"]].merge(
        answers[["item_id", "state", "moved_px"]], on="item_id"
    )
    report = {}
    for kind, g in m.groupby("kind"):
        sure = g[g.state != "unsure"]
        had_ring = sure.px.notna()
        wrong = np.where(
            had_ring,
            (sure.state == "empty") | (sure.moved_px.fillna(0) > MOVED_PX),
            sure.state == "fly",
        )
        report[kind] = {
            "answered": len(g),
            "unsure": int((g.state == "unsure").sum()),
            "fly": int((sure.state == "fly").sum()),
            "empty": int((sure.state == "empty").sum()),
            "wrong_rate": round(float(wrong.mean()), 3) if len(sure) else None,
        }
    return report


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--review", type=Path, default=Path("/mnt/cache/dl_tracking/review")
    )
    ap.add_argument(
        "--pack", type=Path, default=Path("/mnt/cache/dl_tracking/data/pack")
    )
    args = ap.parse_args()
    queue = pd.read_parquet(args.review / "queue.parquet")
    answers = latest_answers(args.review / "answers.jsonl")
    labels = human_labels(queue, answers).assign(source="answered")
    extra = propagate(labels, queue, pd.read_parquet(args.pack / "labels.parquet"))
    print(
        f"propagated: {int(extra.present.sum())} fly, "
        f"{int((~extra.present).sum())} empty"
    )
    labels = pd.concat([labels, extra], ignore_index=True)
    labels.to_parquet(args.review / "human_labels.parquet")
    report = audit_report(queue, answers)
    (args.review / "audit_report.json").write_text(json.dumps(report, indent=1))
    print(
        f"{len(answers)} answers -> {len(labels)} labels "
        f"({int(labels.present.sum())} fly, {int((~labels.present).sum())} empty)"
    )
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
