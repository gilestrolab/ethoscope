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
LEVELS = (5, 8, 12, 20)  # grey-level columns of the pixel-motion parquet
NOISE_MULT = 14  # see auto_levels()
SLEEP_WINDOWS = 30  # sleep = 5 min of still 10-s windows, the ethoscope definition
BRIEF_S = 0.5  # up to this much movement in a window is a twitch (sustained truth)
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


def auto_levels(pix: pd.DataFrame) -> dict:
    """
    Pick the pixel-motion level per light phase, scaled to that phase's noise.

    The rule of the ethoscopy session's ``eval_long.py``: the smallest of the
    recorded levels that is at least ``NOISE_MULT`` times the median empty-tube
    noise (``ctl_noise``). Alice's dead flies validated 20 grey levels at ~14x the
    noise of her bright IR; dimmer videos need a lower level to see real movement.

    Args:
        pix (pd.DataFrame): Pixel-motion rows, with a boolean ``lit`` column if the
            light phases are known.

    Returns:
        dict: Phase (True = lit, False = dark, None = unknown) to column name.
    """
    phases = pix.lit if "lit" in pix else pd.Series(None, index=pix.index)
    noise = pix.ctl_noise.groupby(phases, dropna=False).median()
    return {
        ph: f"fly_{next((lv for lv in LEVELS if lv >= NOISE_MULT * n), LEVELS[-1])}"
        for ph, n in noise.items()
    }


