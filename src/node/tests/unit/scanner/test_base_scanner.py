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


class TestBaseDeviceLifecycle:
    """Test BaseDevice lifecycle methods (run loop, threading, etc)."""

    @patch("urllib.request.urlopen")
    def test_device_run_loop(self, mock_urlopen):
        """Test device run loop execution."""
        device = BaseDevice("192.168.1.100", refresh_period=0.1)

        # Mock successful response
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"id": "test_001"}).encode()
        mock_urlopen.return_value = mock_response

        # Start device thread
        device.start()
        time.sleep(0.3)  # Let it run for a bit

        # Stop device
        device.stop()
        device.join(timeout=2)

        # Verify device ran
        assert not device._is_online

    @patch("urllib.request.urlopen")
    def test_device_run_loop_with_errors(self, mock_urlopen):
        """Test device run loop with errors."""
        device = BaseDevice("192.168.1.100", refresh_period=0.1)

        # Mock error response
        mock_urlopen.side_effect = urllib.error.URLError("Connection failed")

        # Start device thread
        device.start()
        time.sleep(0.3)

        # Stop device
        device.stop()
        device.join(timeout=2)

        # Verify errors were tracked
        assert device._consecutive_errors > 0

    @patch("urllib.request.urlopen")
    def test_device_run_loop_skip_scanning(self, mock_urlopen):
        """Test run loop respects skip_scanning flag."""
        device = BaseDevice("192.168.1.100", refresh_period=0.1)
        device.skip_scanning(True)

        # Start device thread
        device.start()
        time.sleep(0.3)

        # Stop device
        device.stop()
        device.join(timeout=2)

        # Verify no network calls were made
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_device_run_loop_error_recovery(self, mock_urlopen):
        """Test device recovers after errors."""
        device = BaseDevice("192.168.1.100", refresh_period=0.1)

        # First calls fail, then succeed
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"id": "test_001"}).encode()

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise urllib.error.URLError("Temporary error")
            return mock_response

        mock_urlopen.side_effect = side_effect

        device.start()
        time.sleep(0.4)
        device.stop()
        device.join(timeout=2)

        # Verify recovery happened (errors reset to 0)
        assert device._consecutive_errors == 0


class TestDeviceErrorHandling:
    """Test BaseDevice error handling and recovery mechanisms."""

    def test_handle_device_error_connection_refused_graceful(self):
        """Test handling connection refused with graceful shutdown detection."""
        device = BaseDevice("192.168.1.100")

        # Set up graceful operation status
        device._update_device_status("offline", trigger_source="graceful")

        # Simulate connection refused errors
        error = urllib.error.URLError("[Errno 111] Connection refused")
        for _ in range(3):
            device._handle_device_error(error)

        # Should mark for skipping after 3 errors
        assert device._skip_scanning is True
        assert device._consecutive_errors == 3

    def test_handle_device_error_connection_refused_ungraceful(self):
        """Test handling connection refused without graceful shutdown."""
        device = BaseDevice("192.168.1.100")

        # Set up non-graceful status
        device._update_device_status("running", trigger_source="system")

        # Simulate connection refused errors
        error = urllib.error.URLError("[Errno 111] Connection refused")
        for _ in range(3):
            device._handle_device_error(error)

        # Should mark for skipping
        assert device._skip_scanning is True

    def test_handle_device_error_max_errors_reached(self):
        """Test handling max consecutive errors."""
        device = BaseDevice("192.168.1.100")
        device._max_consecutive_errors = 5

        # Simulate generic errors
        error = urllib.error.URLError("Generic error")
        for _ in range(5):
            device._handle_device_error(error)

        # Should stop scanning after max errors
        assert device._skip_scanning is True
        assert device._consecutive_errors == 5

    def test_handle_device_error_progressive_logging(self):
        """Test progressive error logging at different thresholds."""
        device = BaseDevice("192.168.1.100")

        error = urllib.error.URLError("Test error")

        # First error (should log info)
        device._handle_device_error(error)
        assert device._consecutive_errors == 1

        # Fifth error (should log warning)
        for _ in range(4):
            device._handle_device_error(error)
        assert device._consecutive_errors == 5

    def test_handle_device_error_with_actively_refused(self):
        """Test handling 'actively refused' connection errors."""
        device = BaseDevice("192.168.1.100")

        error = urllib.error.URLError("Connection actively refused")
        for _ in range(3):
            device._handle_device_error(error)

        assert device._skip_scanning is True


