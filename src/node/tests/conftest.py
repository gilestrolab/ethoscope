"""
Test configuration and fixtures for ethoscope_node tests.

This module provides common pytest fixtures and configuration for all tests
in the ethoscope_node package.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pytest

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "fixtures" / "data"

# Import notification fixtures
from .fixtures.notification_fixtures import *


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_ethoscope_device():
    """Mock ethoscope device for testing."""
    device = Mock()
    device.id = "test_device_001"
    device.name = "Test Device"
    device.ip = "192.168.1.100"
    device.port = 9000
    device.status = "running"
    device.last_seen = "2025-01-01T00:00:00Z"
    device.hardware_version = "1.0"
    device.software_version = "1.0.0"
    return device


@pytest.fixture
def mock_device_list():
    """Mock list of ethoscope devices."""
    devices = []
    for i in range(3):
        device = Mock()
        device.id = f"test_device_{i:03d}"
        device.name = f"Test Device {i}"
        device.ip = f"192.168.1.{100 + i}"
        device.port = 9000
        device.status = "running"
        device.last_seen = "2025-01-01T00:00:00Z"
        device.hardware_version = "1.0"
        device.software_version = "1.0.0"
        devices.append(device)
    return devices


@pytest.fixture
def mock_database():
    """Mock database connection for testing."""
    db = Mock()
    db.connect.return_value = True
    db.execute.return_value = True
    db.fetchall.return_value = []
    db.fetchone.return_value = None
    db.commit.return_value = True
    db.close.return_value = True
    return db


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    config = {
        "server": {"host": "localhost", "port": 80, "debug": False},
        "database": {
            "host": "localhost",
            "port": 3306,
            "user": "test_user",
            "password": "test_password",
            "database": "ethoscope_test",
        },
        "backup": {"enabled": True, "interval": 3600, "retention_days": 30},
    }
    return config


@pytest.fixture
def sample_experiment_data():
    """Sample experiment data for testing."""
    return {
        "id": "exp_001",
        "name": "Test Experiment",
        "description": "Test experiment for unit testing",
        "start_time": "2025-01-01T00:00:00Z",
        "end_time": "2025-01-01T23:59:59Z",
        "devices": ["test_device_001", "test_device_002"],
        "parameters": {
            "tracking_enabled": True,
            "video_recording": False,
            "stimulation": False,
        },
    }


@pytest.fixture
def sample_tracking_data():
    """Sample tracking data for testing."""
    return [
        {
            "timestamp": "2025-01-01T00:00:00Z",
            "device_id": "test_device_001",
            "roi_id": 1,
            "x": 100.5,
            "y": 200.3,
            "width": 50,
            "height": 30,
            "angle": 45.0,
            "area": 1500,
        },
        {
            "timestamp": "2025-01-01T00:00:01Z",
            "device_id": "test_device_001",
            "roi_id": 1,
            "x": 102.1,
            "y": 201.8,
            "width": 52,
            "height": 31,
            "angle": 46.5,
            "area": 1612,
        },
    ]


@pytest.fixture
def mock_git_repo():
    """Mock git repository for testing updates."""
    repo = Mock()
    repo.remotes.origin.pull.return_value = True
    repo.head.commit.hexsha = "abc123def456"
    repo.is_dirty.return_value = False
    repo.untracked_files = []
    return repo


@pytest.fixture
def mock_network_interface():
    """Mock network interface for testing."""
    interface = Mock()
    interface.name = "eth0"
    interface.ip = "192.168.1.50"
    interface.netmask = "255.255.255.0"
    interface.broadcast = "192.168.1.255"
    return interface


@pytest.fixture(autouse=True)
def cleanup_test_files():
    """Automatically clean up test files after each test."""
    yield
    # Clean up any test files that might have been created
    test_files = ["test_backup.db", "test_config.json", "test_experiment.json"]
    for file_path in test_files:
        if os.path.exists(file_path):
            os.remove(file_path)


@pytest.fixture
def mock_cherrypy_server():
    """Mock CherryPy server for testing."""
    server = Mock()
    server.start.return_value = True
    server.stop.return_value = True
    server.restart.return_value = True
    server.is_running = True
    return server


@pytest.fixture
def mock_zeroconf_service():
    """Mock Zeroconf service for device discovery."""
    service = Mock()
    service.name = "Test Ethoscope Service"
    service.type = "_ethoscope._tcp.local."
    service.port = 9000
    service.server = "test-device.local."
    service.addresses = [b"\xc0\xa8\x01\x64"]  # 192.168.1.100
    service.properties = {b"device_id": b"test_device_001", b"version": b"1.0.0"}
    return service
