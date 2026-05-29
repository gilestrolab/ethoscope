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
    """``DeviceStatus`` is now a small data holder: name + timestamp + age.

    The previous, larger surface (chain walking, user-trigger flags,
    initial-discovery markers, alert decisions) moved into the scanner's
    run-centric finalisation logic — see ``TestEthoscopeRunReconciliation``
    in test_ethoscope_scanner.py.
    """

    def test_initialization_valid_status(self):
        status = DeviceStatus("running")
        assert status.status_name == "running"

    def test_initialization_invalid_status(self):
        with pytest.raises(ValueError, match="Invalid status"):
            DeviceStatus("invalid_status")

    def test_status_age_tracking(self):
        status = DeviceStatus("running")
        time.sleep(0.1)
        assert status.get_age_seconds() >= 0.1
        assert status.get_age_minutes() >= 0.001

    def test_timeout_exceeded(self):
        status = DeviceStatus("unreached")
        # Backdate to ~25 minutes ago.
        status._timestamp = time.time() - 25 * 60
        assert status.is_timeout_exceeded(20) is True
        assert status.is_timeout_exceeded(30) is False

    def test_is_active_tracking(self):
        assert DeviceStatus("running").is_active_tracking() is True
        assert DeviceStatus("recording").is_active_tracking() is True
        assert DeviceStatus("streaming").is_active_tracking() is True
        assert DeviceStatus("stopped").is_active_tracking() is False
        assert DeviceStatus("unreached").is_active_tracking() is False

    def test_to_dict_serialization(self):
        status = DeviceStatus("running")
        d = status.to_dict()
        assert d["status_name"] == "running"
        assert "timestamp" in d

    def test_from_dict_deserialization(self):
        ts = time.time() - 5
        status = DeviceStatus.from_dict({"status_name": "stopped", "timestamp": ts})
        assert status.status_name == "stopped"
        assert status.timestamp == ts


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

        mock_urlopen.side_effect = TimeoutError("Connection timeout")

        with pytest.raises(NetworkError, match="Timeout"):
            device._get_json("http://192.168.1.100/id")

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

    def test_effective_refresh_period_unreachable(self):
        """Devices with too many consecutive errors back off to slow polling."""
        device = BaseDevice("192.168.1.100", refresh_period=5)
        device._consecutive_errors = device._max_consecutive_errors

        assert (
            device._get_effective_refresh_period() == device._unreachable_refresh_period
        )

    def test_effective_refresh_period_recovers_when_errors_reset(self):
        """Once a successful poll resets the error count, polling speeds up again."""
        device = BaseDevice("192.168.1.100", refresh_period=5)
        device._consecutive_errors = device._max_consecutive_errors
        assert device._get_effective_refresh_period() != 5

        device._consecutive_errors = 0
        assert device._get_effective_refresh_period() == 5


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

    def test_handle_device_error_increments_counter(self):
        """Each handled error bumps the consecutive-error counter."""
        device = BaseDevice("192.168.1.100")
        error = urllib.error.URLError("[Errno 111] Connection refused")

        for i in range(1, 6):
            device._handle_device_error(error)
            assert device._consecutive_errors == i

    def test_handle_device_error_marks_offline(self):
        """Errors mark the device offline via _reset_info."""
        device = BaseDevice("192.168.1.100")
        device._update_device_status("running")

        device._handle_device_error(urllib.error.URLError("network down"))

        assert device.get_device_status().status_name == "offline"

    def test_handle_device_error_does_not_block_polling(self):
        """Crossing the error threshold slows polling but never stops it."""
        device = BaseDevice("192.168.1.100", refresh_period=5)
        error = urllib.error.URLError("Generic error")

        for _ in range(device._max_consecutive_errors):
            device._handle_device_error(error)

        # Polling backs off but the device remains active.
        assert (
            device._get_effective_refresh_period() == device._unreachable_refresh_period
        )
        assert device._is_online is True

    def test_handle_device_error_progressive_logging(self):
        """Error #1 logs info, threshold logs warning, others stay debug."""
        device = BaseDevice("192.168.1.100")
        device._max_consecutive_errors = 5
        error = urllib.error.URLError("Test error")

        with (
            patch.object(device._logger, "info") as info_log,
            patch.object(device._logger, "warning") as warning_log,
        ):
            device._handle_device_error(error)
            assert info_log.call_count == 1
            for _ in range(3):
                device._handle_device_error(error)
            # Hitting the threshold logs a single warning
            device._handle_device_error(error)
            assert warning_log.call_count == 1


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
        device._update_device_status("running")
        assert device._device_status.status_name == "running"

    def test_update_device_status_preserves_error_count(self):
        """Errors live on BaseDevice, not on DeviceStatus, so a status change
        does not reset the consecutive-error count."""
        device = BaseDevice("192.168.1.100")
        device._consecutive_errors = 2
        device._update_device_status("offline")
        assert device._consecutive_errors == 2
        assert device._info["consecutive_errors"] == 2

    def test_info_includes_status_details(self):
        """Test that info() includes status details."""
        device = BaseDevice("192.168.1.100")
        device._update_device_status("running")

        info = device.info()
        assert info["status"] == "running"
        assert info["status_details"]["status"] == "running"
        assert "age_minutes" in info["status_details"]
        assert "consecutive_errors" in info["status_details"]

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
    def test_add_existing_device_resets_errors(self, mock_browser, mock_zeroconf):
        """Re-adding a known device clears its error counter and refreshes status."""
        scanner = DeviceScanner()
        scanner.start()

        scanner.add("192.168.1.100", 9000, name="test.local")
        assert len(scanner.devices) == 1

        # Simulate the device having racked up errors and gone offline
        scanner.devices[0]._consecutive_errors = 25

        scanner.add("192.168.1.100", 9000, name="test.local")

        assert len(scanner.devices) == 1
        assert scanner.devices[0]._consecutive_errors == 0

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

        # Device is marked offline; the device thread keeps probing on the
        # slow cadence so it can recover automatically when it comes back.
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
    def test_update_service_updates_device_address(self, mock_browser, mock_zeroconf):
        """update_service should rewrite the IP/port of an existing device.

        Reason: a Zeroconf TXT/address change (typically a DHCP renewal that
        moves the device to a new IP) fires update_service rather than
        add_service. Before this fix the handler was a no-op, so the node kept
        polling the stale IP forever.
        """
        scanner = DeviceScanner()
        scanner.start()

        scanner.add("192.168.1.100", 9000, name="ETHO-test.local")
        assert len(scanner.devices) == 1
        device = scanner.devices[0]
        # `add()` records the mDNS name on the device for later lookup.
        assert device.zeroconf_name == "ETHO-test.local"

        mock_zc = MagicMock()
        new_info = MagicMock()
        new_info.addresses = [socket.inet_aton("192.168.1.200")]
        new_info.port = 9000
        new_info.properties = {}
        mock_zc.get_service_info.return_value = new_info

        scanner.update_service(mock_zc, "_device._tcp.local.", "ETHO-test.local")

        assert len(scanner.devices) == 1
        assert scanner.devices[0].ip() == "192.168.1.200"

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_update_service_unknown_name_falls_back_to_add(
        self, mock_browser, mock_zeroconf
    ):
        """An update for an unknown service name should add the device."""
        scanner = DeviceScanner()
        scanner.start()

        mock_zc = MagicMock()
        new_info = MagicMock()
        new_info.addresses = [socket.inet_aton("192.168.1.150")]
        new_info.port = 9000
        new_info.properties = {}
        mock_zc.get_service_info.return_value = new_info

        scanner.update_service(mock_zc, "_device._tcp.local.", "ETHO-new.local")

        assert len(scanner.devices) == 1
        assert scanner.devices[0].ip() == "192.168.1.150"

        scanner.stop()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_update_service_when_not_running(self, mock_browser, mock_zeroconf):
        """update_service is a no-op when the scanner is stopped."""
        scanner = DeviceScanner()
        # Don't start scanner

        mock_zc = MagicMock()
        scanner.update_service(mock_zc, "_device._tcp.local.", "ETHO-test.local")
        # Must not call into zeroconf at all when stopped.
        mock_zc.get_service_info.assert_not_called()

    @patch("ethoscope_node.scanner.base_scanner.Zeroconf")
    @patch("ethoscope_node.scanner.base_scanner.ServiceBrowser")
    def test_add_reannounce_at_new_ip_updates_existing(
        self, mock_browser, mock_zeroconf
    ):
        """A re-announce at a new IP should update the existing device entry.

        Reason: if a device re-announces (add_service) at a new IP without us
        having processed an update_service first, the IP-based dedup branch
        wouldn't find it, and the post-creation ID check would reject the new
        entry — leaving the original stuck at the stale IP. Matching by
        zeroconf_name first sidesteps that.
        """
        scanner = DeviceScanner()
        scanner.start()

        scanner.add("192.168.1.100", 9000, name="ETHO-test.local")
        assert len(scanner.devices) == 1

        scanner.add("192.168.1.200", 9000, name="ETHO-test.local")

        assert len(scanner.devices) == 1
        assert scanner.devices[0].ip() == "192.168.1.200"

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
    """Edge cases for the (now small) DeviceStatus contract."""

    def test_timeout_exceeded_fresh_status(self):
        """A fresh status has not exceeded any positive timeout."""
        status = DeviceStatus("unreached")
        assert status.is_timeout_exceeded(20) is False

    def test_string_representations(self):
        status = DeviceStatus("running")
        assert "running" in str(status)
        assert "running" in repr(status)


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
