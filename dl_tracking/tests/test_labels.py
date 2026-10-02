"""Tests for the label rules."""

from __future__ import annotations

import numpy as np

from dl_tracking import labels as L


def track(xs, ys=None, dt=500, t0=0, w=28, h=11, inferred=None) -> np.ndarray:
    """Build ROI rows from x (and optional y) positions, one frame every ``dt`` ms."""
    n = len(xs)
    ys = np.full(n, 30.0) if ys is None else np.asarray(ys, float)
    inf = np.zeros(n) if inferred is None else np.asarray(inferred, float)
    t = t0 + dt * np.arange(n)
    return np.column_stack(
        [t, xs, ys, np.full(n, w), np.full(n, h), np.zeros(n), np.zeros(n), inf]
    ).astype(float)


BOUNDS = L.SizeBounds(20, 36, 7, 15)


def test_walking_fly_is_not_a_hop() -> None:
    """Steady 6 px steps (faster than jump_px) are walking, not hopping."""
    rows = track(100 + 6.0 * np.arange(40))
    assert not L.suspicious_rows(rows).any()


def test_single_frame_hop_is_flagged() -> None:
    """A-B-A: one frame on a second blob 20 px away, then straight back."""
    xs = np.full(30, 100.0)
    xs[15] = 120
    flags = L.suspicious_rows(track(xs))
    assert flags[14:17].all() and flags.sum() == 3


def test_multi_frame_hop_is_flagged() -> None:
    """A-B-B-B-A: the tracker sits on the second blob for three frames."""
    xs = np.full(30, 100.0)
    xs[10:13] = 125
    flags = L.suspicious_rows(track(xs))
    assert flags[9:14].all()


def test_centroid_jitter_is_not_a_hop() -> None:
    """A still fly whose centroid wobbles by 4 px as the blob changes shape."""
    xs = np.array([327, 325, 327, 328, 324, 328, 327, 327, 328, 327], float)
    assert not L.suspicious_rows(track(xs)).any()


def test_walk_away_and_back_is_not_a_hop() -> None:
    """Walking out and back gradually lands home over many small steps."""
    xs = np.concatenate([100 + 3.0 * np.arange(10), 127 - 3.0 * np.arange(10)])
    assert not L.suspicious_rows(track(xs)).any()


def test_teleport_is_flagged() -> None:
    """A 400 px step in 500 ms is faster than any fly."""
    xs = np.full(10, 100.0)
    xs[5:] = 500
    flags = L.suspicious_rows(track(xs))
    assert flags[4] and flags[5] and flags.sum() == 2


def test_detection_label_confident() -> None:
    """A clean detection at the snapshot time becomes a confident label."""
    rows = track(np.full(121, 200.0), t0=-30_000)
    lab = L.detection_label(rows, 0, BOUNDS)
    assert lab is not None and lab.kind == L.CONFIDENT
    assert (lab.x, lab.y, lab.span_px, lab.n_window) == (200, 30, 0, 121)


def test_detection_label_rejections() -> None:
    """Bad size or a nearby hop is kept as rejected, with the tracker's position."""
    rows = track(np.full(121, 200.0), t0=-30_000)
    small = rows.copy()
    small[60, L.W] = 8
    assert L.detection_label(small, 0, BOUNDS).kind == L.REJECTED_SIZE
    assert L.detection_label(rows, 0, None).kind == L.REJECTED_SIZE
    hop = rows.copy()
    hop[65, L.X] = 225  # 2.5 s after the snapshot
    lab = L.detection_label(hop, 0, BOUNDS)
    assert lab.kind == L.REJECTED_HOP and lab.x == 200


def test_detection_label_no_detection() -> None:
    """No row at the snapshot time, or only an inferred one: no label at all."""
    rows = track(np.full(121, 200.0), t0=-30_000)
    assert L.detection_label(rows, 250, BOUNDS) is None
    rows[60, L.INFERRED] = 1
    assert L.detection_label(rows, 0, BOUNDS) is None


def test_distant_hop_does_not_reject() -> None:
    """A hop 25 s after the snapshot says nothing about the snapshot's own frame."""
    rows = track(np.full(121, 200.0), t0=-30_000)
    rows[110, L.X] = 225
    assert L.detection_label(rows, 0, BOUNDS).kind == L.CONFIDENT


def test_gapfill_label() -> None:
    """Lost at (100, 30), found at (102, 31) an hour later: labelled in between."""
    before = track([100.0], t0=0)[0]
    after = track([102.0], ys=[31.0], t0=3_600_000)[0]
    lab = L.gapfill_label(before, after, 1_800_000)
    assert lab is not None and lab.kind == L.GAPFILL
    assert (lab.x, lab.y, lab.gap_ms) == (101, 30.5, 3_600_000)


def test_gapfill_rejections() -> None:
    """Moved while lost, gap too long, snapshot outside the gap, or missing ends."""
    before = track([100.0], t0=0)[0]
    moved = track([110.0], t0=60_000)[0]
    assert L.gapfill_label(before, moved, 30_000) is None
    late = track([100.0], t0=25 * 3600 * 1000)[0]
    assert L.gapfill_label(before, late, 3600 * 1000) is None
    back = track([100.0], t0=60_000)[0]
    assert L.gapfill_label(before, back, 90_000) is None
    assert L.gapfill_label(None, back, 30_000) is None


def test_size_bounds() -> None:
    """Bounds follow the fly's own size, with a floor, and need enough rows."""
    rng = np.random.default_rng(0)
    rows = track(np.full(200, 100.0))
    rows[:, L.W] = rng.normal(28, 1, 200).round()
    b = L.size_bounds(rows)
    assert b.contains(28, 11) and not b.contains(16, 11) and not b.contains(28, 4)
    assert b.w_hi - b.w_lo >= 6  # floor of 3 px on each side
    assert L.size_bounds(rows[:10]) is None


def test_local_contrast() -> None:
    """A dark blob on a bright tube has positive contrast; outside is NaN."""
    crop = np.full((60, 560), 200, np.uint8)
    crop[28:33, 98:103] = 40
    assert L.local_contrast(crop, 100, 30) > 100
    assert abs(L.local_contrast(crop, 300, 30)) < 1
    assert np.isnan(L.local_contrast(crop, 600, 30))
