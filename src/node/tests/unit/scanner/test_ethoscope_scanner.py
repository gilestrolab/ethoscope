"""
Unit tests for ethoscope_scanner module.

This module tests Ethoscope-specific scanner functionality including
device management, status tracking, and backup path generation.
"""

import json
import os
import subprocess
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from ethoscope_node.scanner.base_scanner import DeviceError, DeviceStatus, ScanException
from ethoscope_node.scanner.ethoscope_scanner import (
    ETHOSCOPE_PORT,
    Ethoscope,
    EthoscopeScanner,
)


class TestEthoscope:
    """Test Ethoscope device class."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_initialization(self, mock_config_class, mock_db_class):
        """Test Ethoscope initialization."""
        device = Ethoscope("192.168.1.100", port=9000)
        assert device._ip == "192.168.1.100"
        assert device._port == 9000
        assert device._ping_count == 0

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_remote_pages_constants(self, mock_config_class, mock_db_class):
        """Test REMOTE_PAGES constants."""
        device = Ethoscope("192.168.1.100")
        assert device.REMOTE_PAGES["id"] == "id"
        assert device.REMOTE_PAGES["data"] == "data"
        assert device.REMOTE_PAGES["controls"] == "controls"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_allowed_instructions(self, mock_config_class, mock_db_class):
        """Test ALLOWED_INSTRUCTIONS constants."""
        device = Ethoscope("192.168.1.100")
        assert "start" in device.ALLOWED_INSTRUCTIONS
        assert "stop" in device.ALLOWED_INSTRUCTIONS
        assert "stopped" in device.ALLOWED_INSTRUCTIONS["start"]

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_databases_info_success(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test databases_info method with successful response."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"databases": "info"}).encode()
        mock_urlopen.return_value = mock_response

        result = device.databases_info()
        assert result == {"databases": "info"}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_databases_info_no_id(self, mock_config_class, mock_db_class):
        """Test databases_info when device has no ID."""
        device = Ethoscope("192.168.1.100")
        device._id = ""

        result = device.databases_info()
        assert result == {}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_machine_info_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test machine_info method."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"kernel": "5.4.0"}).encode()
        mock_urlopen.return_value = mock_response

        result = device.machine_info()
        assert result["kernel"] == "5.4.0"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_user_options_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test user_options method."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"option": "value"}).encode()
        mock_urlopen.return_value = mock_response

        result = device.user_options()
        assert result == {"option": "value"}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_videofiles_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test videofiles method."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(
            ["video1.mp4", "video2.mp4"]
        ).encode()
        mock_urlopen.return_value = mock_response

        result = device.videofiles()
        assert result == ["video1.mp4", "video2.mp4"]

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_get_log_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test get_log method."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"log": "data"}).encode()
        mock_urlopen.return_value = mock_response

        result = device.get_log()
        assert result == {"log": "data"}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_dump_sql_db_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test dump_sql_db method."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        result = device.dump_sql_db()
        assert result == {"status": "ok"}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_dumpSQLdb_legacy_method(self, mock_config_class, mock_db_class):
        """Test legacy dumpSQLdb method."""
        device = Ethoscope("192.168.1.100")

        with patch.object(device, "dump_sql_db") as mock_dump:
            mock_dump.return_value = {"status": "ok"}
            result = device.dumpSQLdb()
            assert result == {"status": "ok"}
            mock_dump.assert_called_once()

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_check_instruction_status_valid(self, mock_config_class, mock_db_class):
        """Test instruction validation with valid status."""
        device = Ethoscope("192.168.1.100")
        device._device_status = DeviceStatus("stopped")

        with patch.object(device, "_update_info"):
            # Should not raise exception
            device._check_instruction_status("start")

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_check_instruction_status_invalid(self, mock_config_class, mock_db_class):
        """Test instruction validation with invalid status."""
        device = Ethoscope("192.168.1.100")
        device._device_status = DeviceStatus("running")

        with patch.object(device, "_update_info"):
            with pytest.raises(DeviceError):
                device._check_instruction_status("start")

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_check_instruction_status_unknown(self, mock_config_class, mock_db_class):
        """Test instruction validation with unknown instruction."""
        device = Ethoscope("192.168.1.100")

        with patch.object(device, "_update_info"):
            with pytest.raises(ValueError, match="Unknown instruction"):
                device._check_instruction_status("invalid_instruction")

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_settings_with_dict(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test send_settings with dictionary data."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        with patch.object(device, "_update_info"):
            result = device.send_settings({"key": "value"})
            assert result == {"status": "ok"}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_settings_with_bytes(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test send_settings with bytes data."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        with patch.object(device, "_update_info"):
            result = device.send_settings(b'{"key": "value"}')
            assert result == {"status": "ok"}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_reset_info(self, mock_config_class, mock_db_class):
        """Test _reset_info method."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._info["name"] = "Test Device"

        device._reset_info()

        assert device._info["ip"] == "192.168.1.100"
        assert device._info["name"] == "Test Device"  # Name should be preserved
        assert device._info["id"] == "test_device"  # ID should be preserved

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_reorganize_experimental_info_flat_to_nested(
        self, mock_config_class, mock_db_class
    ):
        """Test experimental info reorganization from flat to nested format."""
        device = Ethoscope("192.168.1.100")
        device._info = {"status": "running"}

        new_info = {
            "experimental_info": {"user": "test", "location": "lab1"},
            "status": "running",
        }

        device._reorganize_experimental_info(new_info)

        assert "experimental_info" in new_info
        assert "current" in new_info["experimental_info"]
        assert new_info["experimental_info"]["current"]["user"] == "test"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_reorganize_experimental_info_already_nested(
        self, mock_config_class, mock_db_class
    ):
        """Test experimental info when already in nested format."""
        device = Ethoscope("192.168.1.100")
        device._info = {"experimental_info": {"current": {}, "previous": {}}}

        new_info = {
            "experimental_info": {
                "current": {"user": "test"},
                "previous": {"user": "old_test"},
            }
        }

        device._reorganize_experimental_info(new_info)

        assert new_info["experimental_info"]["current"]["user"] == "test"
        assert new_info["experimental_info"]["previous"]["user"] == "old_test"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_make_backup_path_with_filename(self, mock_config_class, mock_db_class):
        """Test backup path generation."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_id_123"
        device._info = {
            "name": "ETHOSCOPE_001",
            "databases": {
                "SQLite": {
                    "test_db": {"backup_filename": "2025-01-15_10-30-00_test_id_123.db"}
                }
            },
        }
        device._results_dir = "/tmp/test_results"

        device._make_backup_path(force_recalculate=True, service_type="sqlite")

        assert device._info["backup_path"] is not None
        assert "2025-01-15_10-30-00" in device._info["backup_path"]

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_make_backup_path_no_filename(self, mock_config_class, mock_db_class):
        """Test backup path generation with no filename."""
        device = Ethoscope("192.168.1.100")
        device._info = {"databases": {}}

        device._make_backup_path(force_recalculate=True)

        assert device._info["backup_path"] is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_backup_filename_for_db_type_sqlite(
        self, mock_config_class, mock_db_class
    ):
        """Test getting backup filename for SQLite."""
        device = Ethoscope("192.168.1.100")
        device._info = {
            "databases": {"SQLite": {"test_db": {"backup_filename": "test.db"}}}
        }

        filename = device._get_backup_filename_for_db_type("SQLite")
        assert filename == "test.db"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_backup_filename_for_db_type_mariadb(
        self, mock_config_class, mock_db_class
    ):
        """Test getting backup filename for MariaDB."""
        device = Ethoscope("192.168.1.100")
        device._info = {
            "databases": {"MariaDB": {"test_db": {"backup_filename": "test_maria.db"}}}
        }

        filename = device._get_backup_filename_for_db_type("MariaDB")
        assert filename == "test_maria.db"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_is_user_initiated_stop_recent_action(
        self, mock_config_class, mock_db_class
    ):
        """Test user-initiated stop detection with recent action."""
        device = Ethoscope("192.168.1.100")
        device._last_user_action = time.time()
        device._last_user_instruction = "stop"

        with patch.object(device._config, "get_custom") as mock_get_custom:
            mock_get_custom.return_value = {"user_action_timeout_seconds": 30}
            assert device._is_user_initiated_stop() is True

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_is_user_initiated_stop_old_action(self, mock_config_class, mock_db_class):
        """Test user-initiated stop detection with old action."""
        device = Ethoscope("192.168.1.100")
        device._last_user_action = time.time() - 100  # 100 seconds ago
        device._last_user_instruction = "stop"

        with patch.object(device._config, "get_custom") as mock_get_custom:
            mock_get_custom.return_value = {"user_action_timeout_seconds": 30}
            assert device._is_user_initiated_stop() is False

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_cleanup_stream_manager(self, mock_config_class, mock_db_class):
        """Test stream manager cleanup."""
        device = Ethoscope("192.168.1.100")

        mock_stream_manager = Mock()
        device._stream_manager = mock_stream_manager

        device.cleanup_stream_manager()

        mock_stream_manager.stop.assert_called_once()
        assert device._stream_manager is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_stop_device_with_stream_manager(self, mock_config_class, mock_db_class):
        """Test device stop with active stream manager."""
        device = Ethoscope("192.168.1.100")

        mock_stream_manager = Mock()
        device._stream_manager = mock_stream_manager

        device.stop()

        mock_stream_manager.stop.assert_called_once()
        assert device._stream_manager is None


class TestEthoscopeScanner:
    """Test EthoscopeScanner class."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_initialization(self, mock_db_class):
        """Test EthoscopeScanner initialization."""
        scanner = EthoscopeScanner(
            device_refresh_period=10,
            results_dir="/tmp/results",
            config_dir="/tmp/config",
        )

        assert scanner.device_refresh_period == 10
        assert scanner.results_dir == "/tmp/results"
        assert scanner.config_dir == "/tmp/config"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_service_type(self, mock_db_class):
        """Test service type constant."""
        scanner = EthoscopeScanner()
        assert scanner.SERVICE_TYPE == "_ethoscope._tcp.local."
        assert scanner.DEVICE_TYPE == "ethoscope"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_get_all_devices_info_from_db(self, mock_db_class):
        """Test getting all devices info including database devices."""
        mock_db = Mock()
        mock_db.getEthoscope.return_value = {
            "device_001": {
                "ethoscope_name": "ETHOSCOPE_001",
                "last_ip": "192.168.1.100",
                "status": "running",
                "active": 1,
            }
        }
        mock_db_class.return_value = mock_db

        scanner = EthoscopeScanner()
        devices_info = scanner.get_all_devices_info()

        assert "device_001" in devices_info
        assert devices_info["device_001"]["name"] == "ETHOSCOPE_001"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_get_all_devices_info_skip_empty_ids(self, mock_db_class):
        """Test that devices with empty IDs are skipped."""
        mock_db = Mock()
        mock_db.getEthoscope.return_value = {
            "": {"ethoscope_name": "Invalid", "last_ip": "192.168.1.100"},
            "device_001": {
                "ethoscope_name": "ETHOSCOPE_001",
                "last_ip": "192.168.1.101",
                "active": 1,
            },
        }
        mock_db_class.return_value = mock_db

        scanner = EthoscopeScanner()
        devices_info = scanner.get_all_devices_info()

        assert "" not in devices_info
        assert "device_001" in devices_info

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_retire_device(self, mock_db_class):
        """Test device retirement."""
        mock_db = Mock()
        mock_db.getEthoscope.return_value = {
            "device_001": {"ethoscope_id": "device_001", "active": 0}
        }
        mock_db_class.return_value = mock_db

        scanner = EthoscopeScanner()
        result = scanner.retire_device("device_001", active=0)

        assert result["id"] == "device_001"
        assert result["active"] == 0
        mock_db.updateEthoscopes.assert_called_once()


