"""
Ethoscope Node API Package

This package contains modular API components for the Ethoscope Node Server.
Each module handles a specific domain of functionality to improve maintainability
and separation of concerns.

Modules:
- base: Common infrastructure and utilities
- device_api: Device management and control
- backup_api: Backup system management
- sensor_api: Sensor data and configuration
- roi_template_api: ROI template management
- node_api: Node system management
- file_api: File operations and downloads
- database_api: Database queries and experiments
- setup_api: Installation wizard and first-time setup
- tunnel_utils: Tunnel configuration and URL management utilities
"""

from .auth_api import AuthAPI
from .backup_api import BackupAPI
from .base import BaseAPI
from .database_api import DatabaseAPI
from .device_api import DeviceAPI
from .file_api import FileAPI
from .node_api import NodeAPI
from .roi_template_api import ROITemplateAPI
from .sensor_api import SensorAPI
from .setup_api import SetupAPI
from .tunnel_utils import TunnelUtils

__all__ = [
    "BaseAPI",
    "DeviceAPI",
    "BackupAPI",
    "SensorAPI",
    "ROITemplateAPI",
    "NodeAPI",
    "FileAPI",
    "DatabaseAPI",
    "SetupAPI",
    "TunnelUtils",
    "AuthAPI",
]
