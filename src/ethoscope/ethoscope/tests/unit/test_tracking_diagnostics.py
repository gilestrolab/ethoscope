#!/usr/bin/env python3
"""
Unit tests for the acquisition-quality diagnostics sampled during tracking.

Three quantities are measured (issue #222):

* **image noise** - how far the current ROI deviates from the background model,
  in grey levels. The candidate *cause* of centroid jitter.
* **sharpness** - variance of the Laplacian. The other candidate cause: a
  defocused blob has soft edges, so its centroid wanders even in a clean image.
* **jitter** - a low quantile of the per-frame displacements already recorded by
  the tracker. The *effect*: this is the noise floor of the movement signal, in
  the same units as the movement threshold, and it is what gets misread as
  movement by sleep scoring.

Measuring both causes alongside the effect is what makes "which one dominates"
a question the data can answer.
"""

from collections import deque
from unittest.mock import Mock

import numpy as np
import pytest

from ethoscope.core.monitor import Monitor


def _point(distance_fraction, is_inferred=False):
    """A recorded position with a given per-frame displacement."""
    return {
        "xy_dist_log10x1000": int(round(np.log10(distance_fraction) * 1000)),
        "is_inferred": int(is_inferred),
    }


def _tracker_with_displacements(distances, inferred=()):
    """A stand-in tracker exposing a rolling history like the real one."""
    tracker = Mock()
    tracker.positions = deque(
        [[_point(d)] for d in distances] + [[_point(d, True)] for d in inferred]
    )
    return tracker


def test_jitter_is_the_low_quantile_of_displacement():
    """The floor is the quiet tail, not the mean: a walk must not raise it."""
    # 100 quiescent frames at 0.001 ROI widths, plus 20 frames of real walking.
    quiet = [0.001] * 100
    walking = [0.05] * 20

    jitter = Monitor._roi_jitter(_tracker_with_displacements(quiet + walking))

    assert jitter == pytest.approx(0.001, rel=0.2)


def test_jitter_tracks_a_noisier_tracker():
    """A noisier image floor produces a proportionally higher jitter."""
    quiet_jitter = Monitor._roi_jitter(_tracker_with_displacements([0.001] * 100))
    noisy_jitter = Monitor._roi_jitter(_tracker_with_displacements([0.004] * 100))

    assert noisy_jitter > quiet_jitter * 3


def test_inferred_positions_are_excluded():
    """Inference repeats the previous displacement, so it is not a measurement.

    Including inferred points would bias the floor with values that were never
    observed - the artefact behind the ghost movement bouts in issue #224.
    """
    # 100 genuine quiet frames, plus 100 inferred ones repeating a large value.
    tracker = _tracker_with_displacements([0.001] * 100, inferred=[0.05] * 100)

    assert Monitor._roi_jitter(tracker) == pytest.approx(0.001, rel=0.2)


def test_jitter_needs_enough_samples():
    """Too short a history reports nothing rather than a meaningless number."""
    assert Monitor._roi_jitter(_tracker_with_displacements([0.001] * 5)) is None


def test_jitter_survives_a_malformed_history():
    """A diagnostic must never raise into the tracking loop."""
    broken = Mock()
    broken.positions = [[{"unexpected": 1}]] * 50

    assert Monitor._roi_jitter(broken) is None


def test_sharpness_separates_focused_from_blurred():
    """A defocused frame must score lower than a sharp one."""
    rng = np.random.default_rng(0)
    sharp = rng.integers(0, 255, (200, 200), dtype=np.uint8)
    # Same image, blurred: the Laplacian variance must collapse.
    import cv2

    blurred = cv2.GaussianBlur(sharp, (15, 15), 0)

    assert Monitor._frame_sharpness(sharp) > Monitor._frame_sharpness(blurred) * 5


def test_sharpness_handles_a_missing_frame():
    """No frame is not an error."""
    assert Monitor._frame_sharpness(None) is None


