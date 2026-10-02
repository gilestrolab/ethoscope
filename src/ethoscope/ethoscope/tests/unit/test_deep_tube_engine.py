"""
Unit tests for the DeepTubeTracker engine: preprocessing, shake correction, batching.

The network itself is replaced by a fake whose outputs place each tube's fly where
the test wants it, except in the parity tests, which run the packaged model on a
stored frame and compare with what the training code produced
(``dl_tracking/device_reference.py``).
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ethoscope.trackers.deep_tube import engine
from ethoscope.trackers.deep_tube import preprocess as P

REFERENCE = Path(__file__).parents[1] / "static_files/deep_tube/reference_v5.npz"
TUBE = (100, 200, 560, 60)  # x, y, w, h of a typical tube ROI


def tube_rects(n=20):
    """``n`` tube rectangles in two columns of ten, like the 20-tube arena."""
    return [(30 + 620 * (k // 10), 140 + 64 * (k % 10), 560, 60) for k in range(n)]


class FakeNet:
    """A stand-in for ``cv2.dnn.Net`` whose fly positions are set per call."""

    def __init__(self, n):
        self.n = n
        self.calls = 0
        self.cells = [(4, 36)] * n  # (row, column) of each tube's peak cell
        self.offsets = np.full((n, 2), 0.5)  # sub-cell offset x, y
        self.presence = np.full(n, 6.0)  # logits; sigmoid(6) = 0.998

    def setInput(self, x):  # noqa: N802 (cv2 API)
        assert x.shape == (self.n, 1, P.CANVAS_H, P.CANVAS_W)
        assert x.dtype == np.float32

    def forward(self, names):
        assert names == ["maps", "presence"]
        self.calls += 1
        maps = np.zeros((self.n, 7, 8, 72), np.float32)
        maps[:, 0] = -10
        maps[:, 3], maps[:, 4] = np.log(28), np.log(11)
        maps[:, 6] = 1  # cos 2phi = 1: phi = 0
        for k, (i, j) in enumerate(self.cells):
            maps[k, 0, i, j] = 5
            maps[k, 1:3, i, j] = self.offsets[k]
        return maps, self.presence[:, None].astype(np.float32)

    def move(self, k, dx, dy):
        """Move tube ``k``'s fly by (dx, dy) full-resolution px (1 cell = 8 px)."""
        self.offsets[k] += (dx / 8, dy / 8)


def frame():
    return np.zeros((960, 1280), np.uint8)


class TestPreprocessCopy:
    """The device copy must turn a frame into exactly what the network trained on."""

    def test_canvas_and_frame_coordinates_round_trip(self):
        origin = P.canvas_origin(*TUBE)
        u, v = P.full_to_canvas(377.25, 231.5, origin)
        assert P.canvas_to_full(u, v, origin) == pytest.approx((377.25, 231.5))

    def test_a_canvas_is_centred_on_its_roi(self):
        cx0, cy0 = P.canvas_origin(*TUBE)
        assert 2 * (cx0 + P.CANVAS_W / 2) == pytest.approx(TUBE[0] + TUBE[2] / 2, abs=2)
        assert 2 * (cy0 + P.CANVAS_H / 2) == pytest.approx(TUBE[1] + TUBE[3] / 2, abs=2)

    def test_cut_pads_with_edge_pixels_outside_the_image(self):
        img = np.arange(20, dtype=np.uint8).reshape(4, 5)
        out = P.cut(img, -2, -1, 4, 3)
        assert out.shape == (3, 4)
        assert out[0, 0] == img[0, 0] and out[2, 3] == img[1, 1]

    def test_downsample_averages_two_by_two_blocks(self):
        img = np.random.default_rng(0).integers(0, 256, (8, 12)).astype(np.float32)
        expected = img.reshape(4, 2, 6, 2).mean(axis=(1, 3))
        assert np.allclose(P.downsample(img), expected, atol=1e-4)

    def test_normalise_matches_population_statistics(self):
        c = np.random.default_rng(1).integers(0, 256, (3, 32, 288)).astype(np.uint8)
        x = P.normalise(c)
        ref = (c - c.mean(axis=(1, 2), keepdims=True)) / (
            c.std(axis=(1, 2), keepdims=True) + 1
        )
        assert x.shape == (3, 1, 32, 288) and np.allclose(x[:, 0], ref, atol=1e-4)

    def test_decode_blends_a_tied_neighbour_half_way(self):
        maps = np.zeros((1, 7, 8, 72), np.float32)
        maps[0, 0] = -10
        maps[0, 0, 4, 36] = maps[0, 0, 4, 37] = 5  # a tie between two cells
        u = P.decode(maps, np.zeros((1, 1)))[0, 0]
        assert u == pytest.approx(4 * 36.5 - 0.5)

    def test_decode_ignores_a_neighbour_one_logit_below(self):
        maps = np.zeros((1, 7, 8, 72), np.float32)
        maps[0, 0] = -10
        maps[0, 0, 4, 36], maps[0, 0, 4, 37] = 5, 4
        assert P.decode(maps, np.zeros((1, 1)))[0, 0] == pytest.approx(4 * 36 - 0.5)


