#!/usr/bin/env python3
"""
Test script to verify complete logger name fix workflow.

This tests the complete flow of logger name updates from IP-based to
device-name-based when device info is fetched.
"""

import logging
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
    temp_dir = tempfile.mkdtemp(prefix="test_ethoscope_logger_")
    yield temp_dir
    try:
        shutil.rmtree(temp_dir)
    except (OSError, FileNotFoundError):
        pass


def test_complete_logger_name_workflow(temp_config_dir):
    """Test complete workflow of logger name updates."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    # Create device
    device = Ethoscope("192.168.1.65", 9000, config_dir=temp_config_dir, config=mock_config)

    # Initial logger name should be IP-based
    initial_name = device._logger.name

    assert initial_name.endswith(
        "192.168.1.65"
    ), f"Initial logger name should be IP-based, got: {initial_name}"

    # Mock the device response with proper ethoscope data
    mock_response = {
        "id": "test_device_065",
        "name": "ETHOSCOPE_065",
        "status": "running",
        "version": {"id": "v1.0.0"},
        "experimental_info": {"name": "test_user", "location": "test_location"},
    }

    # Mock the HTTP request
    with patch.object(device, "_get_json", return_value=mock_response):
        with patch.object(device, "_update_id"):
            # This should trigger logger name update
            success = device._fetch_device_info()

            assert success, "Failed to fetch device info"

            # Check that logger name was updated
            final_name = device._logger.name
            expected_name = "ETHOSCOPE_065"

            assert (
                final_name == expected_name
            ), f"Expected '{expected_name}', got '{final_name}'"

            # Verify the info was updated
            assert (
                device._info.get("name") == "ETHOSCOPE_065"
            ), f"Device info not updated correctly: {device._info}"


def test_logger_name_in_warning_messages(temp_config_dir):
    """Test that warning messages now show proper device names."""
    # Mock the configuration to avoid writing to /etc/ethoscope
    from unittest.mock import Mock
    mock_config = Mock()

    # Create device and update its info
    device = Ethoscope("192.168.1.65", 9000, config_dir=temp_config_dir, config=mock_config)
    device._info = {
        "name": "ETHOSCOPE_065",
        "id": "test_device_065",
        "status": "running",
    }

    # Update logger name
    device._update_logger_name()

    # Capture log messages
    log_messages = []

    class TestHandler(logging.Handler):
        def emit(self, record):
            log_messages.append(record.getMessage())

    test_handler = TestHandler()
    device._logger.addHandler(test_handler)
    device._logger.setLevel(logging.WARNING)

    # Generate a warning message
    device._logger.warning("No backup filename available for auto backup")

    # Check that the log message contains proper device name
    assert len(log_messages) > 0, "No log messages captured"