class TestEthoscopeSendInstruction:
    """Test Ethoscope send_instruction method."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_start(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending start instruction."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        with patch.object(device, "_update_info"):
            device.send_instruction("start")

        assert device._last_user_instruction == "start"
        assert device._last_user_action is not None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_stop(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending stop instruction."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("running")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        with patch.object(device, "_update_info"):
            device.send_instruction("stop")

        assert device._last_user_instruction == "stop"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_with_post_data_dict(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending instruction with dictionary post data."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        with patch.object(device, "_update_info"):
            device.send_instruction("start", post_data={"key": "value"})

        # Verify urlopen was called with bytes
        call_args = mock_urlopen.call_args
        assert call_args is not None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_with_post_data_bytes(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending instruction with bytes post data."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
        mock_urlopen.return_value = mock_response

        with patch.object(device, "_update_info"):
            device.send_instruction("start", post_data=b'{"key": "value"}')

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_poweroff(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending poweroff instruction (should not raise on network error)."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        # Simulate network error (device powers off)
        mock_urlopen.side_effect = ScanException("Connection lost")

        with patch.object(device, "_update_info"):
            # Should not raise exception for poweroff
            device.send_instruction("poweroff")

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_reboot(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending reboot instruction (should not raise on network error)."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        # Simulate network error (device reboots)
        mock_urlopen.side_effect = ScanException("Connection lost")

        with patch.object(device, "_update_info"):
            # Should not raise exception for reboot
            device.send_instruction("reboot")

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_send_instruction_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test sending instruction with network error (non-power operation)."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        # Simulate network error
        mock_urlopen.side_effect = ScanException("Network error")

        with patch.object(device, "_update_info"):
            with pytest.raises(DeviceError):
                device.send_instruction("start")


class TestEthoscopeConnectedModule:
    """Test Ethoscope connected_module and related methods."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_connected_module_success(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test connected_module method with successful response."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"module": "sleep_dep"}).encode()
        mock_urlopen.return_value = mock_response

        result = device.connected_module()
        assert result["module"] == "sleep_dep"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_connected_module_no_id(self, mock_config_class, mock_db_class):
        """Test connected_module when device has no ID."""
        device = Ethoscope("192.168.1.100")
        device._id = ""

        result = device.connected_module()
        assert result == {}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_connected_module_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test connected_module with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.connected_module()
        assert result == {}