class TestSetupProblems:
    def test_the_20_tube_arena_at_1280x960_is_supported(self):
        rects = [(k + 1, *r) for k, r in enumerate(tube_rects())]
        assert engine.setup_problems((1280, 960), rects) == []

    def test_a_taller_tube_within_the_training_range_is_accepted(self):
        assert engine.setup_problems((1280, 960), [(1, 10, 10, 560, 70)]) == []

    @pytest.mark.parametrize(
        "frame_size,rect,word",
        [
            ((640, 480), (1, 10, 10, 280, 30), "640x480"),
            ((1280, 960), (1, 10, 10, 1110, 60), "larger"),
            ((1280, 960), (1, 10, 10, 200, 60), "tube-shaped"),
        ],
    )
    def test_unsupported_setups_are_explained(self, frame_size, rect, word):
        problems = engine.setup_problems(frame_size, [rect])
        assert len(problems) == 1 and word in problems[0]


class TestCorrectedSteps:
    def still(self, n=20, shift=0j):
        disp = np.full(n, shift)
        return disp, np.ones(n, bool)

    def test_a_whole_image_shift_is_not_movement(self):
        disp, consecutive = self.still(shift=0.2j)
        assert np.allclose(engine.corrected_steps(disp, consecutive), 0)

    def test_a_walking_fly_keeps_its_step_under_a_small_shift(self):
        disp, consecutive = self.still(shift=0.2j)
        disp[3] += 3
        steps = engine.corrected_steps(disp, consecutive)
        assert steps[3] == pytest.approx(3) and np.allclose(np.delete(steps, 3), 0)

    def test_a_large_shift_leaves_no_step_trusted(self):
        disp, consecutive = self.still(shift=1.2j)
        disp[3] += 3
        assert np.allclose(engine.corrected_steps(disp, consecutive), 0)

    def test_with_too_few_tubes_nothing_is_corrected(self):
        disp, consecutive = self.still(n=4, shift=0.2j)
        assert np.allclose(engine.corrected_steps(disp, consecutive), 0.2)

    def test_many_flies_walking_at_once_are_kept(self):
        rng = np.random.default_rng(2)
        disp, consecutive = self.still()
        disp[:9] = 3 * np.exp(1j * rng.uniform(0, 2 * np.pi, 9))
        steps = engine.corrected_steps(disp, consecutive)
        assert np.all(steps[:9] > 2.5) and np.allclose(steps[9:], 0, atol=0.5)

    def test_a_tube_back_from_a_gap_does_not_vote(self):
        disp, consecutive = self.still(shift=0.2j)
        disp[0], consecutive[0] = 5 + 0.2j, False
        steps = engine.corrected_steps(disp, consecutive)
        assert steps[0] == pytest.approx(abs(5 + 0.2j))

    def test_tubes_without_a_fly_stay_nan(self):
        disp, consecutive = self.still()
        disp[2] = complex(np.nan, np.nan)
        assert np.isnan(engine.corrected_steps(disp, consecutive)[2])


