"""
Unit tests for incubator_scanner module.

Covers the Incubator device's telemetry parsing / hostname derivation and the
IncubatorScanner configuration (service type, refresh period, location push).
"""

import json
from unittest.mock import MagicMock, patch

from ethoscope_node.scanner.incubator_scanner import Incubator, IncubatorScanner


class TestIncubator:
    """Test the Incubator device class."""

    def test_url_setup(self):
        """Incubator polls /telemetry and /health."""
        inc = Incubator("192.168.1.50", port=80)
        assert inc._data_url == "http://192.168.1.50:80/telemetry"
        assert inc._health_url == "http://192.168.1.50:80/health"
        # _id_url points at telemetry (identity comes from node_id there)
        assert inc._id_url == inc._data_url

    @patch("urllib.request.urlopen")
    def test_update_info_parses_telemetry_and_derives_hostname(self, mock_urlopen):
        """A successful /telemetry poll is stored and keyed by incubator-<id>."""
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
                "mode": "LD",
                "light_level": 100,
                "peltier_duty": -30,
                "peltier_dir": "cool",
                "fw": "3.1.0-wifi",
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
    def test_update_info_without_node_id_falls_back(self, mock_urlopen):
        """If node_id is missing, hostname falls back to the IP (still keyed)."""
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
        """A failed poll resets the device to offline."""
        inc = Incubator("192.168.1.52")
        mock_urlopen.side_effect = OSError("unreachable")

        inc._update_info()

        assert inc._device_status.status_name == "offline"


class TestIncubatorScanner:
    """Test the IncubatorScanner class."""

    def test_service_type_and_defaults(self):
        scanner = IncubatorScanner(results_dir="/tmp/inc")
        assert scanner.SERVICE_TYPE == "_incubator._tcp.local."
        assert scanner.DEVICE_TYPE == "incubator"
        assert scanner.device_refresh_period == 60
        assert scanner._device_class == Incubator
        assert scanner.results_dir == "/tmp/inc"

    def test_set_location_unknown_hostname_raises(self):
        """Pushing a location to an unknown unit is an error, not a silent no-op."""
        scanner = IncubatorScanner()
        try:
            scanner.set_location("incubator-99", "Incubator 99")
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_set_location_posts_to_unit(self):
        """set_location POSTs {'location': name} to the matching unit's /set."""
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
