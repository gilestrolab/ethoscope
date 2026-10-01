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
    assert set(D.training_rows(labels).status) == {"confident"}  # gap fills off
    rows = D.training_rows(labels, use_gapfill=True)
    assert sorted(zip(rows.status, rows.contrast, strict=True)) == [
        ("confident", 60),
        ("confident", 60),
        ("gapfill", 12),
        ("gapfill", 30),
    ]
    assert rows[rows.status == "gapfill"].shape_ok.eq(False).all()


def test_training_rows_drops_flat_canvases() -> None:
    """A label on a canvas that shows nothing is not a training example."""
    labels = pd.DataFrame(
        [label_row("confident", 60, roi=1), label_row("confident", 60, roi=2)]
    )
    std = pd.DataFrame({"sid": [0, 0], "roi_idx": [1, 2], "canvas_std": [25.0, 0.8]})
    assert D.training_rows(labels, canvas_std=std).roi_idx.tolist() == [1]


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


def test_match_gain_recovers_gain_and_offset() -> None:
    """A known gain and offset is undone; a flat source keeps unit gain."""
    rng = np.random.default_rng(3)
    src = rng.integers(40, 200, (32, 20)).astype(np.uint8)
    dst = np.clip(1.3 * src.astype(float) - 10, 0, 255)
    a, b = D.match_gain(src, dst)
    assert a == pytest.approx(1.3, abs=0.01) and b == pytest.approx(-10, abs=1.5)
    a, b = D.match_gain(
        np.full((32, 20), 90, np.uint8), np.full((32, 20), 100, np.uint8)
    )
    assert (a, b) == (1.0, 10.0)


def test_items_survive_flat_canvases(packed: Path) -> None:
    """Swaps between flat (featureless) snapshots never raise."""
    store = D.SnapshotStore(packed)
    rows = D.training_rows(
        pd.read_parquet(packed / "labels.parquet").assign(contrast=50.0)
    )
    ds = D.TubeDataset(store, rows, augment=True, p_swap=1.0)
    for k in range(len(ds)):
        assert ds[k]["x"].shape[1:] == (1, P.CANVAS_H, P.CANVAS_W)


def test_canvas_contrast_measures_every_labelled_canvas(packed: Path) -> None:
    """One spread per labelled canvas; the synthetic snapshots are flat."""
    std = D.canvas_contrast(packed, workers=1)
    labels = pd.read_parquet(packed / "labels.parquet")
    assert len(std) == len(labels) and (std.canvas_std < D.MIN_CANVAS_STD).all()
    assert (packed / "canvas_std.parquet").exists()


def test_train_cli_runs_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One epoch through train.main(): catches options parsed but not wired up."""
    import sys

    from dl_tracking import extract
    from dl_tracking import train as T

    from .conftest import make_db, still_rows

    monkeypatch.setattr(extract, "TMP_DIR", tmp_path)
    out = tmp_path / "out"
    for mid in ("abc", "def"):
        path = tmp_path / "src" / mid / "E1" / "2020-01-01_00-00-00" / "r.db"
        make_db(
            path,
            {
                1: still_rows(0, 1_200_000, 1000, 100, 30),
                2: still_rows(0, 1_200_000, 1000, 300, 30),
            },
            [700_000, 800_000, 900_000],
        )
        extract.extract_run(
            {"path": str(path), "machine_id": mid, "run_dt": "2020-01-01_00-00-00"}, out
        )
    D.pack(out)
    runs = pd.DataFrame(
        {
            "machine_id": ["abc", "def"],
            "split": ["train", "val"],
            "run_dt": ["2020-01-01_00-00-00"] * 2,
        }
    )
    runs.to_parquet(tmp_path / "runs.parquet")
    run = tmp_path / "run"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "train",
            "--pack",
            str(out / "pack"),
            "--runs",
            str(tmp_path / "runs.parquet"),
            "--out",
            str(run),
            "--epochs",
            "1",
            "--workers",
            "0",
            "--snapshots-per-batch",
            "2",
            "--variant",
            "tiny_s2",
            "--human",
            str(tmp_path / "no_human_labels.parquet"),
        ],
    )
    T.main()
    assert (run / "best.pt").exists() and (run / "final.json").exists()
