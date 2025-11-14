"""
Unit tests for base_scanner module.

This module tests core scanner functionality including DeviceStatus,
BaseDevice, DeviceScanner, and related utility functions.
"""

import json
import socket
import time
import urllib.error
import urllib.request
from threading import RLock
from unittest.mock import MagicMock, Mock, patch

import pytest

from ethoscope_node.scanner.base_scanner import (
    BaseDevice,
    DeviceError,
    DeviceScanner,
    DeviceStatus,
    NetworkError,
    ScanException,
    retry,
)


class TestDeviceStatus:
    """Test DeviceStatus class."""

    def test_initialization_valid_status(self):
        """Test DeviceStatus initialization with valid status."""
        status = DeviceStatus("running", is_user_triggered=True, trigger_source="user")
        assert status.status_name == "running"
        assert status.is_user_triggered is True
        assert status.trigger_source == "user"
        assert status.consecutive_errors == 0

    def test_initialization_invalid_status(self):
        """Test DeviceStatus initialization with invalid status."""
        with pytest.raises(ValueError, match="Invalid status"):
            DeviceStatus("invalid_status")

    def test_status_age_tracking(self):
        """Test status age tracking."""
        status = DeviceStatus("running")
        time.sleep(0.1)
        assert status.get_age_seconds() >= 0.1
        assert status.get_age_minutes() >= 0.001

    def test_error_tracking(self):
        """Test consecutive error tracking."""
        status = DeviceStatus("unreached")
        assert status.consecutive_errors == 0

        status.increment_errors()
        assert status.consecutive_errors == 1

        status.increment_errors()
        status.increment_errors()
        assert status.consecutive_errors == 3

        status.reset_errors()
        assert status.consecutive_errors == 0

    def test_previous_status_tracking(self):
        """Test previous status tracking."""
        status1 = DeviceStatus("running")
        status2 = DeviceStatus("stopped")
        status2.set_previous_status(status1)

        assert status2.get_previous_status() == status1
        assert status2.get_previous_status().status_name == "running"

    def test_graceful_operation_detection(self):
        """Test graceful operation detection."""
        # Graceful operation
        status = DeviceStatus("offline", trigger_source="graceful")
        assert status.is_graceful_operation() is True

        # Not graceful
        status = DeviceStatus("offline", trigger_source="system")
        assert status.is_graceful_operation() is False

    def test_timeout_exceeded(self):
        """Test timeout exceeded checking."""
        status = DeviceStatus("unreached")
        status._unreachable_start_time = time.time() - 25 * 60  # 25 minutes ago

        assert status.is_timeout_exceeded(20) is True
        assert status.is_timeout_exceeded(30) is False

    def test_should_send_alert_user_triggered(self):
        """Test alert suppression for user-triggered actions."""
        status = DeviceStatus("stopped", is_user_triggered=True)
        assert status.should_send_alert() is False

    def test_should_send_alert_graceful(self):
        """Test alert suppression for graceful operations."""
        status = DeviceStatus("offline", trigger_source="graceful")
        assert status.should_send_alert() is False

    def test_should_send_alert_initial_discovery(self):
        """Test alert suppression for initial device discovery."""
        status = DeviceStatus("stopped", trigger_source="system")
        status.mark_as_initial_discovery()
        assert status.should_send_alert() is False

    def test_interrupted_tracking_session_detection(self):
        """Test detection of interrupted tracking sessions."""
        # Create a chain: running -> unreached -> stopped
        status1 = DeviceStatus("running")
        status2 = DeviceStatus("unreached")
        status2.set_previous_status(status1)
        status3 = DeviceStatus("stopped")
        status3.set_previous_status(status2)

        assert status3.is_interrupted_tracking_session() is True

    def test_interrupted_tracking_no_intermediate(self):
        """Test that direct transitions are not considered interrupted."""
        # Direct transition: running -> stopped (user-triggered)
        status1 = DeviceStatus("running")
        status2 = DeviceStatus("stopped", is_user_triggered=True)
        status2.set_previous_status(status1)

        assert status2.is_interrupted_tracking_session() is False

    def test_metadata_handling(self):
        """Test metadata storage and updates."""
        metadata = {"reason": "test", "count": 42}
        status = DeviceStatus("running", metadata=metadata)

        assert status.metadata["reason"] == "test"
        assert status.metadata["count"] == 42

        status.update_metadata("new_key", "new_value")
        assert status.metadata["new_key"] == "new_value"

    def test_to_dict_serialization(self):
        """Test status serialization to dictionary."""
        status = DeviceStatus("running", is_user_triggered=True, trigger_source="user")
        status_dict = status.to_dict()

        assert status_dict["status_name"] == "running"
        assert status_dict["is_user_triggered"] is True
        assert status_dict["trigger_source"] == "user"
        assert "timestamp" in status_dict

    def test_from_dict_deserialization(self):
        """Test status deserialization from dictionary."""
        status_dict = {
            "status_name": "stopped",
            "is_user_triggered": False,
            "trigger_source": "system",
            "metadata": {"reason": "test"},
            "timestamp": time.time(),
            "consecutive_errors": 2,
        }

        status = DeviceStatus.from_dict(status_dict)
        assert status.status_name == "stopped"
        assert status.is_user_triggered is False
        assert status.consecutive_errors == 2