class TestBatchLocator:
    def make(self, n=20):
        net = FakeNet(n)
        return engine.BatchLocator(tube_rects(n), net=net), net

    def test_one_network_pass_serves_every_tube_of_a_frame(self):
        loc, net = self.make()
        f = frame()
        dets = [loc.get(0, f, k) for k in range(20)]
        assert net.calls == 1 and all(d is not None for d in dets)

    def test_a_new_frame_with_the_same_time_is_still_a_new_frame(self):
        loc, net = self.make()
        loc.get(0, frame(), 0)
        loc.get(0, frame(), 0)  # a video camera stamps frames 0 and 1 with t = 0
        assert net.calls == 2

    def test_positions_are_relative_to_the_roi_rectangle(self):
        loc, net = self.make(n=1)
        d = loc.get(0, frame(), 0)
        cx0, cy0 = P.canvas_origin(*tube_rects(1)[0])
        u, v = 4 * (36 + 0.5) - 0.5, 4 * (4 + 0.5) - 0.5
        x, y = P.canvas_to_full(u, v, (cx0, cy0))
        assert (d.x, d.y) == pytest.approx((x - 30, y - 140))
        assert (d.w, d.h, d.phi) == pytest.approx((28, 11, 0))

    def test_the_first_detection_has_no_step_and_a_move_has_its_length(self):
        loc, net = self.make()
        assert loc.get(0, frame(), 5).step == 0
        net.move(5, 3, 0)
        assert loc.get(200, frame(), 5).step == pytest.approx(3, abs=1e-6)

    def test_camera_shake_is_removed_from_every_step(self):
        loc, net = self.make()
        loc.get(0, frame(), 0)
        for k in range(20):
            net.move(k, 0, 0.25)  # the camera moved; the flies did not
        net.move(7, 2, 0)  # and one fly walked
        f = frame()
        steps = [loc.get(200, f, k).step for k in range(20)]
        assert steps[7] == pytest.approx(2, abs=1e-6)
        assert np.allclose(np.delete(steps, 7), 0, atol=1e-6)

    def test_an_absent_fly_is_none_and_its_return_spans_the_gap(self):
        loc, net = self.make()
        loc.get(0, frame(), 2)
        net.presence[2] = -6
        assert loc.get(200, frame(), 2) is None
        net.presence[2] = 6
        net.move(2, 4, 0)
        assert loc.get(400, frame(), 2).step == pytest.approx(4, abs=1e-6)

    def test_a_frame_of_the_wrong_size_is_refused(self):
        loc, _ = self.make()
        with pytest.raises(ValueError, match="1280x960"):
            loc.get(0, np.zeros((480, 640), np.uint8), 0)


class TestPackagedModel:
    def test_the_card_matches_the_file_and_this_code(self):
        card = json.loads(engine.MODEL_CARD.read_text())
        onnx = engine.MODEL_CARD.parent / card["file"]
        assert hashlib.sha256(onnx.read_bytes()).hexdigest() == card["sha256"]
        net, loaded = engine.load_model()
        assert loaded["name"] == card["name"]

    def test_a_tampered_card_is_refused(self, tmp_path):
        card = json.loads(engine.MODEL_CARD.read_text())
        (tmp_path / card["file"]).write_bytes(b"not a model")
        (tmp_path / "card.json").write_text(json.dumps(card))
        with pytest.raises(ValueError, match="checksum"):
            engine.load_model(tmp_path / "card.json")

    def test_describe_names_the_model_and_the_shake_rule(self):
        info = json.loads(engine.describe(json.loads(engine.MODEL_CARD.read_text())))
        assert info["model"] == "fly_locator_tiny_s2_v5"
        assert info["shake_correction"] == {"min_rois": 5, "gate_px": 0.3}
        assert info["threads"] == engine.THREADS

    def test_the_network_runs_on_two_threads(self):
        """At 5 fps 2 threads keep up even throttled, without 4 threads' current spikes."""
        import cv2

        before = cv2.getNumThreads()
        try:
            engine.BatchLocator(tube_rects(2))
            assert cv2.getNumThreads() == engine.THREADS == 2
        finally:
            cv2.setNumThreads(before)


class TestParityWithTraining:
    """The device path reproduces the training code's output on a real frame."""

    @pytest.fixture(scope="class")
    def ref(self):
        return dict(np.load(REFERENCE))

    def test_canvases_are_identical(self, ref):
        origins = [P.canvas_origin(*map(int, r[1:])) for r in ref["rects"]]
        assert np.array_equal(
            P.canvases_from_frame(ref["frame"], origins), ref["canvases"]
        )

    def test_decoding_is_identical(self, ref):
        # Reason: within float rounding, not bit for bit. The reference was made on
        # another machine, and numpy's exp/arctan2 differ in the last bits between
        # builds (CI failed an exact comparison). The peak cell must agree exactly.
        decoded = P.decode(ref["maps"], ref["presence"])
        assert np.array_equal(decoded[:, 7], ref["decoded"][:, 7])
        np.testing.assert_allclose(decoded, ref["decoded"], rtol=1e-6, atol=1e-6)

    def test_the_packaged_model_finds_the_same_flies(self, ref):
        rects = [tuple(map(int, r[1:])) for r in ref["rects"]]
        loc = engine.BatchLocator(rects)
        dets = [loc.get(0, ref["frame"], k) for k in range(len(rects))]
        origins = np.array([P.canvas_origin(*r) for r in rects], float)
        dec = ref["decoded"]
        x = 2 * (dec[:, 0] + origins[:, 0]) + 0.5 - ref["rects"][:, 1]
        y = 2 * (dec[:, 1] + origins[:, 1]) + 0.5 - ref["rects"][:, 2]
        assert np.allclose([d.x for d in dets], x, atol=0.05)
        assert np.allclose([d.y for d in dets], y, atol=0.05)
        assert np.allclose([d.presence for d in dets], dec[:, 6], atol=1e-3)