def test_image_noise_measures_deviation_from_the_background():
    """Noise is the median deviation of the ROI from the background model."""
    from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel

    tracker = AdaptiveBGModel.__new__(AdaptiveBGModel)
    background = np.full((50, 50), 100, dtype=np.float32)
    # Every pixel sits 4 grey levels above the background.
    tracker._last_grey = np.full((50, 50), 104, dtype=np.uint8)
    tracker._bg_model = Mock()
    tracker._bg_model.bg_img = background

    assert tracker.image_noise() == pytest.approx(4.0)


def test_image_noise_ignores_the_animal():
    """A small dark blob must not move the number: the statistic is a median."""
    from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel

    tracker = AdaptiveBGModel.__new__(AdaptiveBGModel)
    grey = np.full((50, 50), 102, dtype=np.uint8)
    grey[20:24, 20:24] = 0  # the animal, ~0.6% of the ROI
    tracker._last_grey = grey
    tracker._bg_model = Mock()
    tracker._bg_model.bg_img = np.full((50, 50), 100, dtype=np.float32)

    assert tracker.image_noise() == pytest.approx(2.0)


def test_tracking_unit_exposes_its_tracker():
    """The diagnostics reach the tracker through TrackingUnit.tracker.

    Regression: the collector was written against Mock(tracker=...), which
    fabricated the attribute. On real hardware TrackingUnit exposed only `roi`
    and `stimulator`, so every ROI raised AttributeError and every sample came
    back empty. Assert against the real class, not a mock of it.
    """
    from ethoscope.core.roi import ROI
    from ethoscope.core.tracking_unit import TrackingUnit
    from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel

    unit = TrackingUnit(
        AdaptiveBGModel,
        ROI(polygon=((0, 0), (10, 0), (10, 10), (0, 10)), idx=1, value=1),
        None,
    )

    assert isinstance(unit.tracker, AdaptiveBGModel)
    assert hasattr(unit.tracker, "image_noise")


def _monitor_with(trackers):
    """A Monitor with its tracking units replaced, bypassing ROI setup."""
    monitor = Monitor.__new__(Monitor)
    monitor._unit_trackers = [Mock(tracker=t) for t in trackers]
    monitor._diagnostics = {}
    monitor._last_diagnostics_t = None
    return monitor


def test_collect_aggregates_across_rois():
    """The reported figures are medians across ROIs, so one bad ROI cannot swing them."""
    trackers = []
    for _ in range(5):
        tracker = _tracker_with_displacements([0.001] * 100)
        tracker.image_noise.return_value = 2.0
        trackers.append(tracker)
    # One ROI is wildly off; the median must ignore it.
    outlier = _tracker_with_displacements([0.5] * 100)
    outlier.image_noise.return_value = 99.0
    trackers.append(outlier)

    monitor = _monitor_with(trackers)
    monitor._collect_diagnostics(1000, np.zeros((20, 20), dtype=np.uint8))

    assert monitor.diagnostics["image_noise"] == pytest.approx(2.0)
    assert monitor.diagnostics["jitter"] == pytest.approx(0.001, rel=0.2)
    assert monitor.diagnostics["n_rois_sampled"] == 6
    assert monitor.diagnostics["t"] == 1000


def test_collect_never_raises_into_the_tracking_loop():
    """An exploding tracker degrades the diagnostics, not the experiment."""
    exploding = Mock()
    type(exploding).positions = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    exploding.image_noise.side_effect = RuntimeError("boom")

    monitor = _monitor_with([exploding])
    monitor._collect_diagnostics(1000, np.zeros((20, 20), dtype=np.uint8))

    assert monitor.diagnostics["image_noise"] is None
    assert monitor.diagnostics["jitter"] is None


def test_image_noise_is_none_before_the_background_converges():
    """No background model yet means no measurement, not a crash."""
    from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel

    tracker = AdaptiveBGModel.__new__(AdaptiveBGModel)
    tracker._last_grey = np.zeros((10, 10), dtype=np.uint8)
    tracker._bg_model = Mock()
    tracker._bg_model.bg_img = None

    assert tracker.image_noise() is None
