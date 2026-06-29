"""Tests for the framework-agnostic route handlers.

The handlers are exercised against in-memory ``SQLiteIncubatorStorage`` (so
the storage layer's SQL paths are also covered) with the scanner + firmware
client mocked. No HTTP framework involved here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ethoscope_node.incubators.firmware_client import IncubatorHTTPError
from ethoscope_node.incubators.routes import IncubatorRoutes
from ethoscope_node.incubators.schedule import build_firmware_payload
from ethoscope_node.incubators.storage import SQLiteIncubatorStorage


@pytest.fixture
def storage(tmp_path):
    return SQLiteIncubatorStorage(str(tmp_path / "routes.db"))


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def scanner():
    s = MagicMock()
    s.get_all_devices_info.return_value = {}
    return s


@pytest.fixture
def routes(storage, scanner, client):
    return IncubatorRoutes(storage, scanner, client)


def _bind_live_unit(scanner, *, hostname="incubator-1", ip="10.0.0.5", port=80):
    """Make the scanner pretend a unit at `hostname` is online at `ip`."""
    device = MagicMock()
    device.ip.return_value = ip
    device._port = port
    device.info.return_value = {"hostname": hostname, "status": "online"}
    scanner.get_device_by_hostname.side_effect = lambda h: (
        device if h == hostname else None
    )
    scanner.get_all_devices_info.return_value = {
        hostname: {
            "hostname": hostname,
            "ip": ip,
            "status": "online",
            "node_id": 1,
            **build_firmware_payload({"name": "x"}),
        }
    }
    return device


class TestAdd:
    def test_minimal(self, routes):
        result = routes.add({"name": "Inc1"})
        assert result["result"] == "success"
        assert result["pushed"] is False  # no hostname binding

    def test_missing_name_is_error(self, routes):
        result = routes.add({"location": "Room A"})
        assert result["result"] == "error"

    def test_with_bound_hostname_pushes(self, routes, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        result = routes.add(
            {
                "name": "Inc1",
                "hostname": "incubator-1",
                "lights_on": "09:00",
                "lights_off": "21:00",
            }
        )
        assert result["pushed"] is True
        client.push_config.assert_called_once()

    def test_ignores_unknown_fields(self, routes):
        result = routes.add({"name": "Inc1", "exotic_field": "x"})
        assert result["result"] == "success"


class TestUpdate:
    def test_basic(self, routes, storage):
        storage.add({"name": "Inc1", "location": "old"})
        result = routes.update("Inc1", {"location": "new"})
        assert result["result"] == "success"
        assert storage.get(name="Inc1")["location"] == "new"

    def test_missing_record_is_error(self, routes):
        result = routes.update("Nope", {"location": "X"})
        assert result["result"] == "error"

    def test_update_with_bound_hostname_pushes(self, routes, storage, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        result = routes.update("Inc1", {"lights_on": "10:00"})
        assert result["pushed"] is True
        client.push_config.assert_called_once()

    def test_unknown_field_does_not_crash(self, routes, storage):
        storage.add({"name": "Inc1"})
        result = routes.update("Inc1", {"surprise": 1, "location": "X"})
        assert result["result"] == "success"

    def test_rename_attempt_is_silently_dropped(self, routes, storage):
        # Renaming via update is not supported (see route docstring).
        storage.add({"name": "OldName"})
        result = routes.update("OldName", {"name": "NewName", "location": "X"})
        assert result["result"] == "success"
        # The other patch field still applied, but the row keeps its name.
        assert storage.get(name="OldName")["location"] == "X"
        assert storage.get(name="NewName") is None


class TestDelete:
    def test_existing(self, routes, storage):
        storage.add({"name": "Inc1"})
        result = routes.delete("Inc1")
        assert result["result"] == "success"
        assert storage.get(name="Inc1") is None

    def test_missing_returns_zero_rows(self, routes):
        result = routes.delete("Nope")
        assert result["result"] == "success"
        assert result["rows_affected"] == 0


class TestBind:
    def test_bind_online_unit_pushes_location_and_schedule(
        self, routes, storage, scanner, client
    ):
        device = _bind_live_unit(scanner, hostname="incubator-1")
        scanner.set_identity.return_value = {"status": "ok"}
        storage.add({"name": "Inc1", "lights_on": "09:00", "lights_off": "21:00"})

        result = routes.bind("Inc1", "incubator-1")

        assert result["result"] == "success"
        assert result["hostname"] == "incubator-1"
        assert result["location_pushed"] is True
        assert result["schedule_pushed"] is True
        scanner.set_identity.assert_called_once_with(
            "incubator-1", name="Inc1", location="Inc1"
        )
        assert client.push_config.call_count == 1
        assert storage.get(name="Inc1")["hostname"] == "incubator-1"
        assert device is not None  # bound to silence unused

    def test_unbind_clears_hostname(self, routes, storage, scanner):
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        result = routes.bind("Inc1", None)
        assert result["result"] == "success"
        assert result["hostname"] is None
        assert storage.get(name="Inc1")["hostname"] is None
        scanner.set_identity.assert_not_called()

    def test_push_identity_mirrors_name_to_unit(self, routes, storage, scanner):
        """push_identity sends the incubator name as the unit's sensor name+location."""
        _bind_live_unit(scanner, hostname="incubator-1")
        scanner.set_identity.return_value = {"status": "ok"}
        storage.add({"name": "Inc1", "hostname": "incubator-1"})

        assert routes.push_identity("Inc1") is True
        scanner.set_identity.assert_called_once_with(
            "incubator-1", name="Inc1", location="Inc1"
        )

    def test_push_identity_unbound_is_noop(self, routes, storage, scanner):
        storage.add({"name": "Inc1"})  # no hostname
        assert routes.push_identity("Inc1") is False
        scanner.set_identity.assert_not_called()

    def test_bind_missing_record_is_error(self, routes):
        result = routes.bind("Nope", "incubator-1")
        assert result["result"] == "error"

    def test_bind_offline_unit_does_not_crash(self, routes, storage, scanner):
        # Scanner returns no device for this hostname → schedule_pushed stays False.
        scanner.get_device_by_hostname.return_value = None
        storage.add({"name": "Inc1"})
        result = routes.bind("Inc1", "incubator-99")
        assert result["result"] == "success"
        assert result["schedule_pushed"] is False
        assert result["location_pushed"] is False


