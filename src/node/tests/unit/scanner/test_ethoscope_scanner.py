"""
Unit tests for ethoscope_scanner module.

This module tests Ethoscope-specific scanner functionality including
device management, status tracking, and backup path generation.
"""

import json
import os
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
