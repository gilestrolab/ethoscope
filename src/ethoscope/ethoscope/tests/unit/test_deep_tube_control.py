"""
Unit tests for offering DeepTubeTracker in the start dialog and refusing setups it cannot track.

The start path is driven through a stand-in ControlThread that has only what
``_set_tracking_from_scratch`` touches before the database is created, with the
repository's 20-tube test video as the camera.
"""

import tempfile
from collections import OrderedDict
from pathlib import Path

import pytest

from ethoscope.control import tracking
from ethoscope.control.tracking import ControlThread
from ethoscope.drawers.drawers import NullDrawer
from ethoscope.hardware.input.cameras import MovieVirtualCamera
from ethoscope.roi_builders.file_based_roi_builder import FileBasedROIBuilder
from ethoscope.stimulators.stimulators import DefaultStimulator
from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel
from ethoscope.trackers.deep_tube import DeepTubeTracker

VIDEO = Path(__file__).parents[1] / "static_files/videos/arena_10x2_sortTubes.mp4"


@pytest.fixture
def production_pi(monkeypatch):
    """A Pi with a camera that is not flagged experimental."""
    monkeypatch.setattr(ControlThread, "_is_a_rPi", True)
    monkeypatch.setattr(tracking.pi, "isExperimental", lambda: False)


class TestOffered:
    def test_a_production_pi_offers_both_trackers_default_first(self, production_pi):
        offered = ControlThread.user_options()["tracker"]
        assert [o["name"] for o in offered] == ["AdaptiveBGModel", "DeepTubeTracker"]
        assert "tube" in offered[1]["overview"] and offered[1]["arguments"] == []

    def test_the_camera_stays_hidden_on_a_production_pi(self, production_pi):
        assert "camera" not in ControlThread.user_options()

    def test_a_start_request_naming_it_resolves(self):
        Class, kwargs = ControlThread._parse_one_user_option(
            ControlThread,
            "tracker",
            {"tracker": {"name": "DeepTubeTracker", "arguments": {}}},
        )
        assert Class is DeepTubeTracker and kwargs == {}

    def test_without_a_choice_the_default_is_adaptivebgmodel(self):
        assert (
            ControlThread._option_dict["tracker"]["possible_classes"][0]
            is AdaptiveBGModel
        )


class StartStandIn(ControlThread):
    """Just enough of a ControlThread to reach the tracker's setup check."""

    def __init__(self, tracker_class):
        self._info = {}
        self._roi_build_error = None
        self._tmp_dir = tempfile.mkdtemp(prefix="test_deep_tube_control_")
        self.released = []
        self._option_dict = OrderedDict(
            (k, dict(v)) for k, v in ControlThread._option_dict.items()
        )
        choose = {
            "camera": (MovieVirtualCamera, {"path": str(VIDEO)}),
            "roi_builder": (
                FileBasedROIBuilder,
                {"template_name": "sleep_monitor_20tube"},
            ),
            "tracker": (tracker_class, {}),
            "drawer": (NullDrawer, {}),
            "interactor": (DefaultStimulator, {}),
        }
        for key, (cls, kwargs) in choose.items():
            self._option_dict[key]["class"], self._option_dict[key]["kwargs"] = (
                cls,
                kwargs,
            )

    def _force_lights_on_for_targets(self):
        pass

    def _release_lights_after_targets(self):
        pass

    def _release_camera_after_failed_start(self, cam):
        self.released.append(cam)
        cam._close()

    def stop(self, error=None):
        pass


class Refusing(DeepTubeTracker):
    _description = {"overview": "test", "arguments": []}

    @classmethod
    def check_setup(cls, frame_size, rois):
        return (
            f"DeepTubeTracker cannot track this setup: {len(rois)} ROIs at {frame_size}"
        )


class TestRefusal:
    def test_an_unsupported_setup_stops_before_anything_is_written(self):
        thread = StartStandIn(Refusing)
        assert thread._set_tracking_from_scratch() is None
        assert thread._roi_build_error.startswith("DeepTubeTracker cannot track")
        assert "20 ROIs at (1280, 960)" in thread._roi_build_error
        assert len(thread.released) == 1  # the camera is free for the next attempt

    def test_the_test_video_passes_the_real_check(self):
        cam = MovieVirtualCamera(str(VIDEO))
        _, rois = FileBasedROIBuilder(template_name="sleep_monitor_20tube").build(cam)
        assert DeepTubeTracker.check_setup(cam.resolution, rois) is None
        cam._close()