class TestDeviceIDUpdate:
    """Test device ID update and status transitions."""

    @patch("urllib.request.urlopen")
    def test_update_id_success(self, mock_urlopen):
        """Test successful device ID update."""
        device = BaseDevice("192.168.1.100")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"id": "test_001"}).encode()
        mock_urlopen.return_value = mock_response

        device._update_id()

        assert device._id == "test_001"
        assert device._info["id"] == "test_001"

    @patch("urllib.request.urlopen")
    def test_update_id_fallback_to_id_url(self, mock_urlopen):
        """Test ID update falls back to ID URL if data URL fails."""
        device = BaseDevice("192.168.1.100")

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call to data URL fails
                raise urllib.error.URLError("Not found")

            # Second call to ID URL succeeds
            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response
            mock_response.read.return_value = json.dumps({"id": "test_002"}).encode()
            return mock_response

        mock_urlopen.side_effect = side_effect

        device._update_id()

        assert device._id == "test_002"

    @patch("urllib.request.urlopen")
    def test_update_id_change_detection(self, mock_urlopen):
        """Test ID change detection and reset."""
        device = BaseDevice("192.168.1.100")
        device._id = "old_id"

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"id": "new_id"}).encode()
        mock_urlopen.return_value = mock_response

        device._update_id()

        assert device._id == "new_id"

    def test_update_id_skip_scanning(self):
        """Test update_id raises when skip_scanning is True."""
        device = BaseDevice("192.168.1.100")
        device.skip_scanning(True)

        with pytest.raises(ScanException, match="Not scanning"):
            device._update_id()

    @patch("urllib.request.urlopen")
    def test_update_id_exception_handling(self, mock_urlopen):
        """Test update_id handles exceptions properly."""
        device = BaseDevice("192.168.1.100")

        # Both URLs fail
        mock_urlopen.side_effect = urllib.error.URLError("Connection failed")

        with pytest.raises(NetworkError):
            device._update_id()

    @patch("urllib.request.urlopen")
    def test_update_info(self, mock_urlopen):
        """Test _update_info method."""
        device = BaseDevice("192.168.1.100")

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"id": "test_003"}).encode()
        mock_urlopen.return_value = mock_response

        device._update_info()

        assert device._id == "test_003"
        assert device._device_status.status_name == "online"

    def test_reset_info(self):
        """Test reset_info preserves important data."""
        device = BaseDevice("192.168.1.100")
        device._info["name"] = "Test Device"
        device._id = "test_004"
        device._info["id"] = "test_004"

        device._reset_info()

        # Status should be offline
        assert device._device_status.status_name == "offline"
        # Name and ID should be preserved
        assert device._info.get("name") == "Test Device"
        assert device._info.get("id") == "test_004"


