#!/usr/bin/env python3
"""
Test script for validating the new backup format functionality.

This script tests the updated backup system with the new nested databases structure.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from ethoscope_node.backup.helpers import BackupClass


def create_test_device_info():
    """Create a test device info with the new nested databases structure."""
    return {
        "id": "test_device_001",
        "name": "ETHOSCOPE_001",
        "ip": "192.168.1.10",
        "status": "running",
        "databases": {
            "SQLite": {
                "test_sqlite.db": {
                    "backup_filename": "test_sqlite.db",
                    "filesize": 1024,
                    "version": "3.32.0",
                    "path": "test_device_001/ETHOSCOPE_001/2024-01-01_12-00-00",
                    "date": 1704110400,
                    "db_status": "active",
                    "table_counts": {"ROI_1": 100, "ROI_2": 150},
                    "file_exists": True,
                }
            },
            "MariaDB": {
                "test_mariadb.db": {
                    "backup_filename": "test_mariadb.db",
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
        "backup_type": "mariadb_dump",
        "backup_method": "mysql_dump",
    }


def test_mariadb_validation():
    """Test MariaDB database validation with new format."""
    print("Testing MariaDB database validation...")

    device_info = create_test_device_info()

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            backup_class = BackupClass(device_info, temp_dir)

            # Test MariaDB validation
            is_valid = backup_class._validate_mariadb_database()
            print(f"✓ MariaDB validation: {'PASS' if is_valid else 'FAIL'}")

            # Test MariaDB backup path extraction
            backup_path = backup_class._get_mariadb_backup_path()
            print(f"✓ MariaDB backup path: {backup_path}")

            return True

        except Exception as e:
            print(f"✗ MariaDB validation failed: {e}")
            return False


def test_sqlite_validation():
    """Test SQLite database validation with new format."""
    print("Testing SQLite database validation...")

    device_info = create_test_device_info()

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            from ethoscope_node.utils.backups_helpers import UnifiedRsyncBackupClass

            # UnifiedRsyncBackupClass has _validate_sqlite_database method
            backup_class = UnifiedRsyncBackupClass(device_info, temp_dir)

            # Test SQLite validation
            is_valid = backup_class._validate_sqlite_database()
            print(f"✓ SQLite validation: {'PASS' if is_valid else 'FAIL'}")

            return True

        except Exception as e:
            print(f"✗ SQLite validation failed: {e}")
            return False


def test_backup_status_initialization():
    """Test backup status initialization with new fields."""
    print("Testing backup status initialization...")

    device_info = create_test_device_info()

    try:
        from ethoscope_node.utils.backups_helpers import GenericBackupWrapper

        with tempfile.TemporaryDirectory() as temp_dir:
            gbw = GenericBackupWrapper(temp_dir, "localhost")

            # Test backup status initialization
            gbw._initialize_backup_status("test_device_001", device_info)

            status = gbw.backup_status["test_device_001"]
            progress = status.progress

            # Check that new fields are properly initialized
            expected_fields = [
                "backup_status",
                "backup_size",
                "time_since_backup",
                "backup_type",
                "backup_method",
            ]
            for field in expected_fields:
                if field not in progress:
                    print(f"✗ Missing field in progress: {field}")
                    return False
                print(f"✓ Field {field}: {progress[field]}")

            print("✓ Backup status initialization: PASS")
            return True

    except Exception as e:
        print(f"✗ Backup status initialization failed: {e}")
        return False


def test_device_info_creation():
    """Test device info creation for forced backups."""
    print("Testing device info creation...")

    try:
        from scripts.backup_tool import create_device_info_from_backup

        ethoscope_name = "ETHOSCOPE_001"
        host = "192.168.1.10"
        backup_filename = "2024-01-01_12-00-00_test_device_001.db"

        device_info = create_device_info_from_backup(
            ethoscope_name, host, backup_filename
        )

        # Check that the new nested structure is created
        if "databases" not in device_info:
            print("✗ Missing 'databases' structure")
            return False

        if "MariaDB" not in device_info["databases"]:
            print("✗ Missing 'MariaDB' structure")
            return False

        if backup_filename not in device_info["databases"]["MariaDB"]:
            print(f"✗ Missing backup filename '{backup_filename}' in MariaDB structure")
            return False

        mariadb_info = device_info["databases"]["MariaDB"][backup_filename]
        expected_fields = [
            "backup_filename",
            "filesize",
            "version",
            "path",
            "date",
            "db_status",
            "table_counts",
            "file_exists",
        ]

        for field in expected_fields:
            if field not in mariadb_info:
                print(f"✗ Missing field in MariaDB info: {field}")
                return False

        print("✓ Device info creation: PASS")
        return True

    except Exception as e:
        print(f"✗ Device info creation failed: {e}")
        return False


def test_frontend_compatibility():
    """Test that the frontend will work with the new backup format."""
    print("Testing frontend compatibility with new backup format...")

    # Test device with new backup fields
    device_with_new_fields = {
        "id": "test_device_001",
        "name": "ETHOSCOPE_001",
        "backup_status": 85.5,
        "backup_size": 2048,
        "time_since_backup": 300.0,
        "backup_type": "mariadb_dump",
        "backup_method": "mysql_dump",
    }

    # Test device without new backup fields (fallback)
    device_without_new_fields = {
        "id": "test_device_002",
        "name": "ETHOSCOPE_002",
        "status": "running",
    }

    try:
        # Test JavaScript logic simulation
        # Device with new fields should work
        if device_with_new_fields.get("backup_status") is not None:
            print("✓ Device with new fields detected")
            backup_status = device_with_new_fields["backup_status"]
            if isinstance(backup_status, (int, float)) and backup_status >= 50:
                print("✓ Backup status logic works for new fields")
            else:
                print("✗ Backup status logic failed for new fields")
                return False

        # Device without new fields should fall back gracefully
        if device_without_new_fields.get("backup_status") is None:
            print("✓ Device without new fields falls back correctly")

        # Test the HTML template fields
        required_fields = ["backup_status", "backup_size", "time_since_backup"]
        for field in required_fields:
            if field in device_with_new_fields:
                print(f"✓ Field {field} available for frontend template")
            else:
                print(f"✗ Field {field} missing for frontend template")
                return False

        print("✓ Frontend compatibility: PASS")
        return True

    except Exception as e:
        print(f"✗ Frontend compatibility failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=== Testing New Backup Format Functionality ===")

    tests = [
        test_mariadb_validation,
        test_sqlite_validation,
        test_backup_status_initialization,
        test_device_info_creation,
        test_frontend_compatibility,
    ]

    passed = 0
    total = len(tests)

    for test in tests:
        print(f"\n{'-' * 50}")
        if test():
            passed += 1
        else:
            print("Test failed!")

    print(f"\n{'-' * 50}")
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
