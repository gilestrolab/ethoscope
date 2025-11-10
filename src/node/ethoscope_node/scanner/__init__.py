"""
Scanner package for Ethoscope node.

This package provides device scanning and management functionality for both
Ethoscope devices and sensors in the distributed Ethoscope system.

Main components:
- BaseDevice and DeviceScanner: Base classes for all device types
- Ethoscope and EthoscopeScanner: Ethoscope-specific device management
- Sensor and SensorScanner: Sensor device management
- EthoscopeStreamManager: Video streaming management
"""

# Import main classes for easy access
from .base_scanner import (
    BaseDevice,
    DeviceError,
    DeviceScanner,
    NetworkError,
    ScanException,
)
from .ethoscope_scanner import Ethoscope, EthoscopeScanner
from .ethoscope_streaming import EthoscopeStreamManager
from .sensor_scanner import Sensor, SensorScanner

__all__ = [
    "BaseDevice",
    "DeviceScanner",
    "ScanException",
    "NetworkError",
    "DeviceError",
    "Ethoscope",
    "EthoscopeScanner",
    "Sensor",
    "SensorScanner",
    "EthoscopeStreamManager",
]
