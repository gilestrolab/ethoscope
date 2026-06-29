"""Tests for the drift-detection reconciler.

Exercises ``run_once`` directly so we don't depend on the threading.Timer
cadence. Lifecycle (start/stop) is also covered with a short poll.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ethoscope_node.incubators.firmware_client import IncubatorHTTPError
from ethoscope_node.incubators.reconciler import Reconciler
from ethoscope_node.incubators.schedule import build_firmware_payload


def _matching_telemetry(record: dict) -> dict:
    """Telemetry that, by construction, reports the same schedule as `record`."""
    fw = build_firmware_payload(record)
    return {
        "status": "online",
        "ip": "10.0.0.5",
        "hostname": record["hostname"],
        **fw,
    }


def _drifted_telemetry(record: dict) -> dict:
    fw = build_firmware_payload(record)
    fw["lights_on"] = "10:00"  # different from the record's "09:00"
    return {
        "status": "online",
        "ip": "10.0.0.5",
        "hostname": record["hostname"],
        **fw,
    }


@pytest.fixture
def storage():
    storage = MagicMock()
    storage.list_all.return_value = {}
    return storage


@pytest.fixture
def scanner():
    scanner = MagicMock()
    scanner.get_all_devices_info.return_value = {}
    return scanner


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def reconciler(storage, scanner, client):
    return Reconciler(storage, scanner, client, interval_s=0.05)


class TestRunOnce:
    def _bound_record(self) -> dict:
        return {
            "name": "Inc1",
            "hostname": "incubator-1",
            "lights_on": "09:00",
            "lights_off": "21:00",
            "light_period_minutes": 1440,
            "light_cycle_anchor": None,
            "fade_in_seconds": 1,
            "fade_out_seconds": 1,
            "max_light": 100,
        }

    def test_no_devices_no_push(self, reconciler, client):
        reconciler.run_once()
        client.push_config.assert_not_called()

    def test_offline_device_skipped(self, reconciler, scanner, storage, client):
        scanner.get_all_devices_info.return_value = {
            "incubator-1": {"status": "offline", "hostname": "incubator-1"},
        }
        storage.list_all.return_value = {"Inc1": self._bound_record()}
        reconciler.run_once()
        client.push_config.assert_not_called()

    def test_unbound_device_skipped(self, reconciler, scanner, storage, client):
        rec = self._bound_record()
        scanner.get_all_devices_info.return_value = {
            "incubator-9": _matching_telemetry({**rec, "hostname": "incubator-9"})
        }
        storage.list_all.return_value = {}  # no record bound to incubator-9
        reconciler.run_once()
        client.push_config.assert_not_called()

    def test_no_drift_no_push(self, reconciler, scanner, storage, client):
        rec = self._bound_record()
        scanner.get_all_devices_info.return_value = {
            "incubator-1": _matching_telemetry(rec)
        }
        storage.list_all.return_value = {"Inc1": rec}
        reconciler.run_once()
        client.push_config.assert_not_called()

    def test_drift_triggers_push(self, reconciler, scanner, storage, client):
        rec = self._bound_record()
        scanner.get_all_devices_info.return_value = {
            "incubator-1": _drifted_telemetry(rec)
        }
        storage.list_all.return_value = {"Inc1": rec}
        pushed = reconciler.run_once()
        assert pushed == 1
        client.push_config.assert_called_once()
        ip_arg, payload_arg = client.push_config.call_args[0]
        assert ip_arg == "10.0.0.5"
        assert payload_arg == build_firmware_payload(rec)

    def test_http_failure_is_logged_not_raised(
        self, reconciler, scanner, storage, client, caplog
    ):
        import logging

        rec = self._bound_record()
        scanner.get_all_devices_info.return_value = {
            "incubator-1": _drifted_telemetry(rec)
        }
        storage.list_all.return_value = {"Inc1": rec}
        client.push_config.side_effect = IncubatorHTTPError("boom")

        with caplog.at_level(logging.WARNING):
            reconciler.run_once()

        assert any("push to incubator-1 failed" in m.lower() for m in caplog.messages)

    def test_telemetry_missing_ip_is_skipped(
        self, reconciler, scanner, storage, client
    ):
        rec = self._bound_record()
        tele = _drifted_telemetry(rec)
        tele.pop("ip")
        scanner.get_all_devices_info.return_value = {"incubator-1": tele}
        storage.list_all.return_value = {"Inc1": rec}
        reconciler.run_once()
        client.push_config.assert_not_called()

    def test_identity_drift_repushes_name(self, reconciler, scanner, storage, client):
        """A unit reporting a stale sensor name is re-synced to the record name."""
        rec = self._bound_record()
        tele = _matching_telemetry(rec)
        tele["name"] = "incubator-1"  # stale (renamed while offline)
        tele["location"] = "incubator-1"
        scanner.get_all_devices_info.return_value = {"incubator-1": tele}
        storage.list_all.return_value = {"Inc1": rec}
        reconciler.run_once()
        scanner.set_identity.assert_called_once_with(
            "incubator-1", name="Inc1", location="Inc1"
        )

    def test_identity_match_no_push(self, reconciler, scanner, storage, client):
        rec = self._bound_record()
        tele = _matching_telemetry(rec)
        tele["name"] = "Inc1"
        tele["location"] = "Inc1"
        scanner.get_all_devices_info.return_value = {"incubator-1": tele}
        storage.list_all.return_value = {"Inc1": rec}
        reconciler.run_once()
        scanner.set_identity.assert_not_called()

    def test_identity_absent_in_telemetry_skipped(
        self, reconciler, scanner, storage, client
    ):
        """Older firmware that omits name/location is left untouched."""
        rec = self._bound_record()
        scanner.get_all_devices_info.return_value = {
            "incubator-1": _matching_telemetry(rec)  # no name/location keys
        }
        storage.list_all.return_value = {"Inc1": rec}
        reconciler.run_once()
        scanner.set_identity.assert_not_called()


class TestLifecycle:
    def test_start_then_stop_is_idempotent(self, reconciler):
        reconciler.start()
        reconciler.start()  # second start is a no-op
        reconciler.stop()
        reconciler.stop()  # second stop is a no-op

    def test_timer_actually_fires(self, storage, scanner, client):
        rec = {
            "name": "Inc1",
            "hostname": "incubator-1",
            "lights_on": "09:00",
            "lights_off": "21:00",
            "light_period_minutes": 1440,
            "light_cycle_anchor": None,
            "fade_in_seconds": 1,
            "fade_out_seconds": 1,
            "max_light": 100,
        }
        scanner.get_all_devices_info.return_value = {
            "incubator-1": _drifted_telemetry(rec)
        }
        storage.list_all.return_value = {"Inc1": rec}
        reconciler = Reconciler(storage, scanner, client, interval_s=0.05)
        try:
            reconciler.start()
            # Wait long enough for at least one tick to fire.
            deadline = time.time() + 1.0
            while time.time() < deadline and not client.push_config.called:
                time.sleep(0.02)
            assert client.push_config.called
        finally:
            reconciler.stop()
