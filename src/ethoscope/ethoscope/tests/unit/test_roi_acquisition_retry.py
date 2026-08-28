#!/usr/bin/env python3
"""
Unit tests for resampling the camera when the targets are not found.

``build()`` used to pull six frames, collapse them to one median image, and hand
that single image to the detector. The detector's own three "attempts" then ran
against that same collapsed image, varying only the threshold and averaging it
with a stale copy of itself. So the camera was sampled once: a fly parked on a
target, or a transient reflection, failed the whole run with no way to recover.

Measured over 197 archive frames carrying recorded target coordinates, the
detector refuses 65, and running it again on a *different* frame of the same
arena resolves 27 of them. It is the same detector throughout, so precision is
unchanged; only the input improves.
"""

import numpy as np
import pytest

from ethoscope.roi_builders.roi_builders import BaseROIBuilder
from ethoscope.utils.debug import EthoscopeException


class _Camera:
    """Yields a different frame each time it is iterated."""

    def __init__(self, n_frames=200):
        self.n_frames = n_frames
        self.grabs = 0

    def __iter__(self):
        for _ in range(self.n_frames):
            self.grabs += 1
            yield 0, np.full((16, 16, 3), self.grabs % 256, dtype=np.uint8)


class _Builder(BaseROIBuilder):
    """Succeeds only on the nth call to _rois_from_img."""

    def __init__(self, succeed_on=1, raise_instead=False):
        self.calls = 0
        self.succeed_on = succeed_on
        self.raise_instead = raise_instead
        self.seen = []

    def _rois_from_img(self, img):
        self.calls += 1
        self.seen.append(float(np.median(img)))
        if self.calls >= self.succeed_on:
            roi = type("R", (), {"value": 1, "idx": 1})()
            return np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32), [roi]
        if self.raise_instead:
            raise EthoscopeException("insufficient targets detected")
        return None, None

    def _value_sorting(self, rois):
        return rois

    def _spatial_sorting(self, rois):
        return rois


class TestResampling:
    def test_a_failed_pass_takes_fresh_frames(self):
        """Regression: every retry used to see the same collapsed image."""
        cam = _Camera()
        b = _Builder(succeed_on=3)

        ref, rois = b.build(cam)

        assert ref is not None and len(rois) == 1
        assert b.calls == 3, "should have retried until it succeeded"
        assert len(set(b.seen)) == 3, f"retries saw the same image: {b.seen}"

    def test_it_gives_up_after_the_configured_passes(self):
        cam = _Camera()
        b = _Builder(succeed_on=999)

        with pytest.raises(EthoscopeException):
            b.build(cam)

        assert b.calls == BaseROIBuilder._MAX_ACQUISITION_PASSES

    def test_an_exception_from_the_detector_also_retries(self):
        """A raised failure and a None return mean the same thing here."""
        cam = _Camera()
        b = _Builder(succeed_on=2, raise_instead=True)

        ref, _ = b.build(cam)

        assert ref is not None and b.calls == 2

    def test_success_on_the_first_pass_costs_nothing_extra(self):
        """The common case must not pay for the retry path."""
        cam = _Camera()
        b = _Builder(succeed_on=1)

        b.build(cam)

        assert b.calls == 1
        assert cam.grabs == 6, "should sample six frames and stop"

    def test_a_plain_image_gets_exactly_one_attempt(self):
        """With a single image there is nothing else to sample, so do not loop."""
        b = _Builder(succeed_on=999)

        with pytest.raises(EthoscopeException):
            b.build(np.zeros((16, 16, 3), dtype=np.uint8))

        assert b.calls == 1

    def test_an_empty_camera_fails_without_looping_forever(self):
        b = _Builder(succeed_on=999)

        with pytest.raises(EthoscopeException):
            b.build(_Camera(n_frames=0))

        assert b.calls == 0
