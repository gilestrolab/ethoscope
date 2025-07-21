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
from .base_scanner import BaseDevice, DeviceScanner, ScanException, NetworkError, DeviceError
from .ethoscope_scanner import Ethoscope, EthoscopeScanner
from .sensor_scanner import Sensor, SensorScanner
from .ethoscope_streaming import EthoscopeStreamManager

__all__ = [
    'BaseDevice',
    'DeviceScanner', 
    'ScanException',
    'NetworkError',
    'DeviceError',
    'Ethoscope',
    'EthoscopeScanner',
    'Sensor', 
    'SensorScanner',
    'EthoscopeStreamManager'
]