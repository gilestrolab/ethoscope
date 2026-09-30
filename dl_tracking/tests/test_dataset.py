"""Tests for label selection, targets, augmentation and the packed dataset."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from dl_tracking import dataset as D
from dl_tracking import preprocess as P


def label_row(status: str, contrast: float, roi: int = 1, run: str = "r", **kw) -> dict:
    """A packed label row."""
    row = {
        "run_id": run,
        "sid": 0,
        "roi_idx": roi,
        "status": status,
        "contrast": contrast,
        "roi_x": 40,
        "roi_y": 100,
        "roi_w": 560,
        "roi_h": 60,
        "x": 100.0,
        "y": 30.0,
        "w": 28.0,
        "h": 11.0,
        "phi": 10.0,
    }
    return {**row, **kw}


def test_training_rows_filters_gapfills_by_relative_contrast() -> None:
    """A gap fill needs 40% of the same fly's typical contrast (or 10 grey levels)."""
    labels = pd.DataFrame(
        [
            label_row("confident", 60),
            label_row("confident", 60),
            label_row("gapfill", 30),  # 50% of 60: kept
            label_row("gapfill", 20),  # 33%: dropped
            label_row("gapfill", 12, roi=2),  # no confident labels: floor of 10 applies
            label_row("gapfill", -40, roi=2),
            label_row("missed", np.nan),
            label_row("rejected_hop", 50),
            label_row(
                "confident", 60, roi=3, roi_h=165, roi_w=170
            ),  # a well, not a tube
        ]
    )
    rows = D.training_rows(labels)
    assert sorted(zip(rows.status, rows.contrast, strict=True)) == [
        ("confident", 60),
        ("confident", 60),
        ("gapfill", 12),
        ("gapfill", 30),
    ]
    assert rows[rows.status == "gapfill"].shape_ok.eq(False).all()


def test_encode_round_trips_through_decode() -> None:
    """A target encoded on the grid decodes back to the same position, size, angle."""
    t = D.Target(True, u=161.3, v=14.8, w=28, h=11, phi=150, shape_ok=True)
    enc = D.encode(t)
    i, j = enc["cell"]
    assert enc["heat"][i, j] == 1 and enc["heat"].max() == 1
    maps = np.full((1, 7, D.OUT_H, D.OUT_W), -9.0, np.float32)
    maps[0, 0, i, j] = 9
    maps[0, 1:, i, j] = enc["reg"]
    u, v, w, h, phi = P.decode(maps, np.zeros((1, 1)))[0, :5]
    assert (u, v, w, h, phi) == pytest.approx((161.3, 14.8, 28, 11, 150), abs=1e-3)


def test_encode_absent_and_off_canvas() -> None:
    """No fly, or a fly outside the canvas: empty heatmap, masks and presence 0."""
    for t in (D.Target(False), D.Target(True, u=-30, v=10, w=28, h=11)):
        enc = D.encode(t)
        assert enc["heat"].max() == 0 and enc["pos"] == 0 and enc["present"] == 0


@pytest.mark.parametrize(
    ("hflip", "vflip"), [(True, False), (False, True), (True, True)]
)
def test_flip_moves_the_fly_with_the_pixels(hflip: bool, vflip: bool) -> None:
    """The dark pixel and the target move together; one flip mirrors the angle."""
    canvas = np.full((P.CANVAS_H, P.CANVAS_W), 200, np.uint8)
    canvas[10, 50] = 0
    out, t = D.flip(canvas, D.Target(True, 50, 10, 28, 11, 30), hflip, vflip)
    v, u = np.unravel_index(out.argmin(), out.shape)
    assert (t.u, t.v) == (u, v)
    assert t.phi == (150 if hflip != vflip else 30)


def test_photometric_keeps_shape_and_dtype() -> None:
    """Augmented canvases stay uint8 canvases of the same size."""
    rng = np.random.default_rng(0)
    canvas = rng.integers(50, 200, (P.CANVAS_H, P.CANVAS_W)).astype(np.uint8)
    for _ in range(20):
        out = D.photometric(canvas, rng)
        assert out.shape == canvas.shape and out.dtype == np.uint8


def test_pack_and_items(packed: Path) -> None:
    """Every labelled tube of a snapshot comes out as one normalised canvas."""
    store = D.SnapshotStore(packed)
    labels = pd.read_parquet(packed / "labels.parquet")
    assert len(store.index) == 3 and labels.sid.notna().all()
    assert store.frame(1).shape == (960, 1280)
    # Reason: the synthetic snapshots are flat grey, so give every label contrast.
    rows = D.training_rows(labels.assign(contrast=50.0))
    ds = D.TubeDataset(store, rows, augment=False, p_swap=0.0)
    item = ds[0]
    assert item["x"].shape == (2, 1, P.CANVAS_H, P.CANVAS_W)
    assert torch.all(item["present"] == 1)
    batch = D.collate([ds[0], ds[1]])
    assert batch["x"].shape[0] == 4 and batch["heat"].shape == (4, D.OUT_H, D.OUT_W)
