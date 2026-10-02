"""DeepTubeTracker: the learned per-tube fly locator as an ethoscope tracker.

Each tube's position comes from a small neural network (``dl_tracking/``) that runs,
batched over all the tubes of a frame, in OpenCV's ``cv2.dnn``. Its output has the
same variables, in the same order, as :class:`AdaptiveBGModel`'s, so result writers,
drawers, stimulators and the analysis downstream need no change.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from math import log10

from ethoscope.core.data_point import DataPoint
from ethoscope.core.variables import (
    HeightVariable,
    PhiVariable,
    WidthVariable,
    XPosVariable,
    XYDistance,
    YPosVariable,
)
from ethoscope.trackers.deep_tube import engine
from ethoscope.trackers.trackers import BaseTracker, NoPositionError

SMALLINT = (-32768, 32767)  # every variable is stored as one


def _smallint(value: float) -> int:
    """Round to the nearest integer within the SMALLINT range."""
    return int(min(max(round(value), SMALLINT[0]), SMALLINT[1]))


def movement(step: float, long_side: int) -> int:
    """
    Encode a step as ``xy_dist_log10x1000``, exactly as AdaptiveBGModel does.

    ``log10(1/L + step/L)`` with ``L`` the ROI's long side: the fraction of the tube
    moved, floored at one pixel, so the stimulators' threshold keeps its meaning.

    Args:
        step (float): Displacement in px.
        long_side (int): The ROI crop's longest side, px.

    Returns:
        int: The stored value.
    """
    return _smallint(1000 * log10((1.0 + step) / long_side))


@dataclass
class SharedState:
    """What the trackers of one Monitor share: the batch locator and their slots."""

    locator: engine.BatchLocator
    slots: dict[int, int]  # id(roi) -> index in the locator's ROI list


class DeepTubeTracker(BaseTracker):
    _description = {
        "overview": (
            "A learned fly locator (a small neural network) for tube arenas. "
            "Sub-pixel positions with little jitter on still flies, robust to "
            "lighting, and it keeps finding dead or immobile flies. One animal per "
            "tube; 20-tube arenas at 1280x960 only."
        ),
        "arguments": [],
    }

    @classmethod
    def make_shared_state(cls, rois: list) -> SharedState:
        """
        Build the state the trackers of one Monitor share (called once per Monitor).

        Args:
            rois (list): Every ROI of the experiment, in tracking order.

        Returns:
            SharedState: One locator for all of them.
        """
        locator = engine.BatchLocator([r.rectangle for r in rois])
        return SharedState(locator, {id(r): k for k, r in enumerate(rois)})

    @classmethod
    def check_setup(cls, frame_size: tuple[int, int], rois: list) -> str | None:
        """
        Tell, before an experiment starts, whether the model can track this setup.

        Args:
            frame_size (tuple[int, int]): Camera frame ``(width, height)``.
            rois (list): The experiment's ROIs.

        Returns:
            str | None: Why the setup is not supported, or None if it is.
        """
        rects = [(r.idx, *r.rectangle) for r in rois]
        problems = engine.setup_problems(frame_size, rects)
        if not problems:
            return None
        return "DeepTubeTracker cannot track this setup: " + "; ".join(problems)

    @classmethod
    def model_info(cls) -> str:
        """
        Describe the model for the experiment's METADATA.

        Returns:
            str: JSON (model name and checksum, OpenCV version and threads, rules).
        """
        return engine.describe(json.loads(engine.MODEL_CARD.read_text()))

    def __init__(self, roi, data=None, shared_state: SharedState | None = None):
        """
        Track one tube.

        Args:
            roi: The tube's ROI.
            data: Unused; kept for the BaseTracker signature.
            shared_state (SharedState | None): Given by the Monitor
                (:meth:`make_shared_state`). Without it the tracker runs the
                network on its own tube only and cannot correct camera shake.
        """
        super().__init__(roi, data)
        if shared_state is None:
            logging.warning(
                "DeepTubeTracker for ROI %s built outside a Monitor: one network pass "
                "per tube and no camera-shake correction",
                roi.idx,
            )
            shared_state = self.make_shared_state([roi])
        self._shared = shared_state
        self._slot = shared_state.slots[id(roi)]
        self._frame = None
        self._long_side = max(roi.rectangle[2], roi.rectangle[3])

    def track(self, t, img):
        """Keep the whole frame at hand for the batch, then track as usual."""
        self._frame = img
        try:
            return super().track(t, img)
        finally:
            self._frame = None

    def _find_position(self, img, mask, t):
        det = self._shared.locator.get(t, self._frame, self._slot)
        if det is None:
            raise NoPositionError
        h_im, w_im = img.shape[:2]
        self._long_side = max(w_im, h_im)
        x = min(max(det.x, 0.0), w_im - 1)
        y = min(max(det.y, 0.0), h_im - 1)
        w, h, phi = det.w, det.h, det.phi
        if w < h:  # AdaptiveBGModel reports the long axis as w
            w, h, phi = h, w, (phi + 90) % 180
        return [
            DataPoint(
                [
                    XPosVariable(_smallint(x)),
                    YPosVariable(_smallint(y)),
                    WidthVariable(_smallint(w)),
                    HeightVariable(_smallint(h)),
                    PhiVariable(_smallint(phi)),
                    XYDistance(movement(det.step, self._long_side)),
                ]
            )
        ]

    def _infer_position(self, t, max_time=30 * 1000):
        """
        Repeat the last position while the fly is briefly lost, as a still fly.

        Reason: BaseTracker repeats the last DataPoint object itself, movement value
        included, so a lost fly read as moving for up to 30 s, and marking the repeat
        inferred also rewrote the original row.
        """
        points = []
        for p in super()._infer_position(t, max_time):
            q = p.copy()
            q.append(XYDistance(movement(0.0, self._long_side)))
            points.append(q)
        return points