class TestExceptions:
    """Test custom exceptions."""

    def test_scan_exception(self):
        """Test ScanException creation."""
        with pytest.raises(ScanException, match="Test error"):
            raise ScanException("Test error")

    def test_network_error(self):
        """Test NetworkError creation."""
        with pytest.raises(NetworkError, match="Connection failed"):
            raise NetworkError("Connection failed")

    def test_device_error(self):
        """Test DeviceError creation."""
        with pytest.raises(DeviceError, match="Device unavailable"):
            raise DeviceError("Device unavailable")


class TestRetryDecorator:
    """Test retry decorator."""

    def test_retry_success_first_attempt(self):
        """Test retry decorator with successful first attempt."""
        call_count = 0

        @retry(Exception, tries=3, delay=0.01)
        def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_function()
        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """Test retry decorator with success after failures."""
        call_count = 0

        @retry(ValueError, tries=3, delay=0.01)
        def eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Not ready yet")
            return "success"

        result = eventually_successful()
        assert result == "success"
        assert call_count == 3

    def test_retry_max_attempts_exceeded(self):
        """Test retry decorator when max attempts are exceeded."""
        call_count = 0

        @retry(ValueError, tries=3, delay=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            always_fails()

        assert call_count == 3


class TestBaseDevice:
    """Test BaseDevice class."""

    def test_initialization(self):
        """Test BaseDevice initialization."""
        device = BaseDevice("192.168.1.100", port=9000, refresh_period=5)
        assert device._ip == "192.168.1.100"
        assert device._port == 9000
        assert device._refresh_period == 5
        assert device._device_status.status_name == "offline"

    def test_url_setup(self):
        """Test URL setup."""
        device = BaseDevice("192.168.1.100", port=9000)
        assert device._id_url == "http://192.168.1.100:9000/id"
        assert device._data_url == "http://192.168.1.100:9000/"

    def test_ip_access(self):
        """Test IP address getter."""
        device = BaseDevice("192.168.1.100")
        assert device.ip() == "192.168.1.100"

    def test_id_access(self):
        """Test device ID getter."""
        device = BaseDevice("192.168.1.100")
        device._id = "test_device_001"
        assert device.id() == "test_device_001"

    def test_get_device_status(self):
        """Test device status getter."""
        device = BaseDevice("192.168.1.100")
        status = device.get_device_status()
        assert isinstance(status, DeviceStatus)
        assert status.status_name == "offline"

    @patch("urllib.request.urlopen")
    def test_get_json_success(self, mock_urlopen):
        """Test successful JSON fetching."""
        device = BaseDevice("192.168.1.100")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"id": "test_001"}).encode()
        mock_urlopen.return_value = mock_response

        result = device._get_json("http://192.168.1.100/id")
        assert result["id"] == "test_001"

    @patch("urllib.request.urlopen")
    def test_get_json_empty_response(self, mock_urlopen):
        """Test JSON fetching with empty response."""
        device = BaseDevice("192.168.1.100")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = b""
        mock_urlopen.return_value = mock_response

        with pytest.raises(ScanException, match="Empty response"):
            device._get_json("http://192.168.1.100/id")

    @patch("urllib.request.urlopen")
    def test_get_json_invalid_json(self, mock_urlopen):
        """Test JSON fetching with invalid JSON response."""
        device = BaseDevice("192.168.1.100")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = b"not valid json"
        mock_urlopen.return_value = mock_response

        with pytest.raises(ScanException, match="Invalid JSON"):
            device._get_json("http://192.168.1.100/id")

    @patch("urllib.request.urlopen")
    def test_get_json_http_error(self, mock_urlopen):
        """Test JSON fetching with HTTP error."""
        device = BaseDevice("192.168.1.100")

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://test.com", 404, "Not Found", {}, None
        )

        with pytest.raises(NetworkError, match="HTTP 404"):
            device._get_json("http://192.168.1.100/id")

    @patch("urllib.request.urlopen")
    def test_get_json_timeout(self, mock_urlopen):
        """Test JSON fetching with timeout."""
        device = BaseDevice("192.168.1.100")

        mock_urlopen.side_effect = socket.timeout("Connection timeout")

        with pytest.raises(NetworkError, match="Timeout"):
            device._get_json("http://192.168.1.100/id")

    def test_skip_scanning(self):
        """Test skip scanning flag."""
        device = BaseDevice("192.168.1.100")
        assert device._skip_scanning is False

        device.skip_scanning(True)
        assert device._skip_scanning is True
        assert device._consecutive_errors == 0  # Should reset errors

        device.skip_scanning(False)
        assert device._skip_scanning is False

    def test_reset_error_state(self):
        """Test error state reset."""
        device = BaseDevice("192.168.1.100")
        device._consecutive_errors = 5

        device.reset_error_state()
        assert device._consecutive_errors == 0

    def test_info_returns_copy(self):
        """Test that info() returns a copy with status details."""
        device = BaseDevice("192.168.1.100")
        device._info["test_key"] = "test_value"

        info = device.info()
        assert info["test_key"] == "test_value"
        assert "status" in info
        assert "status_details" in info

    def test_effective_refresh_period_normal(self):
        """Test effective refresh period for normal device."""
        device = BaseDevice("192.168.1.100", refresh_period=5)
        device._update_device_status("running")

        assert device._get_effective_refresh_period() == 5

    def test_effective_refresh_period_busy(self):
        """Test effective refresh period for busy device."""
        device = BaseDevice("192.168.1.100", refresh_period=5)
        device._update_device_status("busy")

        assert device._get_effective_refresh_period() == 60.0


