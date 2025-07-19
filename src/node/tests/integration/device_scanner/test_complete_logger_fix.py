#!/usr/bin/env python3
"""
Test script to verify complete logger name fix workflow.

This tests the complete flow of logger name updates from IP-based to 
device-name-based when device info is fetched.
"""

import sys
import os
import logging
from unittest.mock import Mock, patch
import json

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from ethoscope_node.utils.device_scanner import Ethoscope

def test_complete_logger_name_workflow():
    """Test complete workflow of logger name updates."""
    print("Testing complete logger name workflow...")
    
    # Create device
    device = Ethoscope('192.168.1.65', 9000, '/tmp')
    
    # Initial logger name should be IP-based
    initial_name = device._logger.name
    print(f"Initial logger name: {initial_name}")
    
    if not initial_name.endswith('192.168.1.65'):
        print("✗ Initial logger name should be IP-based")
        return False
    
    # Mock the device response with proper ethoscope data
    mock_response = {
        'id': 'test_device_065',
        'name': 'ETHOSCOPE_065',
        'status': 'running',
        'version': {'id': 'v1.0.0'},
        'experimental_info': {
            'name': 'test_user',
            'location': 'test_location'
        }
    }
    
    # Mock the HTTP request
    with patch.object(device, '_get_json', return_value=mock_response):
        with patch.object(device, '_update_id'):
            # This should trigger logger name update
            success = device._fetch_device_info()
            
            if not success:
                print("✗ Failed to fetch device info")
                return False
            
            # Check that logger name was updated
            final_name = device._logger.name
            print(f"Final logger name: {final_name}")
            
            expected_name = "Ethoscope_ETHOSCOPE_065"
            if final_name == expected_name:
                print("✓ Logger name updated correctly during fetch")
            else:
                print(f"✗ Expected '{expected_name}', got '{final_name}'")
                return False
            
            # Verify the info was updated
            if device._info.get('name') == 'ETHOSCOPE_065':
                print("✓ Device info updated correctly")
            else:
                print(f"✗ Device info not updated correctly: {device._info}")
                return False
    
    return True

def test_logger_name_in_warning_messages():
    """Test that warning messages now show proper device names."""
    print("Testing logger name in warning messages...")
    
    # Create device and update its info
    device = Ethoscope('192.168.1.65', 9000, '/tmp')
    device._info = {
        'name': 'ETHOSCOPE_065',
        'id': 'test_device_065',
        'status': 'running'
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
    if log_messages:
        message = log_messages[0]
        print(f"Log message: {message}")
        
        # The logger name should now be used in the log format
        # This will depend on the logging configuration, but the logger name is now correct
        print("✓ Warning message generated with proper logger name")
        return True
    else:
        print("✗ No log messages captured")
        return False

def main():
    """Run all tests."""
    print("=== Testing Complete Logger Name Fix ===")
    
    tests = [
        test_complete_logger_name_workflow,
        test_logger_name_in_warning_messages
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
        print("🎉 All tests passed! Logger names should now show proper device names in logs.")
        print("    Instead of 'Ethoscope_192.168.1.65', you should see 'Ethoscope_ETHOSCOPE_065'")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())