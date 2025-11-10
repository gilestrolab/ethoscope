#!/usr/bin/env python3
"""
Integration tests for the backup API endpoints.

Tests the complete backup API integration including:
- Backup status endpoint with caching
- Device-level backup information
- Home page backup status display
- API response structure and performance
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

# Add the source path for imports
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ethoscope_node")
)

from ethoscope_node.api.backup_api import BackupAPI


class TestBackupAPIIntegration(unittest.TestCase):
    """Integration tests for backup API endpoints."""

    def setUp(self):
        """Set up test environment with mock API instance."""
        self.test_dir = tempfile.mkdtemp()

        # Create mock app and device scanner
        self.mock_app = MagicMock()
        self.mock_device_scanner = MagicMock()

        # Create BackupAPI instance
        self.backup_api = BackupAPI(
            app=self.mock_app,
            device_scanner=self.mock_device_scanner,
            config={},
            logger=MagicMock(),
        )

        # Sample device data
        self.sample_devices = {
            "device_001": {
                "id": "device_001",
                "name": "ETHOSCOPE_001",
                "status": "running",
                "databases": {
                    "MariaDB": {"ethoscope_db": {"table1": 1000}},
                    "SQLite": {
                        "file1.db": {"path": "/path/to/file1.db", "filesize": 1024000}
                    },
                },
            },
            "device_002": {
                "id": "device_002",
                "name": "ETHOSCOPE_002",
                "status": "offline",
                "databases": {},
            },
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    @patch("urllib.request.urlopen")
    def test_backup_status_endpoint_success(self, mock_urlopen):
        """Test successful backup status endpoint response."""
        # Mock rsync and mysql service responses
        mysql_response = {
            "device_001": {"progress": {"status": "completed"}, "name": "ETHOSCOPE_001"}
        }

        rsync_response = {
            "devices": {
                "device_001": {
                    "synced": {
                        "results": {"disk_usage_human": "10.5 MB"},
                        "videos": {"local_files": 5},
                    }
                }
            }
        }

        # Mock URL responses
        def mock_urlopen_side_effect(url, timeout=None):
            mock_response = MagicMock()
            if "8090" in str(url):  # MySQL service
                mock_response.read.return_value = json.dumps(mysql_response).encode()
            elif "8093" in str(url):  # Rsync service
                mock_response.read.return_value = json.dumps(rsync_response).encode()
            return mock_response.__enter__.return_value

        mock_urlopen.return_value.__enter__ = lambda self: mock_urlopen_side_effect(
            None
        )
        mock_urlopen.side_effect = mock_urlopen_side_effect

        # Mock device scanner
        self.mock_device_scanner.get_all_devices_info.return_value = self.sample_devices

        # Mock device backup info function
        with patch(
            "ethoscope_node.backup.helpers.get_device_backup_info"
        ) as mock_get_backup:
            mock_backup_info = {
                "backup_status": {
                    "mysql": {
                        "available": True,
                        "database_count": 1,
                        "total_size_bytes": 1024000,
                        "last_backup": time.time() - 3600,  # 1 hour ago
                    },
                    "sqlite": {
                        "available": True,
                        "database_count": 1,
                        "total_size_bytes": 1024000,
                        "last_backup": time.time() - 1800,  # 30 minutes ago
                    },
                    "video": {
                        "available": True,
                        "file_count": 5,
                        "total_size_bytes": 10485760,
                        "size_human": "10.0 MB",
                        "last_backup": time.time() - 7200,  # 2 hours ago
                    },
                }
            }
            mock_get_backup.return_value = mock_backup_info

            # Call the backup status endpoint
            result = self.backup_api._get_backup_status()
            response_data = json.loads(result)

            # Verify response structure
            self.assertIn("services", response_data)
            self.assertIn("summary", response_data)
            self.assertIn("devices", response_data)
            self.assertIn("processing_devices", response_data)
            self.assertIn("timestamp", response_data)

            # Verify service availability
            services = response_data["services"]
            self.assertTrue(services["mysql_backup"]["available"])
            self.assertTrue(services["rsync_backup"]["available"])

            # Verify summary
            summary = response_data["summary"]
            self.assertTrue(summary["mysql_backup_available"])
            self.assertTrue(summary["rsync_backup_available"])
            self.assertTrue(summary["services"]["mysql_service_available"])
            self.assertTrue(summary["services"]["rsync_service_available"])

            # Verify device data structure
            devices = response_data["devices"]
            self.assertIn("device_001", devices)

            device_data = devices["device_001"]
            self.assertIn("backup_types", device_data)
            self.assertIn("overall_status", device_data)

            # Verify backup types have required fields
            backup_types = device_data["backup_types"]
            for backup_type in ["mysql", "sqlite", "video"]:
                self.assertIn(backup_type, backup_types)
                backup_info = backup_types[backup_type]

                # Check required fields for JavaScript consumption
                required_fields = [
                    "available",
                    "status",
                    "processing",
                    "size",
                    "last_backup",
                ]
                for field in required_fields:
                    self.assertIn(
                        field,
                        backup_info,
                        f"Missing required field '{field}' in {backup_type} backup info",
                    )

    def test_backup_status_cache_functionality(self):
        """Test backup status caching behavior."""
        # Mock device scanner
        self.mock_device_scanner.get_all_devices_info.return_value = {}

        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock service responses
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # First call - should hit the services
            start_time = time.time()
            result1 = self.backup_api._get_backup_status()
            first_call_time = time.time() - start_time

            # Second call immediately - should use cache
            start_time = time.time()
            result2 = self.backup_api._get_backup_status()
            second_call_time = time.time() - start_time

            # Results should be identical
            self.assertEqual(result1, result2)

            # Second call should be faster (cached)
            self.assertLess(
                second_call_time,
                first_call_time * 0.5,
                "Cached call should be significantly faster",
            )

            # Verify cache was used (only one call to urlopen per service)
            self.assertEqual(mock_urlopen.call_count, 2)  # One for each service

    @patch("urllib.request.urlopen")
    def test_backup_status_service_unavailable(self, mock_urlopen):
        """Test backup status when services are unavailable."""
        # Mock service unavailable
        mock_urlopen.side_effect = Exception("Connection refused")

        # Mock device scanner
        self.mock_device_scanner.get_all_devices_info.return_value = self.sample_devices

        # Call backup status endpoint
        result = self.backup_api._get_backup_status()
        response_data = json.loads(result)

        # Verify graceful handling
        self.assertIn("services", response_data)
        self.assertIn("summary", response_data)

        # Services should be marked as unavailable
        services = response_data["services"]
        self.assertFalse(services["mysql_backup"]["available"])
        self.assertFalse(services["rsync_backup"]["available"])

        summary = response_data["summary"]
        self.assertFalse(summary["mysql_backup_available"])
        self.assertFalse(summary["rsync_backup_available"])

    def test_backup_status_offline_device_handling(self):
        """Test backup status for offline devices."""
        offline_devices = {
            "offline_device": {
                "id": "offline_device",
                "name": "ETHOSCOPE_OFFLINE",
                "status": "offline",
                "databases": {},
            }
        }

        # Mock device scanner
        self.mock_device_scanner.get_all_devices_info.return_value = offline_devices

        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock service responses
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = self.backup_api._get_backup_status()
            response_data = json.loads(result)

            # Verify offline device handling
            devices = response_data["devices"]
            self.assertIn("offline_device", devices)

            device_data = devices["offline_device"]
            self.assertIn("backup_types", device_data)
            self.assertEqual(device_data["overall_status"], "no_backups")

            # All backup types should be marked as unavailable
            backup_types = device_data["backup_types"]
            for backup_type in ["mysql", "sqlite", "video"]:
                backup_info = backup_types[backup_type]
                self.assertFalse(backup_info["available"])
                self.assertEqual(backup_info["status"], "offline")
                self.assertFalse(backup_info["processing"])
                self.assertEqual(backup_info["size"], 0)
                self.assertEqual(backup_info["last_backup"], 0)

    def test_backup_status_performance_large_devices(self):
        """Test backup status performance with many devices."""
        # Create large number of mock devices
        large_device_set = {}
        for i in range(50):  # Simulate 50 devices
            device_id = f"device_{i:03d}"
            large_device_set[device_id] = {
                "id": device_id,
                "name": f"ETHOSCOPE_{i:03d}",
                "status": "running" if i % 2 == 0 else "offline",
                "databases": (
                    {
                        "SQLite": {
                            f"file_{i}.db": {
                                "path": f"/path/to/file_{i}.db",
                                "filesize": 1024000,
                            }
                        }
                    }
                    if i % 3 == 0
                    else {}
                ),
            }

        # Mock device scanner
        self.mock_device_scanner.get_all_devices_info.return_value = large_device_set

        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock service responses
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # Mock backup info function to be fast
            with patch(
                "ethoscope_node.backup.helpers.get_device_backup_info"
            ) as mock_get_backup:
                mock_get_backup.return_value = {
                    "backup_status": {
                        "mysql": {
                            "available": False,
                            "database_count": 0,
                            "total_size_bytes": 0,
                            "last_backup": 0,
                        },
                        "sqlite": {
                            "available": True,
                            "database_count": 1,
                            "total_size_bytes": 1024000,
                            "last_backup": time.time(),
                        },
                        "video": {
                            "available": False,
                            "file_count": 0,
                            "total_size_bytes": 0,
                            "last_backup": 0,
                        },
                    }
                }

                # Measure performance
                start_time = time.time()
                result = self.backup_api._get_backup_status()
                execution_time = time.time() - start_time

                # Should complete reasonably quickly even with many devices
                self.assertLess(
                    execution_time,
                    5.0,
                    f"Backup status should complete quickly with 50 devices, took {execution_time:.2f}s",
                )

                # Verify all devices are included
                response_data = json.loads(result)
                devices = response_data["devices"]
                self.assertEqual(len(devices), 50)

    def test_backup_status_response_structure_for_frontend(self):
        """Test that backup status response structure matches frontend expectations."""
        # Mock device with comprehensive data
        test_device = {
            "test_device": {
                "id": "test_device",
                "name": "ETHOSCOPE_TEST",
                "status": "running",
                "databases": {
                    "MariaDB": {"ethoscope_db": {"table1": 1000}},
                    "SQLite": {
                        "file1.db": {"path": "/path/file1.db", "filesize": 1024000}
                    },
                },
            }
        }

        self.mock_device_scanner.get_all_devices_info.return_value = test_device

        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock service responses
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            with patch(
                "ethoscope_node.backup.helpers.get_device_backup_info"
            ) as mock_get_backup:
                mock_get_backup.return_value = {
                    "backup_status": {
                        "mysql": {
                            "available": True,
                            "database_count": 1,
                            "total_size_bytes": 2048000,
                            "last_backup": time.time() - 3600,
                        },
                        "sqlite": {
                            "available": True,
                            "database_count": 1,
                            "total_size_bytes": 1024000,
                            "last_backup": time.time() - 1800,
                        },
                        "video": {
                            "available": True,
                            "file_count": 10,
                            "total_size_bytes": 10485760,
                            "size_human": "10.0 MB",
                            "last_backup": time.time() - 7200,
                        },
                    }
                }

                result = self.backup_api._get_backup_status()
                response_data = json.loads(result)

                # Check structure expected by script.js getBackupStatusText function
                device_data = response_data["devices"]["test_device"]
                backup_types = device_data["backup_types"]

                # Verify fields required by JavaScript
                for backup_type in ["mysql", "sqlite", "video"]:
                    backup_info = backup_types[backup_type]

                    # Fields used in getBackupStatusText function
                    self.assertIn(
                        "size", backup_info
                    )  # mysql.size, sqlite.size, video.size
                    self.assertIn("last_backup", backup_info)  # mysql.last_backup, etc.
                    self.assertIn("available", backup_info)  # For availability checks
                    self.assertIn("processing", backup_info)  # For processing status

                # Verify overall_status field
                self.assertIn("overall_status", device_data)
                self.assertIn(
                    device_data["overall_status"],
                    ["success", "partial", "error", "no_backups", "unknown"],
                )

                # Verify numeric fields are actually numeric
                for backup_type in ["mysql", "sqlite", "video"]:
                    backup_info = backup_types[backup_type]
                    self.assertIsInstance(backup_info["size"], (int, float))
                    self.assertIsInstance(backup_info["last_backup"], (int, float))
                    self.assertIsInstance(backup_info["processing"], bool)


class TestBackupAPIErrorHandling(unittest.TestCase):
    """Test backup API error handling and edge cases."""

    def setUp(self):
        """Set up test environment."""
        self.mock_app = MagicMock()
        self.mock_device_scanner = MagicMock()
        self.backup_api = BackupAPI(
            app=self.mock_app,
            device_scanner=self.mock_device_scanner,
            config={},
            logger=MagicMock(),
        )

    def test_device_scanner_unavailable(self):
        """Test handling when device scanner is unavailable."""
        self.backup_api.device_scanner = None

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            result = self.backup_api._get_backup_status()
            response_data = json.loads(result)

            # Should handle gracefully
            self.assertIn("devices", response_data)
            self.assertEqual(len(response_data["devices"]), 0)

    def test_malformed_service_response(self):
        """Test handling of malformed service responses."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock malformed JSON response
            mock_response = MagicMock()
            mock_response.read.return_value = b"invalid json {"
            mock_urlopen.return_value.__enter__.return_value = mock_response

            self.mock_device_scanner.get_all_devices_info.return_value = {}

            result = self.backup_api._get_backup_status()
            response_data = json.loads(result)

            # Should handle gracefully with error indicators
            services = response_data["services"]
            self.assertFalse(services["mysql_backup"]["available"])
            self.assertFalse(services["rsync_backup"]["available"])

    def test_cache_corruption_recovery(self):
        """Test recovery from cache corruption."""
        # Corrupt the cache
        self.backup_api._backup_cache["data"] = "invalid json"

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps({}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            self.mock_device_scanner.get_all_devices_info.return_value = {}

            # Should recover and regenerate cache
            result = self.backup_api._get_backup_status()

            # Should be valid JSON
            response_data = json.loads(result)
            self.assertIn("devices", response_data)

            # Cache should be regenerated
            self.assertNotEqual(self.backup_api._backup_cache["data"], "invalid json")


if __name__ == "__main__":
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    test_classes = [TestBackupAPIIntegration, TestBackupAPIErrorHandling]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