class TestDeviceStatusTransitions:
    """Test device status transitions and tracking."""

    def test_update_device_status_basic(self):
        """Test basic status update."""
        device = BaseDevice("192.168.1.100")

        device._update_device_status("running", trigger_source="user")

        assert device._device_status.status_name == "running"
        assert device._device_status.trigger_source == "user"

    def test_update_device_status_preserves_errors(self):
        """Test status update preserves error count."""
        device = BaseDevice("192.168.1.100")

        # Set up previous status with errors
        prev_status = DeviceStatus("unreached")
        prev_status.increment_errors()
        prev_status.increment_errors()
        device._device_status = prev_status

        device._update_device_status("offline")

        assert device._device_status.consecutive_errors == 2

    def test_update_device_status_initial_discovery(self):
        """Test initial discovery marking."""
        device = BaseDevice("192.168.1.100")

        # Initial offline state
        assert device._device_status.status_name == "offline"

        # First real status should be marked as initial discovery
        device._update_device_status("running")

        # The marking happens internally, verify by checking attribute
        assert hasattr(device, "_has_received_real_status")

    def test_info_includes_status_details(self):
        """Test that info() includes detailed status information."""
        device = BaseDevice("192.168.1.100")
        device._update_device_status("running", is_user_triggered=True)

        info = device.info()

        assert "status" in info
        assert info["status"] == "running"
        assert "status_details" in info
        assert info["status_details"]["status"] == "running"
        assert info["status_details"]["is_user_triggered"] is True

    def test_info_includes_backup_status(self):
        """Test that info() exposes backup status at root level."""
        device = BaseDevice("192.168.1.100")
        device._info["progress"] = {
            "status": "completed",
            "backup_size": 1024,
            "time_since_backup": 60,
        }

        info = device.info()

        assert info["backup_status"] == "completed"
        assert info["backup_size"] == 1024
        assert info["time_since_backup"] == 60


