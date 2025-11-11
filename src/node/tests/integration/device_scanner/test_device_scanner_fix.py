#!/usr/bin/env python3
"""
Test script for device_scanner.py backup filename fix.

This script tests the updated device_scanner methods to ensure they properly
handle the new nested databases structure and eliminate the warning messages.
"""

import os
import shutil
import sys
import tempfile
from unittest.mock import patch

import pytest

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from ethoscope_node.scanner.ethoscope_scanner import Ethoscope


@pytest.fixture
def temp_config_dir():
    """Create temporary config directory for tests."""
    temp_dir = tempfile.mkdtemp(prefix="test_ethoscope_")
    yield temp_dir
    try:
        shutil.rmtree(temp_dir)
    except (OSError, FileNotFoundError):
        pass


def create_test_device_old_format():
    """Create a test device with old database_info format."""
    return {
        "id": "test_device_001",
        "name": "ETHOSCOPE_001",
        "ip": "192.168.1.10",
        "status": "running",
        "database_info": {
            "active_type": "mariadb",
            "mariadb": {
                "exists": True,
                "current": {
                    "backup_filename": "2024-01-01_12-00-00_test_device_001.db"
                },
            },
        },
    }


def create_test_device_new_format():
    """Create a test device with new nested databases format."""
    return {
        "id": "test_device_001",
        "name": "ETHOSCOPE_001",
        "ip": "192.168.1.10",
        "status": "running",
        "databases": {
            "SQLite": {},
            "MariaDB": {
                "test_mariadb.db": {
                    "backup_filename": "2024-01-01_12-00-00_test_device_001.db",
                    "filesize": 2048,
                    "version": "10.5.8",
                    "path": "test_device_001/ETHOSCOPE_001/2024-01-01_12-00-00",
                    "date": 1704110400,
                    "db_status": "active",
                    "table_counts": {"ROI_1": 200, "ROI_2": 250},
                    "file_exists": True,
                }
            },
        },
        "backup_status": 75.5,
        "backup_size": 2048,
        "time_since_backup": 300.0,
    }


def test_mariadb_backup_filename(temp_config_dir):
    """Test MariaDB backup filename extraction."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    # Test with new format
    device = Ethoscope("192.168.1.10", 9000, config_dir=temp_config_dir, config=mock_config)
    device._info = create_test_device_new_format()

    filename = device._get_backup_filename_for_db_type("MariaDB")
    expected = "2024-01-01_12-00-00_test_device_001.db"

    assert filename == expected, f"New format: Expected '{expected}', got '{filename}'"

    # Test with old format fallback (requires mocking databases_info HTTP call)
    device._info = create_test_device_old_format()

    # Mock the databases_info method to return the old format structure
    mock_databases_info = {
        "mariadb": {
            "exists": True,
            "current": {
                "backup_filename": "2024-01-01_12-00-00_test_device_001.db"
            }
        }
    }

    with patch.object(device, 'databases_info', return_value=mock_databases_info):
        filename = device._get_backup_filename_for_db_type("MariaDB")
        assert (
            filename == expected
        ), f"Old format fallback: Expected '{expected}', got '{filename}'"


def test_sqlite_backup_filename(temp_config_dir):
    """Test SQLite backup filename extraction."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    # Create test device with SQLite database
    device_info = create_test_device_new_format()
    device_info["databases"]["SQLite"] = {
        "test_sqlite.db": {
            "backup_filename": "2024-01-01_12-00-00_test_device_001.db",
            "filesize": 1024,
            "version": "3.32.0",
        }
    }
    device_info["databases"]["MariaDB"] = {}  # Empty MariaDB

    device = Ethoscope("192.168.1.10", 9000, config_dir=temp_config_dir, config=mock_config)
    device._info = device_info

    filename = device._get_backup_filename_for_db_type("SQLite")
    expected = "2024-01-01_12-00-00_test_device_001.db"

    assert filename == expected, f"Expected '{expected}', got '{filename}'"


def test_appropriate_backup_filename(temp_config_dir):
    """Test appropriate backup filename selection."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    # Test with MariaDB active
    device = Ethoscope("192.168.1.10", 9000, config_dir=temp_config_dir, config=mock_config)
    device._info = create_test_device_new_format()

    filename = device._get_appropriate_backup_filename()
    expected = "2024-01-01_12-00-00_test_device_001.db"

    assert (
        filename == expected
    ), f"MariaDB active: Expected '{expected}', got '{filename}'"

    # Test with SQLite active
    device_info = create_test_device_new_format()
    device_info["databases"]["MariaDB"] = {}  # Empty MariaDB
    device_info["databases"]["SQLite"] = {
        "test_sqlite.db": {"backup_filename": "2024-01-01_12-00-00_test_device_001.db"}
    }

    device._info = device_info
    filename = device._get_appropriate_backup_filename()

    assert (
        filename == expected
    ), f"SQLite active: Expected '{expected}', got '{filename}'"


def test_no_backup_filename_warning(temp_config_dir):
    """Test that the warning is eliminated."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    device = Ethoscope("192.168.1.10", 9000, config_dir=temp_config_dir, config=mock_config)
    device._info = create_test_device_new_format()

    # Mock the logger to capture warnings
    with patch.object(device, "_logger") as mock_logger:
        # This should find a backup filename and not produce a warning
        device._make_backup_path(service_type="auto")

        # Check that no warning was called
        warning_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "No backup filename available" in str(call)
        ]

        assert (
            len(warning_calls) == 0
        ), f"Found {len(warning_calls)} unexpected warning calls"
