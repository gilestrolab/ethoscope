#!/usr/bin/env python3
"""
Test script for device_scanner.py backup filename fix.

This script tests the updated device_scanner methods to ensure they properly
handle the new nested databases structure and eliminate the warning messages.
"""

import sys
import os
import tempfile
import time
from unittest.mock import Mock, patch

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))

from ethoscope_node.utils.device_scanner import Ethoscope

def create_test_device_old_format():
    """Create a test device with old database_info format."""
    return {
        'id': 'test_device_001',
        'name': 'ETHOSCOPE_001',
        'ip': '192.168.1.10',
        'status': 'running',
        'database_info': {
            'active_type': 'mariadb',
            'mariadb': {
                'exists': True,
                'current': {
                    'backup_filename': '2024-01-01_12-00-00_test_device_001.db'
                }
            }
        }
    }

def create_test_device_new_format():
    """Create a test device with new nested databases format."""
    return {
        'id': 'test_device_001',
        'name': 'ETHOSCOPE_001',
        'ip': '192.168.1.10',
        'status': 'running',
        'databases': {
            'SQLite': {},
            'MariaDB': {
                'test_mariadb.db': {
                    'backup_filename': '2024-01-01_12-00-00_test_device_001.db',
                    'filesize': 2048,
                    'version': '10.5.8',
                    'path': 'test_device_001/ETHOSCOPE_001/2024-01-01_12-00-00',
                    'date': 1704110400,
                    'db_status': 'active',
                    'table_counts': {'ROI_1': 200, 'ROI_2': 250},
                    'file_exists': True
                }
            }
        },
        'backup_status': 75.5,
        'backup_size': 2048,
        'time_since_backup': 300.0
    }

def test_mariadb_backup_filename():
    """Test MariaDB backup filename extraction."""
    print("Testing MariaDB backup filename extraction...")
    
    # Test with new format
    device = Ethoscope('192.168.1.10', 9000, '/tmp')
    device._info = create_test_device_new_format()
    
    filename = device._get_mariadb_backup_filename()
    expected = '2024-01-01_12-00-00_test_device_001.db'
    
    if filename == expected:
        print("✓ New format: MariaDB backup filename extracted correctly")
    else:
        print(f"✗ New format: Expected '{expected}', got '{filename}'")
        return False
    
    # Test with old format
    device._info = create_test_device_old_format()
    filename = device._get_mariadb_backup_filename()
    
    if filename == expected:
        print("✓ Old format fallback: MariaDB backup filename extracted correctly")
    else:
        print(f"✗ Old format fallback: Expected '{expected}', got '{filename}'")
        return False
    
    return True

def test_sqlite_backup_filename():
    """Test SQLite backup filename extraction."""
    print("Testing SQLite backup filename extraction...")
    
    # Create test device with SQLite database
    device_info = create_test_device_new_format()
    device_info['databases']['SQLite'] = {
        'test_sqlite.db': {
            'backup_filename': '2024-01-01_12-00-00_test_device_001.db',
            'filesize': 1024,
            'version': '3.32.0'
        }
    }
    device_info['databases']['MariaDB'] = {}  # Empty MariaDB
    
    device = Ethoscope('192.168.1.10', 9000, '/tmp')
    device._info = device_info
    
    filename = device._get_sqlite_backup_filename()
    expected = '2024-01-01_12-00-00_test_device_001.db'
    
    if filename == expected:
        print("✓ New format: SQLite backup filename extracted correctly")
    else:
        print(f"✗ New format: Expected '{expected}', got '{filename}'")
        return False
    
    return True

def test_appropriate_backup_filename():
    """Test appropriate backup filename selection."""
    print("Testing appropriate backup filename selection...")
    
    # Test with MariaDB active
    device = Ethoscope('192.168.1.10', 9000, '/tmp')
    device._info = create_test_device_new_format()
    
    filename = device._get_appropriate_backup_filename()
    expected = '2024-01-01_12-00-00_test_device_001.db'
    
    if filename == expected:
        print("✓ MariaDB active: Appropriate backup filename selected correctly")
    else:
        print(f"✗ MariaDB active: Expected '{expected}', got '{filename}'")
        return False
    
    # Test with SQLite active
    device_info = create_test_device_new_format()
    device_info['databases']['MariaDB'] = {}  # Empty MariaDB
    device_info['databases']['SQLite'] = {
        'test_sqlite.db': {
            'backup_filename': '2024-01-01_12-00-00_test_device_001.db'
        }
    }
    
    device._info = device_info
    filename = device._get_appropriate_backup_filename()
    
    if filename == expected:
        print("✓ SQLite active: Appropriate backup filename selected correctly")
    else:
        print(f"✗ SQLite active: Expected '{expected}', got '{filename}'")
        return False
    
    return True

def test_backup_status_update():
    """Test backup status update with new format."""
    print("Testing backup status update...")
    
    device = Ethoscope('192.168.1.10', 9000, '/tmp')
    device._info = create_test_device_new_format()
    
    # Mock the time interval check
    device._last_db_info = 0
    
    # Test direct backup status usage
    device._update_backup_status_from_database_info()
    
    # Check that backup status was preserved
    if device._info.get('backup_status') == 75.5:
        print("✓ Direct backup status: Device-provided backup status used correctly")
    else:
        print(f"✗ Direct backup status: Expected 75.5, got {device._info.get('backup_status')}")
        return False
    
    # Check that additional fields were stored
    if device._info.get('backup_size') == 2048:
        print("✓ Backup size: Additional backup info stored correctly")
    else:
        print(f"✗ Backup size: Expected 2048, got {device._info.get('backup_size')}")
        return False
    
    return True

def test_no_backup_filename_warning():
    """Test that the warning is eliminated."""
    print("Testing elimination of 'No backup filename available' warning...")
    
    device = Ethoscope('192.168.1.10', 9000, '/tmp')
    device._info = create_test_device_new_format()
    
    # Mock the logger to capture warnings
    with patch.object(device, '_logger') as mock_logger:
        try:
            # This should find a backup filename and not produce a warning
            device._make_backup_path(service_type="auto")
            
            # Check that no warning was called
            warning_calls = [call for call in mock_logger.warning.call_args_list 
                           if 'No backup filename available' in str(call)]
            
            if len(warning_calls) == 0:
                print("✓ Warning eliminated: No 'backup filename available' warning produced")
                return True
            else:
                print(f"✗ Warning still present: Found {len(warning_calls)} warning calls")
                return False
                
        except Exception as e:
            print(f"✗ Test failed with exception: {e}")
            return False

def main():
    """Run all tests."""
    print("=== Testing Device Scanner Backup Filename Fix ===")
    
    tests = [
        test_mariadb_backup_filename,
        test_sqlite_backup_filename,
        test_appropriate_backup_filename,
        test_backup_status_update,
        test_no_backup_filename_warning
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
        print("🎉 All tests passed! Device scanner should now work with new format.")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())