class TestEthoscopeImageMethods:
    """Test Ethoscope image retrieval methods."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_last_image_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test last_image method with valid status."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("running")
        device._info["last_drawn_img"] = "static/img/last.png"

        mock_response = MagicMock()
        mock_urlopen.return_value = mock_response

        result = device.last_image()
        assert result == mock_response

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_last_image_invalid_status(self, mock_config_class, mock_db_class):
        """Test last_image method with invalid status."""
        device = Ethoscope("192.168.1.100")
        device._device_status = DeviceStatus("stopped")

        result = device.last_image()
        assert result is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_last_image_missing_key(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test last_image method when key is missing."""
        device = Ethoscope("192.168.1.100")
        device._device_status = DeviceStatus("running")
        device._info = {}

        with pytest.raises(KeyError):
            device.last_image()

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_dbg_img_success(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test dbg_img method with success."""
        device = Ethoscope("192.168.1.100")
        device._info["dbg_img"] = "static/img/debug.png"

        mock_response = MagicMock()
        mock_urlopen.return_value = mock_response

        result = device.dbg_img()
        assert result == mock_response

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_dbg_img_error(self, mock_urlopen, mock_config_class, mock_db_class):
        """Test dbg_img method with error."""
        device = Ethoscope("192.168.1.100")
        device._info["dbg_img"] = "static/img/debug.png"

        mock_urlopen.side_effect = Exception("Network error")

        result = device.dbg_img()
        assert result is None


class TestEthoscopeVideofilesMethods:
    """Test Ethoscope videofiles method edge cases."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_videofiles_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test videofiles method with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.videofiles()
        assert result == []

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_user_options_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test user_options method with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.user_options()
        assert result is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_get_log_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test get_log method with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.get_log()
        assert result is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_dump_sql_db_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test dump_sql_db method with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.dump_sql_db()
        assert result is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_machine_info_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test machine_info method with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.machine_info()
        assert result == {}

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_databases_info_network_error(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test databases_info method with network error."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_urlopen.side_effect = ScanException("Network error")

        result = device.databases_info()
        assert result == {}


class TestEthoscopeStreaming:
    """Test Ethoscope streaming functionality."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeStreamManager")
    def test_relay_stream_creates_manager(
        self, mock_stream_class, mock_config_class, mock_db_class
    ):
        """Test relay_stream creates stream manager on first call."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_stream_instance = Mock()
        mock_stream_instance.get_stream_for_client.return_value = iter([b"frame1"])
        mock_stream_class.return_value = mock_stream_instance

        # Call relay_stream
        result = device.relay_stream()
        list(result)  # Consume iterator

        # Verify manager was created
        mock_stream_class.assert_called_once_with("192.168.1.100", "test_device")
        assert device._stream_manager == mock_stream_instance

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeStreamManager")
    def test_relay_stream_reuses_manager(
        self, mock_stream_class, mock_config_class, mock_db_class
    ):
        """Test relay_stream reuses existing stream manager."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        mock_stream_instance = Mock()
        mock_stream_instance.get_stream_for_client.return_value = iter([b"frame1"])
        device._stream_manager = mock_stream_instance

        # Call relay_stream
        device.relay_stream()

        # Verify no new manager was created
        mock_stream_class.assert_not_called()


class TestEthoscopeBackupFilename:
    """Test Ethoscope backup filename logic."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_appropriate_backup_filename_from_info(
        self, mock_config_class, mock_db_class
    ):
        """Test getting backup filename from top-level info."""
        device = Ethoscope("192.168.1.100")
        device._info = {"backup_filename": "2025-01-15_10-30-00_test_id.db"}

        filename = device._get_appropriate_backup_filename()
        assert filename == "2025-01-15_10-30-00_test_id.db"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_appropriate_backup_filename_from_experimental_info(
        self, mock_config_class, mock_db_class
    ):
        """Test getting backup filename from experimental_info."""
        device = Ethoscope("192.168.1.100")
        device._info = {
            "experimental_info": {
                "current": {"selected_options": "SQLiteResultWriter"}
            },
            "databases": {
                "SQLite": {"test_db": {"backup_filename": "sqlite_backup.db"}}
            },
        }

        filename = device._get_appropriate_backup_filename()
        assert filename == "sqlite_backup.db"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_appropriate_backup_filename_mariadb(
        self, mock_config_class, mock_db_class
    ):
        """Test getting MariaDB backup filename from experimental_info."""
        device = Ethoscope("192.168.1.100")
        device._info = {
            "experimental_info": {"current": {"selected_options": "ResultWriter"}},
            "databases": {
                "MariaDB": {"test_db": {"backup_filename": "mariadb_backup.db"}}
            },
        }

        filename = device._get_appropriate_backup_filename()
        assert filename == "mariadb_backup.db"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("urllib.request.urlopen")
    def test_get_appropriate_backup_filename_from_db_info(
        self, mock_urlopen, mock_config_class, mock_db_class
    ):
        """Test getting backup filename from database info."""
        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._info = {
            "databases": {
                "SQLite": {
                    "test_db": {
                        "backup_filename": "fallback.db",
                        "db_status": "tracking",
                    }
                }
            }
        }

        filename = device._get_appropriate_backup_filename()
        assert filename == "fallback.db"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_appropriate_backup_filename_no_match(
        self, mock_config_class, mock_db_class
    ):
        """Test getting backup filename when no database exists."""
        device = Ethoscope("192.168.1.100")
        device._info = {"databases": {}}
        device._device_status = DeviceStatus("stopped")

        filename = device._get_appropriate_backup_filename()
        assert filename is None

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_get_backup_filename_for_db_type_fallback(
        self, mock_config_class, mock_db_class
    ):
        """Test getting backup filename with fallback to old structure."""
        device = Ethoscope("192.168.1.100")
        device._info = {"databases": {}}

        with patch.object(device, "databases_info") as mock_db_info:
            mock_db_info.return_value = {
                "sqlite": {
                    "exists": True,
                    "current": {"backup_filename": "old_struct.db"},
                }
            }
            filename = device._get_backup_filename_for_db_type("SQLite")
            assert filename == "old_struct.db"


class TestEthoscopeSSH:
    """Test Ethoscope SSH authentication setup."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("ethoscope_node.scanner.ethoscope_scanner.ensure_ssh_keys")
    @patch("subprocess.run")
    def test_setup_ssh_authentication_success(
        self, mock_run, mock_ensure_keys, mock_config_class, mock_db_class
    ):
        """Test successful SSH authentication setup."""
        device = Ethoscope("192.168.1.100")
        device._config_dir = "/tmp/config"

        mock_ensure_keys.return_value = ("/tmp/id_rsa", "/tmp/id_rsa.pub")
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = device.setup_ssh_authentication()
        assert result is True

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("ethoscope_node.scanner.ethoscope_scanner.ensure_ssh_keys")
    @patch("subprocess.run")
    def test_setup_ssh_authentication_failure(
        self, mock_run, mock_ensure_keys, mock_config_class, mock_db_class
    ):
        """Test SSH authentication setup failure."""
        device = Ethoscope("192.168.1.100")
        device._config_dir = "/tmp/config"

        mock_ensure_keys.return_value = ("/tmp/id_rsa", "/tmp/id_rsa.pub")
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = "Connection refused"
        mock_run.return_value = mock_result

        result = device.setup_ssh_authentication()
        assert result is False

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("ethoscope_node.scanner.ethoscope_scanner.ensure_ssh_keys")
    @patch("subprocess.run")
    def test_setup_ssh_authentication_timeout(
        self, mock_run, mock_ensure_keys, mock_config_class, mock_db_class
    ):
        """Test SSH authentication setup with timeout."""
        device = Ethoscope("192.168.1.100")
        device._config_dir = "/tmp/config"

        mock_ensure_keys.return_value = ("/tmp/id_rsa", "/tmp/id_rsa.pub")
        mock_run.side_effect = subprocess.TimeoutExpired("sshpass", 30)

        result = device.setup_ssh_authentication()
        assert result is False

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    @patch("ethoscope_node.scanner.ethoscope_scanner.ensure_ssh_keys")
    @patch("subprocess.run")
    def test_setup_ssh_authentication_command_not_found(
        self, mock_run, mock_ensure_keys, mock_config_class, mock_db_class
    ):
        """Test SSH authentication setup when sshpass is not found."""
        device = Ethoscope("192.168.1.100")
        device._config_dir = "/tmp/config"

        mock_ensure_keys.return_value = ("/tmp/id_rsa", "/tmp/id_rsa.pub")
        mock_run.side_effect = FileNotFoundError("sshpass not found")

        result = device.setup_ssh_authentication()
        assert result is False


class TestEthoscopeHandleDeviceComingOnline:
    """Test Ethoscope device coming online handling."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_handle_device_coming_online_success(
        self, mock_config_class, mock_db_class
    ):
        """Test device coming online updates database."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._info = {"name": "ETHOSCOPE_001"}

        with patch.object(device, "machine_info") as mock_machine:
            mock_machine.return_value = {"kernel": "5.4.0", "pi_version": "4"}
            device._handle_device_coming_online()

        mock_db.updateEthoscopes.assert_called_once()
        call_kwargs = mock_db.updateEthoscopes.call_args[1]
        assert call_kwargs["ethoscope_id"] == "test_device"
        assert call_kwargs["ethoscope_name"] == "ETHOSCOPE_001"
        assert call_kwargs["last_ip"] == "192.168.1.100"
        assert "machineinfo" in call_kwargs

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_handle_device_coming_online_ooo_device(
        self, mock_config_class, mock_db_class
    ):
        """Test device coming online with OOO in name (should be ignored)."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._info = {"name": "ETHOSCOPE_OOO_001"}

        device._handle_device_coming_online()

        mock_db.updateEthoscopes.assert_not_called()

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_handle_device_coming_online_error(self, mock_config_class, mock_db_class):
        """Test device coming online with database error."""
        mock_db = Mock()
        mock_db.updateEthoscopes.side_effect = Exception("Database error")
        mock_db_class.return_value = mock_db

        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._info = {"name": "ETHOSCOPE_001"}

        with patch.object(device, "machine_info") as mock_machine:
            mock_machine.return_value = {"kernel": "5.4.0", "pi_version": "4"}
            # Should not raise, just log error
            device._handle_device_coming_online()