class TestDeviceScanner:
    """Test DeviceScanner class."""

    def test_initialization(self):
        """Test DeviceScanner initialization."""
        scanner = DeviceScanner(device_refresh_period=10)
        assert scanner.device_refresh_period == 10
        assert scanner.devices == []
        assert scanner._is_running is False

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_start_scanner(self, mock_browser, mock_zeroconf):
        """Test scanner start."""
        scanner = DeviceScanner()
        scanner.start()

        assert scanner._is_running is True
        mock_zeroconf.assert_called_once()
        mock_browser.assert_called_once()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_stop_scanner(self, mock_browser, mock_zeroconf):
        """Test scanner stop."""
        scanner = DeviceScanner()
        scanner.start()
        scanner.stop()

        assert scanner._is_running is False

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_context_manager(self, mock_browser, mock_zeroconf):
        """Test scanner as context manager."""
        with DeviceScanner() as scanner:
            assert scanner._is_running is True

        assert scanner._is_running is False

    def test_current_devices_id(self):
        """Test getting current device IDs."""
        scanner = DeviceScanner()

        # Add mock devices
        device1 = Mock()
        device1.id.return_value = "device_001"
        device2 = Mock()
        device2.id.return_value = "device_002"

        scanner.devices = [device1, device2]

        ids = scanner.current_devices_id
        assert "device_001" in ids
        assert "device_002" in ids

    def test_get_device(self):
        """Test getting device by ID."""
        scanner = DeviceScanner()

        device = Mock()
        device.id.return_value = "device_001"
        scanner.devices = [device]

        found = scanner.get_device("device_001")
        assert found == device

        not_found = scanner.get_device("device_999")
        assert not_found is None

    def test_get_all_devices_info(self):
        """Test getting all devices info."""
        scanner = DeviceScanner()

        device1 = Mock()
        device1.id.return_value = "device_001"
        device1.info.return_value = {"name": "Device 1"}

        device2 = Mock()
        device2.id.return_value = "device_002"
        device2.info.return_value = {"name": "Device 2"}

        scanner.devices = [device1, device2]

        all_info = scanner.get_all_devices_info()
        assert "device_001" in all_info
        assert "device_002" in all_info
        assert all_info["device_001"]["name"] == "Device 1"
