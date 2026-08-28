"""
Unit tests for the last-known-run history the scanner keeps per device.

``experimental_info.previous`` is where the greyed-out "last known user" and
"last known location" on the home page come from. The scanner maintains it: a
device reports a flat block while it is busy, the scanner files it under
``current``, and promotes it to ``previous`` when the device goes back to
"stopped".

Streaming broke that. A stream is started with a fully defaulted
ExperimentalInformation - no user, no location, but light-schedule defaults
(period 1440, max_light 100) that leave the dict non-empty - so the promotion's
``if current:`` guard passed and a real user and incubator were overwritten with
blanks. A minute of debugging through the camera cost the device its history.

These tests pin that a stream leaves the history alone while a real run still
replaces it.
"""

from unittest.mock import patch

import pytest

from ethoscope_node.scanner.ethoscope_scanner import Ethoscope

# What the device reports while streaming: every ExperimentalInformation field at
# its default. Note the non-empty numeric defaults - this dict is truthy.
STREAM_INFO = {
    "name": "",
    "location": "",
    "code": "",
    "sensor": "",
    "lights_on": "",
    "lights_off": "",
    "light_period_minutes": 1440,
    "light_cycle_anchor": "",
    "fade_in_seconds": 1,
    "fade_out_seconds": 1,
    "max_light": 100,
    "crepuscular": 0,
}

# What the node had recorded from the last real experiment, as the device cache
# spells it.
LAST_RUN = {
    "date_time": 1783347118.2222233,
    "backup_filename": "2026-07-06_14-11-58_025.db",
    "user": "lguo",
    "location": "Incubator_5A",
}


@pytest.fixture
def device():
    with (
        patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB"),
        patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration"),
    ):
        yield Ethoscope("192.168.1.100")


class TestNamesAnExperiment:
    def test_a_stream_names_nothing(self):
        """The whole point: truthy, but it identifies no run."""
        assert STREAM_INFO
        assert Ethoscope._names_an_experiment(STREAM_INFO) is False

    @pytest.mark.parametrize(
        "info",
        [
            {"name": "lguo", "location": ""},
            {"name": "", "location": "Incubator_5A"},
            {"name": "lguo", "location": "Incubator_5A"},
        ],
    )
    def test_a_user_or_a_place_is_enough(self, info):
        assert Ethoscope._names_an_experiment(info) is True

    @pytest.mark.parametrize("info", [{}, None, "not a dict", []])
    def test_anything_else_names_nothing(self, info):
        assert Ethoscope._names_an_experiment(info) is False


class TestStreamingLeavesTheHistoryAlone:
    def test_a_stopped_stream_does_not_become_the_previous_run(self, device):
        """Regression: this replaced lguo / Incubator_5A with blanks."""
        device._info = {
            "status": "streaming",
            "experimental_info": {
                "current": dict(STREAM_INFO),
                "previous": dict(LAST_RUN),
            },
        }
        # The device blanks experimental_info when a stream stops, so nothing
        # comes in with the poll that reports "stopped".
        new_info = {"status": "stopped", "experimental_info": {}}

        device._reorganize_experimental_info(new_info)

        assert new_info["experimental_info"]["previous"] == LAST_RUN
        assert new_info["experimental_info"]["current"] == {}

    def test_the_same_holds_when_the_device_still_reports_the_stream(self, device):
        """Older firmware keeps sending the flat block on the stopping poll."""
        device._info = {
            "status": "streaming",
            "experimental_info": {
                "current": dict(STREAM_INFO),
                "previous": dict(LAST_RUN),
            },
        }
        new_info = {"status": "stopped", "experimental_info": dict(STREAM_INFO)}

        device._reorganize_experimental_info(new_info)

        assert new_info["experimental_info"]["previous"] == LAST_RUN
        assert new_info["experimental_info"]["current"] == {}

    def test_a_running_stream_does_not_touch_previous_either(self, device):
        device._info = {
            "status": "stopped",
            "experimental_info": {"current": {}, "previous": dict(LAST_RUN)},
        }
        new_info = {"status": "streaming", "experimental_info": dict(STREAM_INFO)}

        device._reorganize_experimental_info(new_info)

        assert new_info["experimental_info"]["previous"] == LAST_RUN
        assert new_info["experimental_info"]["current"] == STREAM_INFO


class TestRealRunsStillReplaceTheHistory:
    @pytest.mark.parametrize("busy_status", ["running", "recording"])
    def test_a_finished_run_becomes_the_previous_one(self, device, busy_status):
        """The behaviour the promotion exists for, unchanged."""
        finished = dict(STREAM_INFO, name="ggilestro", location="Incubator_2B")
        device._info = {
            "status": busy_status,
            "experimental_info": {"current": finished, "previous": dict(LAST_RUN)},
        }
        new_info = {"status": "stopped", "experimental_info": {}}

        device._reorganize_experimental_info(new_info)

        assert new_info["experimental_info"]["previous"] == finished
        assert new_info["experimental_info"]["current"] == {}

    def test_a_run_with_only_a_location_still_counts(self, device):
        """The interface asks for both, but one is enough to be worth keeping."""
        finished = dict(STREAM_INFO, location="Incubator_2B")
        device._info = {
            "status": "running",
            "experimental_info": {"current": finished, "previous": dict(LAST_RUN)},
        }
        new_info = {"status": "stopped", "experimental_info": {}}

        device._reorganize_experimental_info(new_info)

        assert new_info["experimental_info"]["previous"] == finished
