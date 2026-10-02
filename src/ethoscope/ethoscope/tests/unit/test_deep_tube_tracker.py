"""
Unit tests for DeepTubeTracker: its rows, its handling of lost flies, and the Monitor hook.

The network is replaced by a fake that puts every tube's fly at the same canvas
position, with a presence the test controls, so the tests run without the model and
say exactly what each tracker should report.
"""

from math import log10
from unittest.mock import Mock

import numpy as np
import pytest

from ethoscope.core.monitor import Monitor
from ethoscope.core.roi import ROI
from ethoscope.core.variables import (
    HeightVariable,
    PhiVariable,
    WidthVariable,
    XPosVariable,
    XYDistance,
    YPosVariable,
)
from ethoscope.trackers.deep_tube import DeepTubeTracker, engine, tracker
from ethoscope.trackers.trackers import BaseTracker

FRAME = np.zeros((960, 1280), np.uint8)


class FakeNet:
    """Every canvas holds a fly at cell (4, 36) unless ``presence`` says otherwise."""

    def __init__(self):
        self.presence_logit = 6.0
        self.size = (np.log(28), np.log(11))
        self.calls = 0

    def setInput(self, x):  # noqa: N802 (cv2 API)
        self.n = len(x)

    def forward(self, names):
        self.calls += 1
        maps = np.zeros((self.n, 7, 8, 72), np.float32)
        maps[:, 0] = -10
        maps[:, 0, 4, 36] = 5
        maps[:, 1:3, 4, 36] = 0.5
        maps[:, 3], maps[:, 4] = self.size
        maps[:, 6] = 1
        return maps, np.full((self.n, 1), self.presence_logit, np.float32)


@pytest.fixture
def net(monkeypatch):
    fake = FakeNet()
    monkeypatch.setattr(engine, "load_model", lambda *a, **k: (fake, {"name": "fake"}))
    return fake


def tube(idx, x=30, y=140, w=560, h=60):
    return ROI(np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]), idx)


def arena(n=20):
    return [tube(k + 1, 30 + 620 * (k // 10), 140 + 64 * (k % 10)) for k in range(n)]


class TestRows:
    def test_a_row_has_adaptivebgmodels_variables_in_its_order(self, net):
        rows = DeepTubeTracker(tube(1)).track(0, FRAME)
        assert len(rows) == 1
        assert list(rows[0].keys()) == [
            "x", "y", "w", "h", "phi", "xy_dist_log10x1000", "is_inferred",
        ]  # fmt: skip
        types = [XPosVariable, YPosVariable, WidthVariable, HeightVariable,
                 PhiVariable, XYDistance]  # fmt: skip
        assert [type(v) for v in list(rows[0].values())[:6]] == types

    def test_the_long_axis_is_reported_as_width(self, net):
        net.size = (np.log(11), np.log(28))
        row = DeepTubeTracker(tube(1)).track(0, FRAME)[0]
        assert (row["w"], row["h"], row["phi"]) == (28, 11, 90)

    def test_a_still_fly_reports_the_one_pixel_floor(self, net):
        trk = DeepTubeTracker(tube(1))
        trk.track(0, FRAME)
        row = trk.track(200, FRAME.copy())[0]
        long_side = max(trk._roi.rectangle[2:])
        assert row["xy_dist_log10x1000"] == round(1000 * log10(1 / long_side))

    def test_movement_is_encoded_as_adaptivebgmodel_does(self):
        assert tracker.movement(1.5, 561) == round(1000 * log10(2.5 / 561))
        assert tracker.movement(1e40, 561) == 32767  # clamped to SMALLINT


class TestLostFly:
    def test_no_fly_and_no_history_gives_no_row(self, net):
        net.presence_logit = -6
        assert DeepTubeTracker(tube(1)).track(0, FRAME) == []

    def test_a_briefly_lost_fly_is_inferred_still_without_touching_its_last_row(
        self, net
    ):
        trk = DeepTubeTracker(tube(1))
        trk.track(0, FRAME)
        first = trk.track(200, FRAME.copy())[0]
        first_value = int(first["xy_dist_log10x1000"])
        net.presence_logit = -6
        inferred = trk.track(400, FRAME.copy())[0]
        assert inferred["is_inferred"] == 1
        assert inferred["x"] == first["x"]
        assert inferred["xy_dist_log10x1000"] == tracker.movement(0, 561)
        assert inferred is not first and first["is_inferred"] == 0
        assert int(first["xy_dist_log10x1000"]) == first_value

    def test_after_30_seconds_a_lost_fly_has_no_row(self, net):
        trk = DeepTubeTracker(tube(1))
        trk.track(0, FRAME)
        net.presence_logit = -6
        assert trk.track(31_000, FRAME.copy()) == []


class TestMonitorHook:
    def test_one_shared_state_serves_every_tube(self, net):
        mon = Monitor(Mock(), DeepTubeTracker, arena())
        shared = {id(u.tracker._shared) for u in mon._unit_trackers}
        assert len(shared) == 1
        slots = [u.tracker._slot for u in mon._unit_trackers]
        assert slots == list(range(20))

    def test_a_frame_runs_the_network_once(self, net):
        mon = Monitor(Mock(), DeepTubeTracker, arena())
        for u in mon._unit_trackers:
            assert u.track(0, FRAME)
        assert net.calls == 1

    def test_trackers_without_the_hook_get_no_extra_argument(self):
        class Plain(BaseTracker):
            def __init__(self, roi, data=None):
                super().__init__(roi, data)

            def _find_position(self, img, mask, t):
                return []

        mon = Monitor(Mock(), Plain, arena(2))
        assert len(mon._unit_trackers) == 2

    def test_outside_a_monitor_a_tracker_runs_alone_and_says_so(self, net, caplog):
        trk = DeepTubeTracker(tube(3))
        assert "outside a Monitor" in caplog.text
        assert trk._slot == 0 and trk.track(0, FRAME)


class TestSetupCheck:
    def test_the_arena_passes(self):
        assert DeepTubeTracker.check_setup((1280, 960), arena()) is None

    def test_a_small_camera_is_refused_in_words(self):
        msg = DeepTubeTracker.check_setup((640, 480), arena())
        assert (
            msg.startswith("DeepTubeTracker cannot track this setup")
            and "640x480" in msg
        )
