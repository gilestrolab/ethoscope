#!/usr/bin/env python3
"""
Test script for logger name fix in device_scanner.py.

This script tests that the logger name is properly updated from IP address
to the proper device name format (e.g., ETHOSCOPE_065).
"""

import logging
import os
import sys
from unittest.mock import patch

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from ethoscope_node.scanner.ethoscope_scanner import Ethoscope


def test_logger_name_update():
    """Test that logger name is updated properly."""
    print("Testing logger name update...")

    # Create a mock device with proper name
    device = Ethoscope("192.168.1.65", 9000, "/tmp")

    # Check initial logger name (should be based on IP)
    initial_logger_name = device._logger.name
    print(f"Initial logger name: {initial_logger_name}")

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
    print(f"Updated logger name: {new_logger_name}")

    expected_name = "Ethoscope_ETHOSCOPE_065"

    if new_logger_name == expected_name:
        print("✓ Logger name updated correctly")
        return True
    else:
        print(f"✗ Expected '{expected_name}', got '{new_logger_name}'")
        return False


def test_logger_name_no_update_for_invalid_names():
    """Test that logger name is not updated for invalid names."""
    print("Testing logger name does not update for invalid names...")

    device = Ethoscope("192.168.1.65", 9000, "/tmp")
    initial_logger_name = device._logger.name

    # Try with empty name
    device._info = {"name": ""}
    device._update_logger_name()

    if device._logger.name == initial_logger_name:
        print("✓ Logger name not updated for empty name")
    else:
        print("✗ Logger name should not have changed for empty name")
        return False

    # Try with unknown_name
    device._info = {"name": "unknown_name"}
    device._update_logger_name()

    if device._logger.name == initial_logger_name:
        print("✓ Logger name not updated for 'unknown_name'")
        return True
    else:
        print("✗ Logger name should not have changed for 'unknown_name'")
        return False


def test_logger_name_format_variations():
    """Test different device name formats."""
    print("Testing different device name formats...")

    test_cases = [
        ("ETHOSCOPE_001", "Ethoscope_ETHOSCOPE_001"),
        ("ETHOSCOPE_065", "Ethoscope_ETHOSCOPE_065"),
        ("ETHOSCOPE_123", "Ethoscope_ETHOSCOPE_123"),
    ]

    for device_name, expected_logger_name in test_cases:
        device = Ethoscope("192.168.1.65", 9000, "/tmp")
        device._info = {"name": device_name}
        device._update_logger_name()

        if device._logger.name == expected_logger_name:
            print(f"✓ {device_name} -> {expected_logger_name}")
        else:
            print(
                f"✗ {device_name} -> expected '{expected_logger_name}', got '{device._logger.name}'"
            )
            return False

    return True


def main():
    """Run all tests."""
    print("=== Testing Logger Name Fix ===")

    tests = [
        test_logger_name_update,
        test_logger_name_no_update_for_invalid_names,
        test_logger_name_format_variations,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        print(f"\n{'-' * 50}")
        try:
            if test():
                passed += 1
            else:
                print("Test failed!")
        except Exception as e:
            print(f"Test failed with exception: {e}")

    print(f"\n{'-' * 50}")
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Logger names should now show proper device names.")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
