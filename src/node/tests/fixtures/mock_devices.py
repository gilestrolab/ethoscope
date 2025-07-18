"""
Mock devices and device-related utilities for testing.

This module provides mock implementations of ethoscope devices and related
components for use in tests.
"""

from unittest.mock import Mock, MagicMock
import datetime
import json
from typing import List, Dict, Any, Optional


class MockEthoscopeDevice:
    """Mock implementation of an Ethoscope device."""
    
    def __init__(self, device_id: str = "test_device_001", **kwargs):
        """Initialize mock device with default values."""
        self.id = device_id
        self.name = kwargs.get("name", f"Test Device {device_id}")
        self.ip = kwargs.get("ip", "192.168.1.100")
        self.port = kwargs.get("port", 9000)
        self.status = kwargs.get("status", "running")
        self.last_seen = kwargs.get("last_seen", datetime.datetime.now().isoformat())
        self.hardware_version = kwargs.get("hardware_version", "1.0")
        self.software_version = kwargs.get("software_version", "1.0.0")
        self.tracking_enabled = kwargs.get("tracking_enabled", True)
        self.video_recording = kwargs.get("video_recording", False)
        self.stimulation_enabled = kwargs.get("stimulation_enabled", False)
        self._api_responses = {}
        
    def get_api_response(self, endpoint: str) -> Dict[str, Any]:
        """Get mock API response for a specific endpoint."""
        if endpoint in self._api_responses:
            return self._api_responses[endpoint]
        
        # Default responses for common endpoints
        default_responses = {
            "/status": {
                "status": self.status,
                "device_id": self.id,
                "name": self.name,
                "tracking": self.tracking_enabled,
                "video_recording": self.video_recording,
                "stimulation": self.stimulation_enabled,
                "timestamp": datetime.datetime.now().isoformat()
            },
            "/info": {
                "device_id": self.id,
                "name": self.name,
                "hardware_version": self.hardware_version,
                "software_version": self.software_version,
                "ip": self.ip,
                "port": self.port
            },
            "/data": {
                "device_id": self.id,
                "tracking_data": [
                    {
                        "timestamp": datetime.datetime.now().isoformat(),
                        "roi_id": 1,
                        "x": 100.5,
                        "y": 200.3,
                        "width": 50,
                        "height": 30,
                        "angle": 45.0,
                        "area": 1500
                    }
                ]
            }
        }
        
        return default_responses.get(endpoint, {})
    
    def set_api_response(self, endpoint: str, response: Dict[str, Any]):
        """Set custom API response for an endpoint."""
        self._api_responses[endpoint] = response
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert device to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "ip": self.ip,
            "port": self.port,
            "status": self.status,
            "last_seen": self.last_seen,
            "hardware_version": self.hardware_version,
            "software_version": self.software_version,
            "tracking_enabled": self.tracking_enabled,
            "video_recording": self.video_recording,
            "stimulation_enabled": self.stimulation_enabled
        }


class MockDeviceScanner:
    """Mock implementation of device scanner."""
    
    def __init__(self):
        """Initialize mock device scanner."""
        self.devices = []
        self.is_scanning = False
        self.scan_interval = 30
        
    def add_device(self, device: MockEthoscopeDevice):
        """Add a mock device to the scanner."""
        self.devices.append(device)
    
    def remove_device(self, device_id: str):
        """Remove a device from the scanner."""
        self.devices = [d for d in self.devices if d.id != device_id]
    
    def get_devices(self) -> List[MockEthoscopeDevice]:
        """Get all discovered devices."""
        return self.devices.copy()
    
    def get_device(self, device_id: str) -> Optional[MockEthoscopeDevice]:
        """Get a specific device by ID."""
        for device in self.devices:
            if device.id == device_id:
                return device
        return None
    
    def start_scan(self):
        """Start device scanning."""
        self.is_scanning = True
    
    def stop_scan(self):
        """Stop device scanning."""
        self.is_scanning = False
    
    def scan_once(self) -> List[MockEthoscopeDevice]:
        """Perform a single scan and return devices."""
        return self.get_devices()


class MockDeviceManager:
    """Mock implementation of device manager."""
    
    def __init__(self):
        """Initialize mock device manager."""
        self.devices = {}
        self.scanner = MockDeviceScanner()
        
    def add_device(self, device: MockEthoscopeDevice):
        """Add a device to the manager."""
        self.devices[device.id] = device
        self.scanner.add_device(device)
    
    def remove_device(self, device_id: str):
        """Remove a device from the manager."""
        if device_id in self.devices:
            del self.devices[device_id]
        self.scanner.remove_device(device_id)
    
    def get_device(self, device_id: str) -> Optional[MockEthoscopeDevice]:
        """Get a device by ID."""
        return self.devices.get(device_id)
    
    def get_all_devices(self) -> List[MockEthoscopeDevice]:
        """Get all managed devices."""
        return list(self.devices.values())
    
    def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """Get device status."""
        device = self.get_device(device_id)
        if device:
            return device.get_api_response("/status")
        return {}
    
    def update_device_status(self, device_id: str, status: str):
        """Update device status."""
        device = self.get_device(device_id)
        if device:
            device.status = status
            device.last_seen = datetime.datetime.now().isoformat()


def create_mock_device_fleet(count: int = 5) -> List[MockEthoscopeDevice]:
    """Create a fleet of mock devices for testing."""
    devices = []
    for i in range(count):
        device = MockEthoscopeDevice(
            device_id=f"device_{i:03d}",
            name=f"Test Device {i+1}",
            ip=f"192.168.1.{100+i}",
            status="running" if i % 2 == 0 else "stopped",
            tracking_enabled=i % 3 != 0,
            video_recording=i % 4 == 0,
            stimulation_enabled=i % 5 == 0
        )
        devices.append(device)
    return devices


def create_mock_device_manager_with_fleet(count: int = 5) -> MockDeviceManager:
    """Create a mock device manager with a fleet of devices."""
    manager = MockDeviceManager()
    devices = create_mock_device_fleet(count)
    
    for device in devices:
        manager.add_device(device)
    
    return manager