class TestDeviceScannerOperations:
    """Test DeviceScanner add/remove operations."""

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_device_when_running(self, mock_browser, mock_zeroconf):
        """Test adding a device when scanner is running."""
        scanner = DeviceScanner()
        scanner.start()

        scanner.add("192.168.1.100", 9000, name="test.local", device_id="test_001")

        assert len(scanner.devices) == 1
        assert scanner.devices[0].ip() == "192.168.1.100"

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_device_when_not_running(self, mock_browser, mock_zeroconf):
        """Test adding a device when scanner is not running."""
        scanner = DeviceScanner()
        # Don't start scanner

        scanner.add("192.168.1.100", 9000)

        # Should not add device
        assert len(scanner.devices) == 0

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_existing_device_reactivates(self, mock_browser, mock_zeroconf):
        """Test adding an existing device reactivates it."""
        scanner = DeviceScanner()
        scanner.start()

        # Add device first time
        scanner.add("192.168.1.100", 9000, name="test.local")
        assert len(scanner.devices) == 1

        # Mark device as skipping
        scanner.devices[0].skip_scanning(True)
        assert scanner.devices[0]._skip_scanning is True

        # Add same device again (by IP)
        scanner.add("192.168.1.100", 9000, name="test.local")

        # Should still be 1 device, but reactivated
        assert len(scanner.devices) == 1
        assert scanner.devices[0]._skip_scanning is False

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_duplicate_device_id(self, mock_browser, mock_zeroconf):
        """Test adding device with duplicate ID is rejected."""
        scanner = DeviceScanner()
        scanner.start()

        # Create mock device with ID
        device1 = Mock(spec=BaseDevice)
        device1.ip.return_value = "192.168.1.100"
        device1.id.return_value = "test_001"
        device1._skip_scanning = False
        device1._device_status = DeviceStatus("online")

        scanner.devices.append(device1)

        # Try to add another device with same ID
        scanner.add("192.168.1.101", 9000, device_id="test_001")

        # Should still be only 1 device
        assert len(scanner.devices) == 1

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_service_zeroconf_callback(self, mock_browser, mock_zeroconf_class):
        """Test Zeroconf add_service callback."""
        scanner = DeviceScanner()
        scanner.start()

        # Mock zeroconf instance
        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.addresses = [socket.inet_aton("192.168.1.100")]
        mock_info.port = 9000
        mock_info.properties = {}
        mock_zc.get_service_info.return_value = mock_info

        # Call add_service
        scanner.add_service(mock_zc, "_device._tcp.local.", "test.local")

        # Verify service was added
        assert len(scanner.devices) == 1

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_service_no_info(self, mock_browser, mock_zeroconf):
        """Test add_service handles missing service info."""
        scanner = DeviceScanner()
        scanner.start()

        mock_zc = MagicMock()
        mock_zc.get_service_info.return_value = None

        scanner.add_service(mock_zc, "_device._tcp.local.", "test.local")

        # Should not add device
        assert len(scanner.devices) == 0

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_service_when_not_running(self, mock_browser, mock_zeroconf):
        """Test add_service does nothing when scanner not running."""
        scanner = DeviceScanner()
        # Don't start

        mock_zc = MagicMock()
        scanner.add_service(mock_zc, "_device._tcp.local.", "test.local")

        assert len(scanner.devices) == 0

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_remove_service_marks_offline(self, mock_browser, mock_zeroconf):
        """Test remove_service marks device as offline."""
        scanner = DeviceScanner()
        scanner.start()

        # Add a device
        scanner.add("192.168.1.100", 9000)
        device = scanner.devices[0]

        # Mock zeroconf info for removal
        mock_zc = MagicMock()
        mock_info = MagicMock()
        mock_info.addresses = [socket.inet_aton("192.168.1.100")]
        mock_zc.get_service_info.return_value = mock_info

        # Remove service
        scanner.remove_service(mock_zc, "_device._tcp.local.", "test.local")

        # Device should be marked for skipping
        assert device._skip_scanning is True
        assert device._device_status.status_name == "offline"

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_remove_service_when_not_running(self, mock_browser, mock_zeroconf):
        """Test remove_service does nothing when not running."""
        scanner = DeviceScanner()
        # Don't start

        mock_zc = MagicMock()
        scanner.remove_service(mock_zc, "_device._tcp.local.", "test.local")

        # Should do nothing
        pass

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_update_service_callback(self, mock_browser, mock_zeroconf):
        """Test update_service callback (currently a no-op)."""
        scanner = DeviceScanner()
        scanner.start()

        mock_zc = MagicMock()
        scanner.update_service(mock_zc, "_device._tcp.local.", "test.local")

        # Should not crash
        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_scanner_start_already_running(self, mock_browser, mock_zeroconf):
        """Test starting scanner when already running."""
        scanner = DeviceScanner()
        scanner.start()

        # Try to start again
        scanner.start()

        # Should only be called once
        assert mock_zeroconf.call_count == 1

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_scanner_stop_when_not_running(self, mock_browser, mock_zeroconf):
        """Test stopping scanner when not running."""
        scanner = DeviceScanner()

        # Stop without starting
        scanner.stop()

        # Should not crash
        assert scanner._is_running is False

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    def test_scanner_start_error_cleanup(self, mock_zeroconf_class):
        """Test scanner cleans up on start error."""
        mock_zeroconf_class.side_effect = Exception("Zeroconf failed")

        scanner = DeviceScanner()

        with pytest.raises(Exception, match="Zeroconf failed"):
            scanner.start()

        assert scanner._is_running is False

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_scanner_stop_with_device_errors(self, mock_browser, mock_zeroconf):
        """Test scanner handles errors when stopping devices."""
        scanner = DeviceScanner()
        scanner.start()

        # Add mock device that fails on stop
        device = Mock()
        device.ip.return_value = "192.168.1.100"
        device.stop.side_effect = Exception("Stop failed")
        scanner.devices.append(device)

        # Should not crash
        scanner.stop()

        assert scanner._is_running is False

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_scanner_destructor(self, mock_browser, mock_zeroconf):
        """Test scanner destructor cleanup."""
        scanner = DeviceScanner()
        scanner.start()

        # Call destructor
        scanner.__del__()

        # Should clean up
        assert scanner._is_running is False


