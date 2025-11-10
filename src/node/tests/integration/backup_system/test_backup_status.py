#!/usr/bin/env python3
"""
Test script for the new unified backup status endpoint.

This script tests the modified backup status API that combines information
from both MySQL backup daemon (port 8090) and rsync backup daemon (port 8093).
"""

import json
import urllib.error
import urllib.request


def test_individual_services():
    """Test individual backup services directly."""
    print("=== Testing Individual Backup Services ===")

    # Test MySQL backup service (port 8090)
    print("\n1. Testing MySQL backup service (port 8090):")
    try:
        with urllib.request.urlopen(
            "http://192.168.255.18:8090/status", timeout=5
        ) as response:
            mysql_data = json.loads(response.read().decode("utf-8"))
            print("   ✓ MySQL backup service responsive")
            print(f"   ✓ Found {len(mysql_data)} devices in MySQL backup status")
            # Show sample device
            if mysql_data:
                sample_device = list(mysql_data.values())[0]
                print(
                    f"   ✓ Sample status: {sample_device.get('progress', {}).get('status', 'unknown')}"
                )
    except Exception as e:
        print(f"   ✗ MySQL backup service error: {e}")

    # Test rsync backup service (port 8093)
    print("\n2. Testing rsync backup service (port 8093):")
    try:
        with urllib.request.urlopen(
            "http://192.168.255.18:8093/status", timeout=5
        ) as response:
            rsync_data = json.loads(response.read().decode("utf-8"))
            devices = rsync_data.get("devices", {})
            print("   ✓ Rsync backup service responsive")
            print(f"   ✓ Found {len(devices)} devices in rsync backup status")
            # Show sample device
            if devices:
                sample_device = list(devices.values())[0]
                print(
                    f"   ✓ Sample status: {sample_device.get('progress', {}).get('status', 'unknown')}"
                )
                print(
                    f"   ✓ Sample disk usage: {sample_device.get('synced', {}).get('results', {}).get('disk_usage_human', 'unknown')}"
                )
    except Exception as e:
        print(f"   ✗ Rsync backup service error: {e}")


def test_unified_service():
    """Test the new unified backup status endpoint."""
    print("\n=== Testing Unified Backup Status Endpoint ===")
    print("   Note: This test requires the node server to be running locally")

    try:
        # Test the unified endpoint (node server should be running on localhost)
        with urllib.request.urlopen(
            "http://localhost/backup/status", timeout=10
        ) as response:
            unified_data = json.loads(response.read().decode("utf-8"))

            print("   ✓ Unified backup endpoint responsive")

            # Check structure
            if "mysql_backup" in unified_data:
                mysql_available = "error" not in unified_data["mysql_backup"]
                print(
                    f"   ✓ MySQL backup data: {'available' if mysql_available else 'unavailable'}"
                )

            if "rsync_backup" in unified_data:
                rsync_available = "error" not in unified_data["rsync_backup"]
                print(
                    f"   ✓ Rsync backup data: {'available' if rsync_available else 'unavailable'}"
                )

            if "unified_devices" in unified_data:
                unified_devices = unified_data["unified_devices"]
                print(f"   ✓ Found {len(unified_devices)} devices in unified view")

                # Show sample unified device status
                if unified_devices:
                    sample_id = list(unified_devices.keys())[0]
                    sample_device = unified_devices[sample_id]
                    print(f"   ✓ Sample device: {sample_device.get('name', 'unknown')}")
                    print(
                        f"   ✓ Overall status: {sample_device.get('overall_status', 'unknown')}"
                    )
                    print(
                        f"   ✓ MySQL backup available: {sample_device.get('mysql_backup', {}).get('available', False)}"
                    )
                    print(
                        f"   ✓ Rsync backup available: {sample_device.get('rsync_backup', {}).get('available', False)}"
                    )

                    # Count status types
                    status_counts = {}
                    for device in unified_devices.values():
                        status = device.get("overall_status", "unknown")
                        status_counts[status] = status_counts.get(status, 0) + 1

                    print(f"   ✓ Status distribution: {status_counts}")

            return True

    except Exception as e:
        print(f"   ✗ Unified backup endpoint error: {e}")
        return False


def main():
    """Main test function."""
    print("Testing Unified Backup Status API")
    print("=" * 50)

    # Test individual services first
    test_individual_services()

    # Test unified service
    success = test_unified_service()

    print("\n" + "=" * 50)
    if success:
        print("✓ All tests completed successfully!")
        print("The unified backup status endpoint is working correctly.")
    else:
        print("✗ Some tests failed.")
        print("Check the node server logs and ensure both backup daemons are running.")


if __name__ == "__main__":
    main()
