"""Tests for resolving which incubator each ethoscope is in."""

from __future__ import annotations

from ethoscope_node.utils.device_locations import (
    CURRENT,
    LAST_RUN,
    PREVIOUS,
    resolve_device_location,
    resolve_device_locations,
)


def running_device(location="Incubator_4A", run_id="run-1", user="lguo"):
    return {
        "name": "ETHOSCOPE_354",
        "status": "running",
        "experimental_info": {
            "current": {"location": location, "run_id": run_id, "name": user},
            "previous": {"location": "Incubator_9A", "date_time": 1_780_000_000.0},
        },
    }


def stopped_device(location="Incubator_5A", when=1_782_740_672.0):
    return {
        "name": "ETHOSCOPE_025",
        "status": "stopped",
        "experimental_info": {
            "current": {},
            "previous": {"location": location, "date_time": when, "user": "gg"},
        },
    }


def offline_device():
    """An offline device reports no experimental_info at all."""
    return {"name": "ETHOSCOPE_130", "status": "offline"}


class TestSingleDevice:
    def test_running_device_uses_its_current_location(self):
        placement = resolve_device_location(running_device(), None)
        assert placement["incubator"] == "Incubator_4A"
        assert placement["source"] == CURRENT
        assert placement["user"] == "lguo"

    def test_current_location_wins_over_everything_else(self):
        last_run = {"location": "Incubator_1A", "since": 1.0, "run_id": "old"}
        assert resolve_device_location(running_device(), last_run)["incubator"] == (
            "Incubator_4A"
        )

    def test_current_placement_is_dated_from_the_matching_run(self):
        last_run = {
            "location": "Incubator_4A",
            "since": 1_787_000_000.0,
            "run_id": "run-1",
        }
        assert resolve_device_location(running_device(), last_run)["since"] == (
            1_787_000_000.0
        )

    def test_current_placement_is_undated_when_the_run_does_not_match(self):
        """Edge case: the newest recorded run is not the one now running."""
        last_run = {
            "location": "Incubator_4A",
            "since": 1_787_000_000.0,
            "run_id": "other",
        }
        assert resolve_device_location(running_device(), last_run)["since"] is None

    def test_stopped_device_falls_back_to_its_previous_run(self):
        placement = resolve_device_location(stopped_device(), None)
        assert placement["incubator"] == "Incubator_5A"
        assert placement["source"] == PREVIOUS
        assert placement["since"] == 1_782_740_672.0
        assert placement["user"] == "gg"

    def test_offline_device_falls_back_to_the_runs_table(self):
        last_run = {
            "location": "Incubator_2A",
            "since": 1_780_000_000.0,
            "user": "lguo",
            "run_id": "r9",
        }
        placement = resolve_device_location(offline_device(), last_run)
        assert placement["incubator"] == "Incubator_2A"
        assert placement["source"] == LAST_RUN
        assert placement["since"] == 1_780_000_000.0

    def test_device_that_never_ran_anywhere_is_unplaced(self):
        placement = resolve_device_location(offline_device(), None)
        assert placement == {
            "incubator": None,
            "source": None,
            "since": None,
            "user": "",
        }

    def test_blank_locations_are_not_placements(self):
        """Failure case: an empty or whitespace location must not place a device."""
        device = {"experimental_info": {"current": {"location": "   "}}}
        assert resolve_device_location(device, None)["incubator"] is None

    def test_unparseable_previous_timestamp_degrades_to_no_date(self):
        device = stopped_device(when="not-a-time")
        placement = resolve_device_location(device, None)
        assert placement["incubator"] == "Incubator_5A"
        assert placement["since"] is None

    def test_location_is_stripped(self):
        device = stopped_device(location="  Incubator_5A  ")
        assert resolve_device_location(device, None)["incubator"] == "Incubator_5A"


class TestWholeFleet:
    def test_every_device_is_listed_including_unplaced_ones(self):
        devices = {
            "d1": running_device(),
            "d2": stopped_device(),
            "d3": offline_device(),
        }
        resolved = resolve_device_locations(devices, {})
        assert set(resolved) == {"d1", "d2", "d3"}
        assert resolved["d3"]["incubator"] is None
        assert resolved["d3"]["status"] == "offline"
        assert resolved["d1"]["name"] == "ETHOSCOPE_354"

    def test_runs_table_places_the_offline_ones(self):
        devices = {"d3": offline_device()}
        last_runs = {"d3": {"location": "Incubator_2A", "since": 1.0, "user": "gg"}}
        resolved = resolve_device_locations(devices, last_runs)
        assert resolved["d3"]["incubator"] == "Incubator_2A"
        assert resolved["d3"]["source"] == LAST_RUN

    def test_empty_inputs_are_tolerated(self):
        assert resolve_device_locations({}, {}) == {}
        assert resolve_device_locations(None, None) == {}

    def test_device_id_is_the_fallback_name(self):
        resolved = resolve_device_locations({"d9": {}}, {})
        assert resolved["d9"]["name"] == "d9"
        assert resolved["d9"]["status"] == "unknown"