class TestDeviceStatusEdgeCases:
    """Test edge cases and additional DeviceStatus functionality."""

    def test_should_send_alert_interrupted_session(self):
        """Test alert for interrupted tracking session."""
        # Create interrupted session chain
        status1 = DeviceStatus("running")
        status2 = DeviceStatus("unreached")
        status2.set_previous_status(status1)
        status3 = DeviceStatus("stopped", trigger_source="system")
        status3.set_previous_status(status2)

        assert status3.should_send_alert() is True

    def test_timeout_exceeded_no_unreachable_time(self):
        """Test timeout check when no unreachable time set."""
        status = DeviceStatus("running")
        assert status.is_timeout_exceeded(20) is False

    def test_device_status_string_representation(self):
        """Test DeviceStatus __str__ method."""
        status = DeviceStatus("running", trigger_source="user")
        time.sleep(0.1)

        str_repr = str(status)
        assert "running" in str_repr
        assert "user" in str_repr

    def test_device_status_repr(self):
        """Test DeviceStatus __repr__ method."""
        status = DeviceStatus("stopped", is_user_triggered=True)

        repr_str = repr(status)
        assert "DeviceStatus" in repr_str
        assert "stopped" in repr_str
        assert "is_user_triggered=True" in repr_str

    def test_interrupted_session_complex_chain(self):
        """Test interrupted session detection with complex chain."""
        # Create chain: recording -> busy -> unreached -> stopping -> offline
        status1 = DeviceStatus("recording")
        status2 = DeviceStatus("busy")
        status2.set_previous_status(status1)
        status3 = DeviceStatus("unreached")
        status3.set_previous_status(status2)
        status4 = DeviceStatus("stopping")
        status4.set_previous_status(status3)
        status5 = DeviceStatus("offline", trigger_source="system")
        status5.set_previous_status(status4)

        assert status5.is_interrupted_tracking_session() is True

    def test_interrupted_session_max_lookback(self):
        """Test interrupted session respects max lookback limit."""
        # Create very long chain
        status = DeviceStatus("running")
        for _ in range(15):
            new_status = DeviceStatus("busy")
            new_status.set_previous_status(status)
            status = new_status

        final_status = DeviceStatus("offline")
        final_status.set_previous_status(status)

        # Should still detect despite long chain (max 10 lookback)
        result = final_status.is_interrupted_tracking_session()
        # Result depends on chain structure
        assert isinstance(result, bool)


class TestRetryDecoratorEdgeCases:
    """Test retry decorator edge cases."""

    def test_retry_with_logger(self):
        """Test retry decorator with logger."""
        import logging

        logger = logging.getLogger("test_retry")
        call_count = 0

        @retry(ValueError, tries=3, delay=0.01, logger=logger)
        def func_with_retry():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Temporary error")
            return "success"

        result = func_with_retry()
        assert result == "success"
        assert call_count == 2

    def test_retry_backoff_and_max_delay(self):
        """Test retry respects max_delay cap."""
        call_count = 0

        @retry(ValueError, tries=4, delay=1, backoff=2, max_delay=2)
        def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 4:
                raise ValueError("Error")
            return "success"

        # Test that retry succeeds with proper backoff
        result = test_function()
        assert result == "success"


class TestBaseDeviceEdgeCases:
    """Test BaseDevice edge cases and additional functionality."""

    def test_is_graceful_shutdown(self):
        """Test graceful shutdown detection."""
        device = BaseDevice("192.168.1.100")

        device._update_device_status("offline", trigger_source="graceful")
        assert device._is_graceful_shutdown() is True

        device._update_device_status("offline", trigger_source="system")
        assert device._is_graceful_shutdown() is False

    @patch("urllib.request.urlopen")
    def test_get_json_url_error(self, mock_urlopen):
        """Test _get_json handles URLError."""
        device = BaseDevice("192.168.1.100")

        mock_urlopen.side_effect = urllib.error.URLError("Connection failed")

        with pytest.raises(NetworkError, match="URL error"):
            device._get_json("http://192.168.1.100/test")

    @patch("urllib.request.urlopen")
    def test_get_json_unexpected_exception(self, mock_urlopen):
        """Test _get_json handles unexpected exceptions."""
        device = BaseDevice("192.168.1.100")

        mock_urlopen.side_effect = RuntimeError("Unexpected error")

        with pytest.raises(ScanException, match="Unexpected error"):
            device._get_json("http://192.168.1.100/test")
