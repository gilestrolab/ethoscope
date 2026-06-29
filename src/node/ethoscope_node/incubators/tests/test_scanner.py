"""Tests for the duplicated scanner module.

Mirror the existing Phase-1 tests in
``src/node/tests/unit/scanner/test_incubator_scanner.py`` so a regression in
the duplicated slice surfaces here as well as in the existing test path.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ethoscope_node.incubators.scanner import (
    INCUBATOR_PORT,
    Incubator,
    IncubatorScanner,
    ScanException,
)


class TestIncubator:
    def test_url_setup(self):
        inc = Incubator("192.168.1.50", port=80)
        assert inc._data_url == "http://192.168.1.50:80/telemetry"
        assert inc._health_url == "http://192.168.1.50:80/health"
        assert inc._id_url == inc._data_url

    @patch("urllib.request.urlopen")
    def test_update_info_parses_telemetry_and_derives_hostname(self, mock_urlopen):
        inc = Incubator("192.168.1.50")
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps(
            {
                "node_id": 4,
                "temperature": 22.4,
                "humidity": 55.0,
                "lux": 120,
                "set_temp": 22.0,
                "light_level": 100,
                "peltier_duty": -30,
                "peltier_dir": "cool",
                "fw": "3.2.0-wifi",
            }
        ).encode()
        mock_urlopen.return_value = resp

        inc._update_info()

        assert inc._info["temperature"] == 22.4
        assert inc._info["hostname"] == "incubator-4"
        assert inc._info["id"] == "incubator-4"
        assert inc.id() == "incubator-4"
        assert inc._device_status.status_name == "online"

    @patch("urllib.request.urlopen")
    def test_update_info_without_node_id_falls_back_to_ip(self, mock_urlopen):
        inc = Incubator("192.168.1.51")
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({"temperature": 21.0}).encode()
        mock_urlopen.return_value = resp

        inc._update_info()

        assert inc._info["hostname"] == "192.168.1.51"
        assert inc._device_status.status_name == "online"

    @patch("urllib.request.urlopen")
    def test_update_info_offline_on_failure(self, mock_urlopen):
        inc = Incubator("192.168.1.52")
        mock_urlopen.side_effect = OSError("unreachable")

        inc._update_info()

        assert inc._device_status.status_name == "offline"

    @patch("urllib.request.urlopen")
    def test_get_json_post_data_is_forwarded(self, mock_urlopen):
        """``_get_json(url, post_data=...)`` shape must match the legacy contract."""
        inc = Incubator("192.168.1.53")
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_urlopen.return_value = resp

        body = json.dumps({"location": "X"}).encode()
        result = inc._get_json("http://192.168.1.53/set", post_data=body)

        assert result == {"ok": True}
        request = mock_urlopen.call_args[0][0]
        assert request.data == body

    def test_empty_response_raises_scan_exception(self):
        inc = Incubator("192.168.1.54")
        with patch("urllib.request.urlopen") as mock_urlopen:
            resp = MagicMock()
            resp.__enter__.return_value = resp
            resp.read.return_value = b""
            mock_urlopen.return_value = resp
            with pytest.raises(ScanException, match="Empty response"):
                inc._get_json("http://192.168.1.54/telemetry")


class TestIncubatorScanner:
    def test_service_type_and_defaults(self):
        scanner = IncubatorScanner(results_dir="/tmp/inc")
        assert scanner.SERVICE_TYPE == "_incubator._tcp.local."
        assert scanner.DEVICE_TYPE == "incubator"
        assert scanner.device_refresh_period == 60
        assert scanner._device_class == Incubator
        assert scanner.results_dir == "/tmp/inc"

    def test_default_port_constant(self):
        assert INCUBATOR_PORT == 80

    def test_get_device_by_hostname_match(self):
        scanner = IncubatorScanner()
        device = MagicMock()
        device.info.return_value = {"hostname": "incubator-1"}
        with scanner._lock:
            scanner.devices.append(device)
        assert scanner.get_device_by_hostname("incubator-1") is device

    def test_get_device_by_hostname_miss(self):
        scanner = IncubatorScanner()
        assert scanner.get_device_by_hostname("incubator-99") is None

    def test_set_location_unknown_hostname_raises(self):
        scanner = IncubatorScanner()
        with pytest.raises(ValueError, match="No live incubator"):
            scanner.set_location("incubator-99", "Incubator 99")

    def test_set_location_posts_to_unit(self):
        scanner = IncubatorScanner()
        device = MagicMock()
        device.info.return_value = {"hostname": "incubator-2"}
        device.ip.return_value = "192.168.1.60"
        device._port = 80
        device._get_json.return_value = {"status": "ok"}
        with scanner._lock:
            scanner.devices.append(device)

        result = scanner.set_location("incubator-2", "Incubator 2")

        assert result == {"status": "ok"}
        called_url = device._get_json.call_args[0][0]
        assert called_url == "http://192.168.1.60:80/set"
        posted = json.loads(device._get_json.call_args[1]["post_data"].decode())
        assert posted == {"location": "Incubator 2"}

    def test_get_all_devices_info_skips_unidentified(self):
        scanner = IncubatorScanner()
        a = MagicMock()
        a.id.return_value = "incubator-1"
        a.info.return_value = {"hostname": "incubator-1", "temperature": 24}
        b = MagicMock()
        b.id.return_value = ""  # not yet identified
        with scanner._lock:
            scanner.devices.append(a)
            scanner.devices.append(b)
        info = scanner.get_all_devices_info()
        assert "incubator-1" in info
        assert "" not in info
        assert info["incubator-1"]["temperature"] == 24
