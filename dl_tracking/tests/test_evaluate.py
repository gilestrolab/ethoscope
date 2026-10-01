"""Tests for the video evaluation and the video runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dl_tracking import evaluate as E
from dl_tracking import model as M
from dl_tracking import run_video as R

from .conftest import make_db, still_rows


def test_displacement_restarts_per_tube_and_rounds() -> None:
    """Displacements never span two tubes; rounding snaps sub-pixel wobble."""
    df = pd.DataFrame(
        {
            "t": [0, 100, 200, 0, 100],
            "roi_idx": [1, 1, 1, 2, 2],
            "x": [10.0, 10.4, 13.4, 50.0, 50.2],
            "y": [5.0] * 5,
        }
    )
    d = E.displacement(df)
    assert np.isnan(d.iloc[0]) and np.isnan(d.iloc[3])
    assert d.iloc[1:3].tolist() == pytest.approx([0.4, 3.0])
    r = E.displacement(df, rounded=True)
    assert r.iloc[1] == 0 and r.iloc[4] == 0


def test_pixel_windows_strict_rule() -> None:
    """A window is moving when any frame has >= MIN_PIXELS changed pixels."""
    pix = pd.DataFrame(
        {"t": [1.0, 2.0, 11.0, 12.0], "roi": [1, 1, 1, 1], "fly_20": [0, 2, 0, 3]}
    )
    w = E.pixel_windows(pix).set_index("win").moving
    assert w[0] == False and w[1] == True  # noqa: E712 - explicit booleans read clearer


def test_evaluate_on_synthetic_tracks() -> None:
    """A still fly: the jittery tracker is caught out, the stable one is not."""
    t = np.arange(0, 20_000, 250)
    rng = np.random.default_rng(0)
    cnn = pd.DataFrame(
        {
            "t": t,
            "roi_idx": 1,
            "x": 100 + rng.normal(0, 0.2, len(t)),
            "y": 30.0,
            "presence": 0.99,
        }
    )
    abg = pd.DataFrame({"t": t[::2], "roi_idx": 1, "x": 100.0, "y": 30.0})
    pix = pd.DataFrame({"t": t / 1000, "roi": 1, "fly_20": 0})
    rep = E.evaluate(cnn, abg, pix, still_tubes=[1])
    assert rep["frames"] == len(t[::2])
    assert rep["detect_all"] == {"cnn_detect": 1.0, "abg_detect": 1.0}
    assert rep["windows"]["n_still"] == 2 and rep["windows"]["n_moving"] == 0
    assert rep["windows"]["abg@0.52"]["false_moving_on_still"] == 0
    assert rep["still_fly_jitter_px"]["float"]["p50"] > 0.1


def test_load_abg_skips_tubes_never_detected(tmp_path: Path) -> None:
    """A ROI whose table was never created (a dead fly) is simply absent."""
    path = make_db(
        tmp_path / "a" / "E" / "d" / "r.db", {1: still_rows(0, 5000, 500, 7, 8)}, []
    )
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO ROI_MAP VALUES (2, 2, 40, 300, 560, 60)")
    abg = E.load_abg(path)
    assert set(abg.roi_idx) == {1} and len(abg) == 10


def test_locate_returns_roi_relative_positions() -> None:
    """The runner maps canvas positions back into each ROI's frame of reference."""
    net = M.build("tiny").eval()
    rois = np.array([[1, 40, 100, 560, 60], [2, 640, 164, 560, 60]])
    frames = [np.full((960, 1280), 120, np.uint8) for _ in range(3)]
    out = R.locate(net, frames, rois, "cpu")
    assert out.shape == (3, 2, 7)
    # Untrained: positions are arbitrary but must lie within each canvas.
    assert np.all(out[..., 0] > -20) and np.all(out[..., 0] < 600)
    assert np.all((out[..., 6] >= 0) & (out[..., 6] <= 1))


def test_load_abg_keeps_only_the_declared_segment(tmp_path: Path) -> None:
    """A segment DB's warm-up rows are dropped, so segments concatenate cleanly."""
    path = make_db(
        tmp_path / "a" / "E" / "d" / "seg.db",
        {1: still_rows(0, 20_000, 1000, 7, 8)},
        [],
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE METADATA SET value = ? WHERE field = 'experimental_info'",
            ("{'segment': [5.0, 15.0]}",),
        )
    abg = E.load_abg(path)
    assert abg.t.min() == 5000 and abg.t.max() == 14_000 and len(abg) == 10


def test_auto_levels_scale_with_noise_per_phase() -> None:
    """Dim, quiet nights get a lower pixel level than noisy, bright days."""
    pix = pd.DataFrame(
        {
            "t": [1.0, 2.0, 3.0, 4.0],
            "roi": 1,
            "lit": [True, True, False, False],
            "ctl_noise": [1.3, 1.3, 0.3, 0.3],
            "fly_5": [9, 9, 3, 0],
            "fly_8": [5, 5, 0, 0],
            "fly_12": [1, 1, 0, 0],
            "fly_20": [0, 0, 0, 0],
        }
    )
    assert E.auto_levels(pix) == {True: "fly_20", False: "fly_5"}
    w = E.pixel_windows(pix, "auto")
    assert w.moving.tolist() == [True]  # the dark frame at t=3 moves at level 5


def test_frames_without_a_fly_do_not_count_as_movement() -> None:
    """Absent frames (presence < 0.5) drop out of the track instead of jumping."""
    t = np.arange(0, 20_000, 250)
    x = np.full(len(t), 100.0)
    pres = np.full(len(t), 0.99)
    x[10], pres[10] = 400.0, 0.1  # one frame where the fly is not seen
    cnn = pd.DataFrame({"t": t, "roi_idx": 1, "x": x, "y": 30.0, "presence": pres})
    abg = pd.DataFrame({"t": t, "roi_idx": 1, "x": 100.0, "y": 30.0})
    pix = pd.DataFrame({"t": t / 1000, "roi": 1, "fly_20": 0})
    rep = E.evaluate(cnn, abg, pix, still_tubes=[1])
    assert rep["windows"]["cnn_float@2.0"]["false_moving_on_still"] == 0
