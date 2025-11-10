"""
Test module for device renaming functionality in the ethoscope scanner.

This module tests the ability of the scanner to properly handle device renaming
scenarios, particularly when ETHOSCOPE_000 devices are renamed to proper names.
"""

import time
from threading import Lock
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from ethoscope_node.scanner.base_scanner import ScanException
from ethoscope_node.scanner.ethoscope_scanner import Ethoscope, EthoscopeScanner
from ethoscope_node.utils.etho_db import ExperimentalDB


class TestDeviceRenaming:
    """Test device renaming scenarios."""

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
            # Set scanner as running to allow device addition
            self.scanner._is_running = True

    def create_mock_device(
        self, device_id: str, device_name: str, ip: str, status: str = "offline"
    ):
        """Create a mock ethoscope device."""
        device = Mock(spec=Ethoscope)
        device.id.return_value = device_id
        device.name = device_name
        device.ip.return_value = ip
        device._skip_scanning = False
        device._device_status = Mock()
        device._device_status.status_name = status
        device._lock = Lock()
        device._info = {
            "name": device_name,
            "id": device_id,
            "ip": ip,
            "status": status,
        }
        device.info.return_value = device._info
        device.reset_error_state = Mock()
        device.skip_scanning = Mock()
        device._update_device_status = Mock()
        return device

    def test_device_id_change_from_ethoscope_000(self):
        """Test handling of device ID change from ETHOSCOPE_000 to proper name."""
        # Create initial device with ETHOSCOPE_000
        initial_device = self.create_mock_device(
            device_id="ETHOSCOPE_000", device_name="ETHOSCOPE_000", ip="192.168.1.100"
        )

        # Mock _update_id to simulate device renaming
        def mock_update_id():
            # Simulate device being renamed
            initial_device.id.return_value = "012345678901234567890123456789ab"
            initial_device.info.return_value.update(
                {"id": "012345678901234567890123456789ab", "name": "ETHOSCOPE_012"}
            )

        initial_device._update_id = Mock(side_effect=mock_update_id)

        # Add device to scanner
        with self.scanner._lock:
            self.scanner.devices = [initial_device]

        # Mock database calls
        self.mock_edb.getEthoscope.return_value = {}
        self.mock_edb.updateEthoscopes = Mock()

        # Simulate device rediscovery (zeroconf callback)
        self.scanner.add(
            "192.168.1.100", 9000, "ETHOSCOPE_012-012345678901234567890123456789ab"
        )

        # Verify that _update_id was called
        initial_device._update_id.assert_called_once()

        # Verify database was updated for the renamed device
        self.mock_edb.updateEthoscopes.assert_called_with(
            ethoscope_id="012345678901234567890123456789ab",
            ethoscope_name="ETHOSCOPE_012",
            last_ip="192.168.1.100",
            status="offline",
        )

    def test_device_id_change_from_real_id_to_another(self):
        """Test handling of device ID change from one real ID to another."""
        # Create initial device with real ID
        initial_device = self.create_mock_device(
            device_id="old123456789012345678901234567890",
            device_name="ETHOSCOPE_011",
            ip="192.168.1.100",
        )

        # Mock _update_id to simulate device getting new ID
        def mock_update_id():
            # Simulate device getting new ID
            initial_device.id.return_value = "new123456789012345678901234567890"
            initial_device.info.return_value.update(
                {"id": "new123456789012345678901234567890", "name": "ETHOSCOPE_013"}
            )

        initial_device._update_id = Mock(side_effect=mock_update_id)

        # Add device to scanner
        with self.scanner._lock:
            self.scanner.devices = [initial_device]

        # Mock database calls - old device exists
        self.mock_edb.getEthoscope.return_value = {
            "old123456789012345678901234567890": {
                "ethoscope_id": "old123456789012345678901234567890",
                "ethoscope_name": "ETHOSCOPE_011",
                "last_ip": "192.168.1.100",
                "active": 1,
            }
        }
        self.mock_edb.updateEthoscopes = Mock()

        # Simulate device rediscovery
        self.scanner.add(
            "192.168.1.100", 9000, "ETHOSCOPE_013-new123456789012345678901234567890"
        )

        # Verify old device was retired
        self.mock_edb.updateEthoscopes.assert_any_call(
            ethoscope_id="old123456789012345678901234567890", active=0
        )

        # Verify new device was created
        self.mock_edb.updateEthoscopes.assert_any_call(
            ethoscope_id="new123456789012345678901234567890",
            ethoscope_name="ETHOSCOPE_013",
            last_ip="192.168.1.100",
            status="offline",
            comments="Renamed from old123456789012345678901234567890",
        )

    def test_no_id_change_scenario(self):
        """Test that no database updates occur when device ID doesn't change."""
        # Create device with consistent ID
        device = self.create_mock_device(
            device_id="consistent123456789012345678901234",
            device_name="ETHOSCOPE_012",
            ip="192.168.1.100",
        )

        # Mock _update_id to return same ID
        device._update_id = Mock()  # ID remains the same

        # Add device to scanner
        with self.scanner._lock:
            self.scanner.devices = [device]

        # Mock database calls
        self.mock_edb.updateEthoscopes = Mock()

        # Simulate device rediscovery
        self.scanner.add(
            "192.168.1.100", 9000, "ETHOSCOPE_012-consistent123456789012345678901234"
        )

        # Verify _update_id was called
        device._update_id.assert_called_once()

        # Verify no database updates for ID change (only status updates)
        # Should not call updateEthoscopes for ID changes
        update_calls = self.mock_edb.updateEthoscopes.call_args_list
        id_change_calls = [call for call in update_calls if "comments" in str(call)]
        assert len(id_change_calls) == 0

    def test_update_id_failure_handling(self):
        """Test that _update_id failures are handled gracefully."""
        # Create device
        device = self.create_mock_device(
            device_id="test123456789012345678901234567890",
            device_name="ETHOSCOPE_012",
            ip="192.168.1.100",
        )

        # Mock _update_id to raise an exception
        device._update_id = Mock(side_effect=ScanException("Cannot connect to device"))

        # Add device to scanner
        with self.scanner._lock:
            self.scanner.devices = [device]

        # Mock database calls
        self.mock_edb.updateEthoscopes = Mock()

        # Simulate device rediscovery - should not crash
        self.scanner.add(
            "192.168.1.100", 9000, "ETHOSCOPE_012-test123456789012345678901234567890"
        )

        # Verify _update_id was called and failed
        device._update_id.assert_called_once()

        # Verify device status was still updated despite ID update failure
        device._update_device_status.assert_called()

    def test_handle_device_id_change_database_error(self):
        """Test handling of database errors during device ID change."""
        # Create device
        device = Mock(spec=Ethoscope)
        device.info.return_value = {
            "name": "ETHOSCOPE_012",
            "id": "new123456789012345678901234567890",
        }
        device.ip.return_value = "192.168.1.100"

        # Mock database to raise error
        self.mock_edb.updateEthoscopes.side_effect = Exception("Database error")

        # Should not crash
        self.scanner._handle_device_id_change(device, "old_id", "new_id")

        # Verify database was attempted to be updated
        self.mock_edb.updateEthoscopes.assert_called()

    def test_ethoscope_000_special_handling(self):
        """Test special handling for ETHOSCOPE_000 devices."""
        device = Mock(spec=Ethoscope)
        device.info.return_value = {
            "name": "ETHOSCOPE_012",
            "id": "012345678901234567890123456789ab",
        }
        device.ip.return_value = "192.168.1.100"

        self.mock_edb.updateEthoscopes = Mock()

        # Test ETHOSCOPE_000 -> new ID
        self.scanner._handle_device_id_change(
            device, "ETHOSCOPE_000", "012345678901234567890123456789ab"
        )

        # Should create new entry without retiring old one
        self.mock_edb.updateEthoscopes.assert_called_once_with(
            ethoscope_id="012345678901234567890123456789ab",
            ethoscope_name="ETHOSCOPE_012",
            last_ip="192.168.1.100",
            status="offline",
        )

        # Reset mock
        self.mock_edb.updateEthoscopes.reset_mock()

        # Test empty ID -> new ID
        self.scanner._handle_device_id_change(
            device, "", "012345678901234567890123456789ab"
        )

        # Should also create new entry without retiring
        self.mock_edb.updateEthoscopes.assert_called_once_with(
            ethoscope_id="012345678901234567890123456789ab",
            ethoscope_name="ETHOSCOPE_012",
            last_ip="192.168.1.100",
            status="offline",
        )

    def test_device_rediscovery_triggers_info_update(self):
        """Test that device rediscovery triggers proper info updates."""
        device = self.create_mock_device(
            device_id="test123456789012345678901234567890",
            device_name="ETHOSCOPE_012",
            ip="192.168.1.100",
            status="offline",
        )
        device._update_id = Mock()  # No ID change

        # Add device to scanner
        with self.scanner._lock:
            self.scanner.devices = [device]

        # Simulate device rediscovery
        self.scanner.add(
            "192.168.1.100", 9000, "ETHOSCOPE_012-test123456789012345678901234567890"
        )

        # Verify device was properly reset and re-enabled
        device.reset_error_state.assert_called_once()
        device.skip_scanning.assert_called_once_with(False)
        device._update_device_status.assert_called_with(
            "offline", trigger_source="system"
        )

        # Verify device info was updated
        assert device._info["last_seen"] <= time.time()

    def test_zeroconf_name_update(self):
        """Test that zeroconf name is properly updated during rediscovery."""
        device = self.create_mock_device(
            device_id="test123456789012345678901234567890",
            device_name="ETHOSCOPE_012",
            ip="192.168.1.100",
        )
        device._update_id = Mock()  # No ID change
        device.zeroconf_name = "old_name"

        # Add device to scanner
        with self.scanner._lock:
            self.scanner.devices = [device]

        # Simulate device rediscovery with new zeroconf name
        new_zeroconf_name = (
            "ETHOSCOPE_012-test123456789012345678901234567890._ethoscope._tcp.local."
        )
        self.scanner.add("192.168.1.100", 9000, new_zeroconf_name)

        # Verify zeroconf name was updated
        assert device.zeroconf_name == new_zeroconf_name
