"""Compare the locator with AdaptiveBGModel on a video with pixel-motion truth.

Inputs are the locator's output (:mod:`dl_tracking.run_video`), an offline
AdaptiveBGModel DB of the same video, and the ethoscopy session's pixel-motion
parquet (per frame and tube, pixels changing by more than 5/8/12/20 grey levels in
a crop centred on the fly). A 10-s window is *still* when no frame in it has
``MIN_PIXELS`` pixels changing by more than the chosen level, and *moving*
otherwise (the "strict" definition, which counts twitches as movement).

Movement from positions uses the frame-to-frame displacement in full-resolution
pixels, at several cut-offs. The locator is scored twice: with its float output,
and rounded to whole pixels as the device's SMALLINT columns would store it.

Usage::

    python -m dl_tracking.evaluate CNN.parquet --abg ABG.db [...] --pixel PIX.parquet [...] \\
        --still-tubes 6 9 11 17 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import db_io

WINDOW_S = 10.0
MIN_PIXELS = 3
CUTS_PX = (0.52, 1.0, 2.0)  # 0.52 px is what a corrected velocity of 1.0 means today
PRESENT = 0.5


def load_abg(db: Path) -> pd.DataFrame:
    """
    Load every ROI's real (non-inferred) AdaptiveBGModel rows.

    A DB made by tracking one segment of a long video records that segment in
    METADATA (``experimental_info = {'segment': [start_s, end_s]}``) and also holds
    a warm-up before it; only rows inside the segment are kept, so the DBs of
    consecutive segments can be concatenated without overlap.

    Args:
        db (Path): Offline tracking DB.

    Returns:
        pd.DataFrame: ``t`` (ms), ``roi_idx``, ``x``, ``y``.
    """
    parts = []
    with db_io.connect(db) as conn:
        segment = db_io.experimental_info(db_io.read_metadata(conn)).get("segment")
        lo, hi = (1000 * segment[0], 1000 * segment[1]) if segment else (-1, 2**62)
        tables = db_io.tables(conn)
        for idx in db_io.roi_map(conn)[:, 0]:
            # Reason: the writer creates a ROI's table with its first row, so a fly
            # that was never detected (a dead one) has no table at all.
            if f"ROI_{idx}" not in tables:
                continue
            rows = db_io.rows_between(conn, f"ROI_{idx}", int(lo), int(hi))
            real = rows[rows[:, -1] == 0]
            parts.append(
                pd.DataFrame(
                    {
                        "t": real[:, 0].astype(np.int64),
                        "roi_idx": int(idx),
                        "x": real[:, 1],
                        "y": real[:, 2],
                    }
                )
            )
    return pd.concat(parts, ignore_index=True)


def displacement(df: pd.DataFrame, rounded: bool = False) -> pd.Series:
    """
    Frame-to-frame displacement of each tube's track (NaN at each track start).

    Args:
        df (pd.DataFrame): ``t``, ``roi_idx``, ``x``, ``y`` rows.
        rounded (bool): Round positions to whole pixels first.

    Returns:
        pd.Series: Displacement in px, aligned with ``df``.
    """
    df = df.sort_values(["roi_idx", "t"])
    xy = df[["x", "y"]].round() if rounded else df[["x", "y"]]
    d = np.hypot(xy.x.diff(), xy.y.diff())
    d[df.roi_idx.ne(df.roi_idx.shift())] = np.nan
    return d.reindex(df.index)


def pixel_windows(pix: pd.DataFrame, level: str = "fly_20") -> pd.DataFrame:
    """
    Label each tube's 10-s windows still or moving from pixel motion.

    Args:
        pix (pd.DataFrame): Pixel-motion rows (``t`` in s, ``roi``, level columns).
        level (str): Which grey-level column to use.

    Returns:
        pd.DataFrame: ``roi_idx``, ``win``, ``moving`` (bool).
    """
    w = pix.assign(win=(pix.t // WINDOW_S).astype(int), hit=pix[level] >= MIN_PIXELS)
    return (
        w.groupby(["roi", "win"])
        .hit.any()
        .rename("moving")
        .reset_index()
        .rename(columns={"roi": "roi_idx"})
    )


def window_calls(df: pd.DataFrame, disp: pd.Series, cut: float) -> pd.Series:
    """
    Tell, per tube and window, whether any displacement reaches ``cut``.

    Args:
        df (pd.DataFrame): Track rows (``t`` in ms, ``roi_idx``).
        disp (pd.Series): Their displacements.
        cut (float): Movement cut-off, px.

    Returns:
        pd.Series: Boolean, indexed by (roi_idx, win).
    """
    win = (df.t / 1000 // WINDOW_S).astype(int)
    return (disp >= cut).groupby([df.roi_idx, win]).any()


def evaluate(
    cnn: pd.DataFrame, abg: pd.DataFrame, pix: pd.DataFrame, still_tubes: list[int]
) -> dict:
    """
    Compute detection, agreement, still-fly jitter and window-level movement calls.

    Args:
        cnn (pd.DataFrame): Locator rows (``t`` ms, ``roi_idx``, x, y, presence).
        abg (pd.DataFrame): AdaptiveBGModel real rows.
        pix (pd.DataFrame): Pixel-motion rows.
        still_tubes (list[int]): Tubes holding dead or immobile flies.

    Returns:
        dict: The report.
    """
    # Reason: an offline AdaptiveBGModel DB may cover every Nth frame only; score
    # both trackers on the frames both processed, so displacements are per the same
    # interval and detection rates share a denominator.
    common = np.intersect1d(cnn.t.unique(), abg.t.unique())
    cnn, abg = cnn[cnn.t.isin(common)], abg[abg.t.isin(common)]
    frames = len(common)
    found = cnn[cnn.presence > PRESENT]
    per_tube = pd.DataFrame(
        {
            "cnn_detect": found.groupby("roi_idx").size() / frames,
            "abg_detect": abg.groupby("roi_idx").size() / frames,
        }
    ).fillna(0)
    both = found.merge(abg, on=["t", "roi_idx"], suffixes=("", "_abg"))
    gap = np.hypot(both.x - both.x_abg, both.y - both.y_abg)
    report: dict = {
        "frames": int(frames),
        "detect_all": per_tube.mean().round(4).to_dict(),
        "detect_still_tubes": per_tube.loc[per_tube.index.isin(still_tubes)]
        .mean()
        .round(4)
        .to_dict(),
        "cnn_vs_abg_px": {
            "median": round(float(gap.median()), 2),
            "p95": round(float(gap.quantile(0.95)), 2),
        },
        "per_tube": per_tube.round(4).to_dict("index"),
    }
    still = cnn[cnn.roi_idx.isin(still_tubes)]
    jit = {}
    for name, rounded in (("float", False), ("rounded", True)):
        d = displacement(still, rounded).dropna()
        jit[name] = {
            "p50": round(float(d.median()), 3),
            "p95": round(float(d.quantile(0.95)), 3),
            "p99": round(float(d.quantile(0.99)), 3),
            **{f"frac_ge_{c}": round(float((d >= c).mean()), 4) for c in CUTS_PX},
        }
    report["still_fly_jitter_px"] = jit

    truth = pixel_windows(pix).set_index(["roi_idx", "win"]).moving
    calls = {}
    tracks = {
        "cnn_float": (cnn, displacement(cnn)),
        "cnn_rounded": (cnn, displacement(cnn, rounded=True)),
        "abg": (abg, displacement(abg)),
    }
    for name, (df, disp) in tracks.items():
        for cut in CUTS_PX:
            called = window_calls(df, disp, cut).reindex(truth.index, fill_value=False)
            calls[f"{name}@{cut}"] = {
                "false_moving_on_still": round(float(called[~truth].mean()), 4),
                "detected_on_moving": round(float(called[truth].mean()), 4),
            }
    report["windows"] = {
        "n_still": int((~truth).sum()),
        "n_moving": int(truth.sum()),
        **calls,
    }
    return report


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cnn", type=Path, help="locator output (parquet)")
    ap.add_argument(
        "--abg",
        type=Path,
        nargs="+",
        required=True,
        help="AdaptiveBGModel DB(s); segment DBs keep only their segment",
    )
    ap.add_argument(
        "--pixel", type=Path, nargs="+", required=True, help="pixel-motion parquet(s)"
    )
    ap.add_argument("--still-tubes", type=int, nargs="*", default=[])
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    report = evaluate(
        pd.read_parquet(args.cnn),
        pd.concat([load_abg(db) for db in args.abg], ignore_index=True),
        pd.concat([pd.read_parquet(p) for p in args.pixel], ignore_index=True),
        args.still_tubes,
    )
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