def pixel_windows(pix: pd.DataFrame, level: str = "fly_20") -> pd.DataFrame:
    """
    Label each tube's 10-s windows still or moving from pixel motion.

    Args:
        pix (pd.DataFrame): Pixel-motion rows (``t`` in s, ``roi``, level columns).
        level (str): The grey-level column to use, or ``auto`` for
            :func:`auto_levels`.

    Returns:
        pd.DataFrame: ``roi_idx``, ``win``, ``moving`` (bool: any frame with
        motion, the strict truth), ``sustained`` (bool: more than
        ``BRIEF_S`` seconds of frames with motion, so twitches count as still).
    """
    if level == "auto":
        cols = auto_levels(pix)
        phases = pix.lit if "lit" in pix else pd.Series(None, index=pix.index)
        counts = np.select(
            [phases == ph for ph in cols if ph is not None],
            [pix[c] for ph, c in cols.items() if ph is not None],
            default=pix[cols.get(None, "fly_20")],
        )
    else:
        counts = pix[level]
    w = pix.assign(win=(pix.t // WINDOW_S).astype(int), hit=counts >= MIN_PIXELS)
    g = w.groupby(["roi", "win"]).hit.agg(["sum", "size"])
    # Reason: "brief" = up to BRIEF_S of moving frames (eval_long.py allows 3
    # frames at 6 fps); scale to this video's frame rate.
    fps = float(g["size"].median()) / WINDOW_S
    brief = max(1, round(BRIEF_S * fps))
    out = pd.DataFrame({"moving": g["sum"] > 0, "sustained": g["sum"] > brief})
    return out.reset_index().rename(columns={"roi": "roi_idx"})


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


def sleep_from_still(still: pd.Series, n: int = SLEEP_WINDOWS) -> pd.Series:
    """
    Mark sleep: runs of at least ``n`` consecutive still windows in a tube.

    Args:
        still (pd.Series): Boolean, indexed by (roi_idx, win).
        n (int): Minimum run length in windows (30 x 10 s = 5 min).

    Returns:
        pd.Series: Boolean sleep, same index (sorted).
    """
    s = still.sort_index()
    roi = s.index.get_level_values(0).to_numpy()
    win = s.index.get_level_values(1).to_numpy()
    v = s.to_numpy()
    # A run breaks at a new tube, a gap in windows, or a change of state.
    brk = np.r_[
        True, (roi[1:] != roi[:-1]) | (win[1:] != win[:-1] + 1) | (v[1:] != v[:-1])
    ]
    run = np.cumsum(brk)
    length = np.bincount(run)[run]
    return pd.Series(v & (length >= n), index=s.index)


def sleep_metrics(called_moving: pd.Series, truth_moving: pd.Series) -> dict:
    """
    Compare sleep derived from a tracker's movement calls with pixel-truth sleep.

    Args:
        called_moving (pd.Series): Tracker's moving calls per (roi_idx, win).
        truth_moving (pd.Series): Pixel-truth moving per (roi_idx, win).

    Returns:
        dict: Sleep fraction, window-level sensitivity (truth sleep found) and
        precision (called sleep that is truth sleep), and the mean absolute error
        of per-tube sleep fractions.
    """
    pred = sleep_from_still(~called_moving)
    true = sleep_from_still(~truth_moving).reindex(pred.index)
    per_tube = pd.DataFrame({"pred": pred, "true": true}).groupby(level=0).mean()
    return {
        "sleep_fraction": round(float(pred.mean()), 4),
        "sensitivity": round(float(pred[true].mean()), 4) if true.any() else None,
        "precision": round(float(true[pred].mean()), 4) if pred.any() else None,
        "per_tube_abs_error": round(
            float((per_tube.pred - per_tube.true).abs().mean()), 4
        ),
    }


def evaluate(
    cnn: pd.DataFrame,
    abg: pd.DataFrame,
    pix: pd.DataFrame,
    still_tubes: list[int],
    level: str = "fly_20",
) -> dict:
    """
    Compute detection, agreement, still-fly jitter and window-level movement calls.

    Args:
        cnn (pd.DataFrame): Locator rows (``t`` ms, ``roi_idx``, x, y, presence).
        abg (pd.DataFrame): AdaptiveBGModel real rows.
        pix (pd.DataFrame): Pixel-motion rows.
        still_tubes (list[int]): Tubes holding dead or immobile flies.
        level (str): Pixel-motion level for the window truth (see
            :func:`pixel_windows`).

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
    # Reason: like AdaptiveBGModel's real rows, the locator's track holds only the
    # frames where it reports a fly; elsewhere its argmax lands anywhere, and the
    # jump back would count as movement.
    still = found[found.roi_idx.isin(still_tubes)]
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

    pw = pixel_windows(pix, level).set_index(["roi_idx", "win"])
    truth, sustained = pw.moving, pw.sustained
    report["pixel_level"] = (
        {str(k): v for k, v in auto_levels(pix).items()} if level == "auto" else level
    )
    calls = {}
    tracks = {
        "cnn_float": (found, displacement(found)),
        "cnn_rounded": (found, displacement(found, rounded=True)),
        "abg": (abg, displacement(abg)),
    }
    # Reason: two references. Strict counts any pixel motion (a twitch, grooming)
    # as waking, as eval_long.py does; sustained lets brief twitches stay asleep,
    # which is what sleep scored from positions can be expected to match.
    sleep = {
        "truth_sleep_fraction_strict": round(float(sleep_from_still(~truth).mean()), 4),
        "truth_sleep_fraction_sustained": round(
            float(sleep_from_still(~sustained).mean()), 4
        ),
    }
    for name, (df, disp) in tracks.items():
        for cut in CUTS_PX:
            # Reason: a window with no detection counts as still, as in ethoscopy;
            # that is how flies AdaptiveBGModel loses get scored as sleeping.
            called = window_calls(df, disp, cut).reindex(truth.index, fill_value=False)
            calls[f"{name}@{cut}"] = {
                "false_moving_on_still": round(float(called[~truth].mean()), 4),
                "detected_on_moving": round(float(called[truth].mean()), 4),
            }
            sleep[f"{name}@{cut}"] = {
                "strict": sleep_metrics(called, truth),
                "sustained": sleep_metrics(called, sustained),
            }
    report["sleep"] = sleep
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
    ap.add_argument(
        "--tubes",
        type=int,
        nargs="*",
        default=None,
        help="score only these ROIs (e.g. the single-fly tubes)",
    )
    ap.add_argument("--level", default="fly_20", help="pixel level column, or 'auto'")
    ap.add_argument(
        "--lum",
        type=Path,
        default=None,
        help="CSV with t_s and lum per minute; lit when lum > 70",
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    pix = pd.concat([pd.read_parquet(p) for p in args.pixel], ignore_index=True)
    if args.lum:
        # Reason: the same phase rule as eval_long.py (lit when lum > 70).
        lum = pd.read_csv(args.lum).sort_values("t_s")
        i = np.clip(
            np.searchsorted(lum.t_s.to_numpy(), pix.t.to_numpy(), "right") - 1,
            0,
            len(lum) - 1,
        )
        pix["lit"] = lum.lum.to_numpy()[i] > 70
    cnn = pd.read_parquet(args.cnn)
    abg = pd.concat([load_abg(db) for db in args.abg], ignore_index=True)
    if args.tubes:
        # Reason: both trackers assume one fly per tube; tubes holding two flies
        # (e.g. half of the 2019 ETHOSCOPE_109 recording) say nothing about either.
        cnn, abg = cnn[cnn.roi_idx.isin(args.tubes)], abg[abg.roi_idx.isin(args.tubes)]
        pix = pix[pix.roi.isin(args.tubes)]
    report = evaluate(cnn, abg, pix, args.still_tubes, args.level)
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        args.out.write_text(text)


if __name__ == "__main__":
    main()