class TestPushSchedule:
    def test_pushes_when_bound_and_online(self, routes, storage, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        result = routes.push_schedule("Inc1")
        assert result["result"] == "success"
        client.push_config.assert_called_once()

    def test_unbound_returns_error(self, routes, storage):
        storage.add({"name": "Inc1"})
        result = routes.push_schedule("Inc1")
        assert result["result"] == "error"

    def test_offline_unit_returns_error(self, routes, storage, scanner):
        scanner.get_device_by_hostname.return_value = None
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        result = routes.push_schedule("Inc1")
        assert result["result"] == "error"

    def test_firmware_error_returns_error(self, routes, storage, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        client.push_config.side_effect = IncubatorHTTPError("boom")
        result = routes.push_schedule("Inc1")
        assert result["result"] == "error"


class TestResetAnchor:
    def test_stamps_now_and_pushes(self, routes, storage, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        result = routes.reset_anchor("Inc1")
        assert result["result"] == "success"
        rec = storage.get(name="Inc1")
        assert rec["light_cycle_anchor"] is not None
        client.push_config.assert_called_once()

    def test_missing_record_is_error(self, routes):
        result = routes.reset_anchor("Nope")
        assert result["result"] == "error"


class TestLightOverride:
    def test_calls_set_light_override(self, routes, storage, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        result = routes.light_override("Inc1", 50)
        assert result["result"] == "success"
        client.set_light_override.assert_called_once_with("10.0.0.5", 50, port=80)

    def test_unbound_is_error(self, routes, storage):
        storage.add({"name": "Inc1"})
        assert routes.light_override("Inc1", 50)["result"] == "error"

    def test_offline_is_error(self, routes, storage, scanner):
        scanner.get_device_by_hostname.return_value = None
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        assert routes.light_override("Inc1", 50)["result"] == "error"


class TestListMerged:
    def test_configured_only(self, routes, storage):
        storage.add({"name": "Inc1"})
        merged = routes.list_merged()
        assert "Inc1" in merged
        assert merged["Inc1"]["source"] == "configured"
        assert merged["Inc1"]["live_status"] == "unbound"

    def test_discovered_only(self, routes, scanner):
        scanner.get_all_devices_info.return_value = {
            "incubator-9": {
                "hostname": "incubator-9",
                "ip": "10.0.0.9",
                "status": "online",
            }
        }
        merged = routes.list_merged()
        assert "incubator-9" in merged
        assert merged["incubator-9"]["source"] == "discovered"

    def test_both(self, routes, storage, scanner):
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        scanner.get_all_devices_info.return_value = {
            "incubator-1": {
                "hostname": "incubator-1",
                "ip": "10.0.0.1",
                "status": "online",
                "temperature": 24.5,
            }
        }
        merged = routes.list_merged()
        assert merged["Inc1"]["source"] == "both"
        assert merged["Inc1"]["live_status"] == "online"
        assert merged["Inc1"]["temperature"] == 24.5

    def test_no_scanner(self, storage, client):
        routes = IncubatorRoutes(storage, scanner=None, client=client)
        storage.add({"name": "Inc1"})
        merged = routes.list_merged()
        assert merged["Inc1"]["source"] == "configured"


class TestGetTelemetry:
    def test_unbound_is_error(self, routes, storage):
        storage.add({"name": "Inc1"})
        assert routes.get_telemetry("Inc1")["result"] == "error"

    def test_passes_through_when_online(self, routes, storage, scanner, client):
        _bind_live_unit(scanner, hostname="incubator-1")
        storage.add({"name": "Inc1", "hostname": "incubator-1"})
        client.get_telemetry.return_value = {"temperature": 25.0}
        result = routes.get_telemetry("Inc1")
        assert result == {"temperature": 25.0}