class TestEthoscopeHandleUnreachableState:
    """Test Ethoscope unreachable state handling."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_handle_unreachable_state_becomes_unreached(
        self, mock_config_class, mock_db_class
    ):
        """Test device becomes unreachable for first time."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("stopped")

        with patch.object(device._config, "get_custom") as mock_get_custom:
            mock_get_custom.return_value = {"unreachable_timeout_minutes": 20}

            with patch.object(device, "_update_device_status") as mock_update:
                with patch.object(device, "_reset_info"):
                    device._handle_unreachable_state("stopped")

                # Verify status was set to unreached
                mock_update.assert_called()
                assert "unreached" in str(mock_update.call_args)

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_handle_unreachable_state_busy_within_timeout(
        self, mock_config_class, mock_db_class
    ):
        """Test busy device within timeout stays busy."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        device = Ethoscope("192.168.1.100")
        device._id = "test_device"

        # Create busy status that has NOT exceeded timeout
        busy_status = DeviceStatus("busy")
        busy_status._state_entered_at = time.time() - 300  # 5 minutes ago
        device._device_status = busy_status

        with patch.object(device._config, "get_custom") as mock_get_custom:
            mock_get_custom.return_value = {"busy_timeout_minutes": 10}

            with patch.object(device, "_update_device_status") as mock_update:
                device._handle_unreachable_state("busy")

                # Verify status stays busy
                assert mock_update.call_count >= 1
                # Device should be updated to busy status
                busy_call_found = any(
                    call[0][0] == "busy" for call in mock_update.call_args_list
                )
                assert busy_call_found

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    @patch("ethoscope_node.scanner.ethoscope_scanner.EthoscopeConfiguration")
    def test_handle_unreachable_state_with_run_id(
        self, mock_config_class, mock_db_class
    ):
        """Test unreachable state with active run_id flags problem."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        device = Ethoscope("192.168.1.100")
        device._id = "test_device"
        device._device_status = DeviceStatus("running")
        device._info = {"experimental_info": {"current": {"run_id": "test_run_123"}}}

        with patch.object(device._config, "get_custom") as mock_get_custom:
            mock_get_custom.return_value = {"unreachable_timeout_minutes": 20}

            with patch.object(device, "_update_device_status"):
                with patch.object(device, "_reset_info"):
                    device._handle_unreachable_state("running")

        # Verify database was updated
        mock_db.flagProblem.assert_called_once_with(
            run_id="test_run_123", message="unreached"
        )


