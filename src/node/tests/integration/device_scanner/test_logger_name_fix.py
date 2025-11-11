#!/usr/bin/env python3
"""
Test script for logger name fix in device_scanner.py.

This script tests that the logger name is properly updated from IP address
to the proper device name format (e.g., ETHOSCOPE_065).
"""

import os
import shutil
import sys
import tempfile

import pytest

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from ethoscope_node.scanner.ethoscope_scanner import Ethoscope


@pytest.fixture
def temp_config_dir():
    """Create temporary config directory for tests."""
    temp_dir = tempfile.mkdtemp(prefix="test_ethoscope_logger_")
    yield temp_dir
    try:
        shutil.rmtree(temp_dir)
    except (OSError, FileNotFoundError):
        pass


def test_logger_name_update(temp_config_dir):
    """Test that logger name is updated properly."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    # Create a mock device with proper name
    device = Ethoscope("192.168.1.65", 9000, config_dir=temp_config_dir, config=mock_config)

    # Check initial logger name (should be based on IP)
    initial_logger_name = device._logger.name

    # Update device info with proper name
    device._info = {
        "name": "ETHOSCOPE_065",
        "id": "test_device_065",
        "status": "running",
    }

    # Call the update method
    device._update_logger_name()

    # Check new logger name
    new_logger_name = device._logger.name
    expected_name = "ETHOSCOPE_065"

    assert new_logger_name == expected_name, f"Expected '{expected_name}', got '{new_logger_name}'"


def test_logger_name_no_update_for_invalid_names(temp_config_dir):
    """Test that logger name is not updated for invalid names."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    device = Ethoscope("192.168.1.65", 9000, config_dir=temp_config_dir, config=mock_config)
    initial_logger_name = device._logger.name

    # Try with empty name
    device._info = {"name": ""}
    device._update_logger_name()

    assert (
        device._logger.name == initial_logger_name
    ), "Logger name should not change for empty name"

    # Try with unknown_name
    device._info = {"name": "unknown_name"}
    device._update_logger_name()

    assert (
        device._logger.name == initial_logger_name
    ), "Logger name should not change for 'unknown_name'"


def test_logger_name_format_variations(temp_config_dir):
    """Test different device name formats."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock

    test_cases = [
        ("ETHOSCOPE_001", "ETHOSCOPE_001"),
        ("ETHOSCOPE_065", "ETHOSCOPE_065"),
        ("ETHOSCOPE_123", "ETHOSCOPE_123"),
    ]

    for device_name, expected_logger_name in test_cases:
        mock_config = Mock()
        device = Ethoscope("192.168.1.65", 9000, config_dir=temp_config_dir, config=mock_config)
        device._info = {"name": device_name}
        device._update_logger_name()

        assert device._logger.name == expected_logger_name, (
            f"{device_name} -> expected '{expected_logger_name}', "
            f"got '{device._logger.name}'"
        )
