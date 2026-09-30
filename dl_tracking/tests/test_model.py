"""Tests for the network, the canvas geometry and the ONNX export."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from dl_tracking import export as E
from dl_tracking import model as M
from dl_tracking import preprocess as P


@pytest.mark.parametrize("variant", list(M.VARIANTS))
def test_variants_fit_the_pi_budget(variant: str) -> None:
    """Every variant is under ~6.2 M MACs per tube and sees ~130 full-res px."""
    net = M.build(variant)
    assert M.count_macs(net, P.CANVAS_H, P.CANVAS_W) <= 6.2e6
    assert M.receptive_field(net) >= 60
    maps, pres = net(torch.zeros(3, 1, P.CANVAS_H, P.CANVAS_W))
    assert maps.shape == (3, M.N_MAPS, P.CANVAS_H // P.STRIDE, P.CANVAS_W // P.STRIDE)
    assert pres.shape == (3, 1)


def test_coordinates_round_trip() -> None:
    """Frame -> canvas -> frame is the identity, for any ROI."""
    origin = P.canvas_origin(41, 205, 553, 67)
    for x, y in [(41.0, 205.0), (300.25, 240.5), (593.0, 271.0)]:
        u, v = P.full_to_canvas(x, y, origin)
        assert P.canvas_to_full(u, v, origin) == pytest.approx((x, y))


def test_canvases_pad_by_replication_at_the_frame_edge() -> None:
    """Inside the frame a canvas is the half-res image; outside, its edge repeats."""
    frame = np.random.default_rng(0).integers(0, 255, (960, 1280), dtype=np.uint8)
    half = P.downsample(frame)
    inner = P.canvas_origin(41, 205, 553, 67)
    got = P.canvases_from_frame(frame, [inner, P.canvas_origin(0, 0, 560, 60)])
    cx, cy = inner
    assert np.array_equal(got[0], half[cy : cy + P.CANVAS_H, cx : cx + P.CANVAS_W])
    edge = got[1]  # origin (-4, -1): 4 replicated columns, 1 replicated row
    assert np.array_equal(edge[1:, 4], half[: P.CANVAS_H - 1, 0])
    assert np.array_equal(edge[1:, 0], edge[1:, 4]) and np.array_equal(edge[0], edge[1])


def test_downsample_centre_convention() -> None:
    """A dark 2x2 block at full-res (100..101, 50..51) lands at its mapped centre."""
    frame = np.full((960, 1280), 200, np.uint8)
    frame[50:52, 100:102] = 0
    origin = P.canvas_origin(0, 0, 560, 60)
    half = P.canvases_from_frame(frame, [origin])[0].astype(float)
    v, u = np.unravel_index(half.argmin(), half.shape)
    assert (u, v) == pytest.approx(P.full_to_canvas(100.5, 50.5, origin))


def test_normalise_is_per_canvas() -> None:
    """Brightness and contrast changes vanish; a flat canvas stays near zero."""
    rng = np.random.default_rng(1)
    base = rng.integers(60, 120, (P.CANVAS_H, P.CANVAS_W)).astype(np.float32)
    a, b = P.normalise(np.stack([base, 2 * base + 30]))[:, 0]
    assert np.abs(a - b).max() < 0.05
    flat = P.normalise(np.full((1, 8, 8), 17.0))
    assert np.abs(flat).max() == 0


def test_decode_reads_the_peak_cell() -> None:
    """The argmax cell plus its offset gives the canvas position."""
    maps = np.full((1, M.N_MAPS, 8, 72), -9.0, np.float32)
    maps[0, 0, 3, 40] = 5.0
    maps[0, 1:3, 3, 40] = (0.25, 0.75)
    maps[0, 3:5, 3, 40] = np.log([28.0, 11.0])
    maps[0, 5:7, 3, 40] = (np.sin(np.radians(60)), np.cos(np.radians(60)))
    out = P.decode(maps, np.array([[3.0]]))[0]
    assert out[0] == pytest.approx(4 * 40.25 - 0.5) and out[1] == pytest.approx(
        4 * 3.75 - 0.5
    )
    assert out[2:5] == pytest.approx([28, 11, 30])
    assert out[5] > 0.99 and out[6] > 0.95


def test_fold_batchnorm_preserves_outputs() -> None:
    """Folding BN into the convolutions changes nothing numerically."""
    net = M.build("tiny")
    net.train()
    with torch.no_grad():  # give BN non-trivial statistics
        for _ in range(3):
            net(torch.randn(16, 1, P.CANVAS_H, P.CANVAS_W))
    net.eval()
    x = torch.randn(4, 1, P.CANVAS_H, P.CANVAS_W)
    with torch.no_grad():
        ref, folded = net(x), E.fold_batchnorm(net)(x)
    assert torch.allclose(ref[0], folded[0], atol=1e-4)
    assert torch.allclose(ref[1], folded[1], atol=1e-4)


def test_onnx_parity_with_cv2_dnn(tmp_path: Path) -> None:
    """cv2.dnn runs the export, at the training width and at a 10-tube width."""
    net = M.build("tiny")
    net.train()
    with torch.no_grad():
        for _ in range(3):
            net(torch.randn(16, 1, P.CANVAS_H, P.CANVAS_W))
    path = E.export(net.eval(), tmp_path / "m.onnx")
    rng = np.random.default_rng(2)
    for width in (P.CANVAS_W, 2 * P.CANVAS_W):
        x = rng.normal(size=(20, 1, P.CANVAS_H, width)).astype(np.float32)
        res = E.parity(net, path, x)
        assert res["max_abs_maps"] < 1e-3 and res["max_abs_presence"] < 1e-3
        assert res["n_decisive"] > 0 and res["argmax_agree"] == 1.0