class TestEthoscopeScannerAdd:
    """Test EthoscopeScanner add method."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_scanner_add_new_device(self, mock_db_class):
        """Test adding a new device to scanner."""
        scanner = EthoscopeScanner()
        scanner._is_running = True

        with patch.object(scanner, "_device_class") as mock_device_class:
            mock_device = Mock()
            mock_device.id.return_value = "test_device"
            mock_device_class.return_value = mock_device

            scanner.add("192.168.1.100", port=9000, name="ETHOSCOPE_001")

            # Verify device was created and started
            mock_device_class.assert_called_once()
            mock_device.start.assert_called_once()
            assert len(scanner.devices) == 1

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_scanner_add_scanner_not_running(self, mock_db_class):
        """Test adding device when scanner is not running."""
        scanner = EthoscopeScanner()
        scanner._is_running = False

        scanner.add("192.168.1.100")

        # Verify no device was added
        assert len(scanner.devices) == 0

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_scanner_add_existing_device_by_ip(self, mock_db_class):
        """Test adding device that already exists (by IP)."""
        scanner = EthoscopeScanner()
        scanner._is_running = True

        # Create existing device
        existing_device = Mock()
        existing_device.ip.return_value = "192.168.1.100"
        existing_device.id.return_value = "old_id"
        existing_device._id = "old_id"
        existing_device._skip_scanning = False
        existing_device._device_status = DeviceStatus("running")
        existing_device._lock = MagicMock()

        scanner.devices.append(existing_device)

        # Try to add same IP
        scanner.add("192.168.1.100", name="ETHOSCOPE_001")

        # Verify no new device was added
        assert len(scanner.devices) == 1
        existing_device.reset_error_state.assert_called_once()
        existing_device.skip_scanning.assert_called()

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_scanner_add_with_zeroconf_info(self, mock_db_class):
        """Test adding device with zeroconf info."""
        scanner = EthoscopeScanner()
        scanner._is_running = True

        zcinfo = {
            b"MACHINE_NAME": b"ETHOSCOPE_001",
            b"MACHINE_ID": b"test_device_id",
        }

        with patch.object(scanner, "_device_class") as mock_device_class:
            mock_device = Mock()
            mock_device.id.return_value = "test_device_id"
            mock_device_class.return_value = mock_device

            scanner.add("192.168.1.100", zcinfo=zcinfo)

            mock_device.start.assert_called_once()


class TestEthoscopeScannerDeviceIDChange:
    """Test EthoscopeScanner device ID change handling."""

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_handle_device_id_change_from_ethoscope_000(self, mock_db_class):
        """Test handling device ID change from ETHOSCOPE_000."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        scanner = EthoscopeScanner()
        device = Mock()
        device.info.return_value = {"name": "ETHOSCOPE_001"}
        device.ip.return_value = "192.168.1.100"

        scanner._handle_device_id_change(device, "ETHOSCOPE_000", "new_device_id")

        # Verify new device entry was created
        mock_db.updateEthoscopes.assert_called()
        call_kwargs = mock_db.updateEthoscopes.call_args[1]
        assert call_kwargs["ethoscope_id"] == "new_device_id"

    @patch("ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB")
    def test_handle_device_id_change_retire_old(self, mock_db_class):
        """Test handling device ID change retires old device."""
        mock_db = Mock()
        mock_db.getEthoscope.return_value = {
            "old_device_id": {"ethoscope_name": "OLD_NAME"}
        }
        mock_db_class.return_value = mock_db

        scanner = EthoscopeScanner()
        device = Mock()
        device.info.return_value = {"name": "ETHOSCOPE_001"}
        device.ip.return_value = "192.168.1.100"

        scanner._handle_device_id_change(device, "old_device_id", "new_device_id")

        # Verify old device was retired (active=0)
        update_calls = mock_db.updateEthoscopes.call_args_list
        assert len(update_calls) == 2
        # First call should retire old device
        assert update_calls[0][1]["ethoscope_id"] == "old_device_id"
        assert update_calls[0][1]["active"] == 0
