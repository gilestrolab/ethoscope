"""
Test module for verifying proper filtering of invalid devices in the ethoscope scanner.

This module tests that devices with empty names, empty IPs, or empty device IDs
are properly filtered out and do not appear in the device list.
"""

import time
from threading import Lock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from ethoscope_node.scanner.ethoscope_scanner import Ethoscope
from ethoscope_node.scanner.ethoscope_scanner import EthoscopeScanner
from ethoscope_node.utils.etho_db import ExperimentalDB


class TestInvalidDeviceFiltering:
    """Test filtering of invalid devices from database and scanner."""

    def setup_method(self):
        """Setup test environment."""
        # Create mock configuration
        self.mock_config = Mock()
        self.mock_config.get_custom.return_value = {}

        # Create mock database
        self.mock_edb = Mock(spec=ExperimentalDB)

        # Create scanner with mocked database
        with patch(
            "ethoscope_node.scanner.ethoscope_scanner.ExperimentalDB"
        ) as mock_edb_class:
            mock_edb_class.return_value = self.mock_edb
            self.scanner = EthoscopeScanner(
                device_refresh_period=1, config=self.mock_config
            )

    def test_filter_empty_device_id_from_database(self):
        """Test that devices with empty IDs are filtered out from database results."""
        # Mock database response with invalid device
        self.mock_edb.getEthoscope.return_value = {
            "": {  # Empty device ID
                "ethoscope_name": "Some Device",
                "status": "offline",
                "last_ip": "192.168.1.100",
                "last_seen": time.time(),
                "active": 1,
            },
            "valid_device_id": {
                "ethoscope_name": "Valid Device",
                "status": "offline",
                "last_ip": "192.168.1.101",
                "last_seen": time.time(),
                "active": 1,
            },
        }

        devices_info = self.scanner.get_all_devices_info()

        # Should only contain the valid device
        assert len(devices_info) == 1
        assert "valid_device_id" in devices_info
        assert "" not in devices_info
        assert devices_info["valid_device_id"]["name"] == "Valid Device"

    def test_filter_none_name_and_none_ip_from_database(self):
        """Test that devices with None name and None IP are filtered out."""
        # Mock database response with invalid device
        self.mock_edb.getEthoscope.return_value = {
            "device_with_none_values": {
                "ethoscope_name": "None",  # String 'None'
                "status": "offline",
                "last_ip": "None",  # String 'None'
                "last_seen": time.time(),
                "active": 1,
            },
            "device_with_empty_values": {
                "ethoscope_name": "",  # Empty string
                "status": "offline",
                "last_ip": "",  # Empty string
                "last_seen": time.time(),
                "active": 1,
            },
            "valid_device": {
                "ethoscope_name": "Valid Device",
                "status": "offline",
                "last_ip": "192.168.1.101",
                "last_seen": time.time(),
                "active": 1,
            },
        }

        devices_info = self.scanner.get_all_devices_info()

        # Should only contain the valid device
        assert len(devices_info) == 1
        assert "valid_device" in devices_info
        assert "device_with_none_values" not in devices_info
        assert "device_with_empty_values" not in devices_info

    def test_allow_device_with_valid_ip_but_empty_name(self):
        """Test that devices with valid IP but empty name are allowed."""
        # Mock database response
        self.mock_edb.getEthoscope.return_value = {
            "device_with_ip_only": {
                "ethoscope_name": "",  # Empty name
                "status": "offline",
                "last_ip": "192.168.1.100",  # Valid IP
                "last_seen": time.time(),
                "active": 1,
            }
        }

        devices_info = self.scanner.get_all_devices_info()

        # Should contain the device with valid IP
        assert len(devices_info) == 1
        assert "device_with_ip_only" in devices_info
        assert devices_info["device_with_ip_only"]["ip"] == "192.168.1.100"

    def test_allow_device_with_valid_name_but_empty_ip(self):
        """Test that devices with valid name but empty IP are allowed."""
        # Mock database response
        self.mock_edb.getEthoscope.return_value = {
            "device_with_name_only": {
                "ethoscope_name": "Valid Device Name",  # Valid name
                "status": "offline",
                "last_ip": "",  # Empty IP
                "last_seen": time.time(),
                "active": 1,
            }
        }

        devices_info = self.scanner.get_all_devices_info()

        # Should contain the device with valid name
        assert len(devices_info) == 1
        assert "device_with_name_only" in devices_info
        assert devices_info["device_with_name_only"]["name"] == "Valid Device Name"

    def test_filter_scanner_devices_with_empty_id(self):
        """Test that scanner devices with empty IDs are filtered out."""

        # Mock database to return no devices
        self.mock_edb.getEthoscope.return_value = {}

        # Create mock devices
        valid_device = Mock(spec=Ethoscope)
        valid_device.id.return_value = "valid_device_id"
        valid_device.name = "Valid Device"
        valid_device.info.return_value = {
            "name": "Valid Device",
            "id": "valid_device_id",
            "ip": "192.168.1.100",
            "status": "offline",
        }

        invalid_device = Mock(spec=Ethoscope)
        invalid_device.id.return_value = ""  # Empty ID
        invalid_device.name = "Invalid Device"
        invalid_device.info.return_value = {
            "name": "Invalid Device",
            "id": "",
            "ip": "192.168.1.101",
            "status": "offline",
        }

        # Add devices to scanner
        with self.scanner._lock:
            self.scanner.devices = [valid_device, invalid_device]

        devices_info = self.scanner.get_all_devices_info()

        # Should only contain the valid device
        assert len(devices_info) == 1
        assert "valid_device_id" in devices_info
        assert devices_info["valid_device_id"]["name"] == "Valid Device"

    def test_filter_scanner_devices_with_no_name_and_no_ip(self):
        """Test that scanner devices with no name and no IP are filtered out."""

        # Mock database to return no devices
        self.mock_edb.getEthoscope.return_value = {}

        # Create mock devices
        valid_device = Mock(spec=Ethoscope)
        valid_device.id.return_value = "valid_device_id"
        valid_device.name = "Valid Device"
        valid_device.info.return_value = {
            "name": "Valid Device",
            "id": "valid_device_id",
            "ip": "192.168.1.100",
            "status": "offline",
        }

        invalid_device = Mock(spec=Ethoscope)
        invalid_device.id.return_value = "invalid_device_id"
        invalid_device.name = "N/A"
        invalid_device.info.return_value = {
            "name": "",  # Empty name
            "id": "invalid_device_id",
            "ip": "",  # Empty IP
            "status": "offline",
        }

        # Add devices to scanner
        with self.scanner._lock:
            self.scanner.devices = [valid_device, invalid_device]

        devices_info = self.scanner.get_all_devices_info()

        # Should only contain the valid device
        assert len(devices_info) == 1
        assert "valid_device_id" in devices_info
        assert devices_info["valid_device_id"]["name"] == "Valid Device"

    def test_database_error_handling(self):
        """Test that database errors are handled gracefully."""
        # Mock database to raise an exception
        self.mock_edb.getEthoscope.side_effect = Exception("Database error")

        # Should return empty dict without crashing
        devices_info = self.scanner.get_all_devices_info()
        assert devices_info == {}

    def test_mixed_valid_and_invalid_devices(self):
        """Test comprehensive filtering with mix of valid and invalid devices."""
        # Mock database with mix of valid and invalid devices
        self.mock_edb.getEthoscope.return_value = {
            "": {  # Invalid: empty ID
                "ethoscope_name": "Device 1",
                "status": "offline",
                "last_ip": "192.168.1.100",
                "active": 1,
            },
            "device2": {  # Invalid: no name and no IP
                "ethoscope_name": "",
                "status": "offline",
                "last_ip": "",
                "active": 1,
            },
            "device3": {  # Invalid: None values
                "ethoscope_name": "None",
                "status": "offline",
                "last_ip": "None",
                "active": 1,
            },
            "device4": {  # Valid: has name
                "ethoscope_name": "Valid Device 4",
                "status": "offline",
                "last_ip": "",
                "active": 1,
            },
            "device5": {  # Valid: has IP
                "ethoscope_name": "",
                "status": "offline",
                "last_ip": "192.168.1.105",
                "active": 1,
            },
            "device6": {  # Valid: has both
                "ethoscope_name": "Valid Device 6",
                "status": "offline",
                "last_ip": "192.168.1.106",
                "active": 1,
            },
        }

        devices_info = self.scanner.get_all_devices_info()

        # Should only contain valid devices
        assert len(devices_info) == 3
        assert "device4" in devices_info
        assert "device5" in devices_info
        assert "device6" in devices_info

        # Invalid devices should not be present
        assert "" not in devices_info
        assert "device2" not in devices_info
        assert "device3" not in devices_info

        # Verify device info
        assert devices_info["device4"]["name"] == "Valid Device 4"
        assert devices_info["device5"]["ip"] == "192.168.1.105"
        assert devices_info["device6"]["name"] == "Valid Device 6"
        assert devices_info["device6"]["ip"] == "192.168.1.106"
