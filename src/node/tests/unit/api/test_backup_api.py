"""
Unit tests for Backup API endpoints.

Tests backup system management including status aggregation from MySQL and
rsync backup services, device backup information, and caching mechanisms.
"""

import json
import time
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from ethoscope_node.api.backup_api import BackupAPI


class TestBackupAPI(unittest.TestCase):
    """Test suite for BackupAPI class."""

    def setUp(self):
        """Create mock server instance and BackupAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.device_scanner = Mock()
        self.mock_server.logger = Mock()

        self.api = BackupAPI(self.mock_server)

    def test_init(self):
        """Test BackupAPI initialization sets up cache correctly."""
        self.assertIsNotNone(self.api._backup_cache)
        self.assertIsNone(self.api._backup_cache["data"])
        self.assertEqual(self.api._backup_cache["timestamp"], 0)
        self.assertEqual(self.api._backup_cache["ttl"], 300)

    def test_register_routes(self):
        """Test that backup routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 1 route
        self.assertEqual(len(route_calls), 1)
        self.assertEqual(route_calls[0][0], "/backup/status")
        self.assertEqual(route_calls[0][1], "GET")
        self.assertEqual(route_calls[0][2], "_get_backup_status")

    @patch("ethoscope_node.api.backup_api.time.time")
    @patch.object(BackupAPI, "_fetch_backup_service_status")
    @patch.object(BackupAPI, "_get_devices_backup_summary")
    def test_get_backup_status_success(
        self, mock_get_devices, mock_fetch_status, mock_time
    ):
        """Test getting backup status successfully."""
        mock_time.return_value = 1000.0

        # Mock service status responses
        mysql_status = {
            "current_device": "ETHOSCOPE_001",
            "current_file": "backup_001.sql",
        }
        rsync_status = {
            "current_device": "ETHOSCOPE_002",
            "current_file": "video_002.h264",
        }

        mock_fetch_status.side_effect = [mysql_status, rsync_status]
        mock_get_devices.return_value = {
            "ETHOSCOPE_001": {
                "backup_types": {"mysql": {"available": True}},
                "overall_status": "success",
            }
        }

        result = self.api._get_backup_status()
        result_dict = json.loads(result)

        # Verify structure
        self.assertIn("services", result_dict)
        self.assertIn("summary", result_dict)
        self.assertIn("devices", result_dict)
        self.assertIn("processing_devices", result_dict)
        self.assertIn("timestamp", result_dict)

        # Verify services
        self.assertTrue(result_dict["services"]["mysql_backup"]["available"])
        self.assertEqual(
            result_dict["services"]["mysql_backup"]["current_device"], "ETHOSCOPE_001"
        )
        self.assertEqual(
            result_dict["services"]["mysql_backup"]["current_file"], "backup_001.sql"
        )

        self.assertTrue(result_dict["services"]["rsync_backup"]["available"])
        self.assertEqual(
            result_dict["services"]["rsync_backup"]["current_device"], "ETHOSCOPE_002"
        )

        # Verify processing devices
        self.assertEqual(len(result_dict["processing_devices"]), 2)

        # Verify cache was updated
        self.assertIsNotNone(self.api._backup_cache["data"])
        self.assertEqual(self.api._backup_cache["timestamp"], 1000.0)

    @patch("ethoscope_node.api.backup_api.time.time")
    def test_get_backup_status_from_cache(self, mock_time):
        """Test that cached status is returned if still valid."""
        mock_time.return_value = 1100.0

        # Set up cache with data
        cached_data = json.dumps({"cached": True, "timestamp": 1000.0})
        self.api._backup_cache = {"data": cached_data, "timestamp": 1050.0, "ttl": 60}

        result = self.api._get_backup_status()

        # Should return cached data
        self.assertEqual(result, cached_data)
        result_dict = json.loads(result)
        self.assertTrue(result_dict["cached"])

    @patch("ethoscope_node.api.backup_api.time.time")
    @patch.object(BackupAPI, "_fetch_backup_service_status")
    @patch.object(BackupAPI, "_get_devices_backup_summary")
    def test_get_backup_status_cache_expired(
        self, mock_get_devices, mock_fetch_status, mock_time
    ):
        """Test that new data is fetched when cache expires."""
        mock_time.return_value = 2000.0

        # Set up expired cache
        self.api._backup_cache = {"data": "old_data", "timestamp": 1000.0, "ttl": 60}

        # Mock fresh data
        mock_fetch_status.side_effect = [
            {"current_device": "NEW_001"},
            {"current_device": "NEW_002"},
        ]
        mock_get_devices.return_value = {}

        result = self.api._get_backup_status()

        # Should fetch fresh data, not use cache
        self.assertNotEqual(result, "old_data")
        mock_fetch_status.assert_called()

    @patch("urllib.request.urlopen")
    def test_fetch_backup_service_status_success(self, mock_urlopen):
        """Test successfully fetching backup service status."""
        mock_response = Mock()
        mock_response.read.return_value = b'{"status": "running", "device": "001"}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = self.api._fetch_backup_service_status(8090, "MySQL")

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["device"], "001")
        mock_urlopen.assert_called_once_with("http://localhost:8090/status", timeout=5)

    @patch("urllib.request.urlopen")
    def test_fetch_backup_service_status_timeout(self, mock_urlopen):
        """Test handling of backup service timeout."""
        mock_urlopen.side_effect = URLError("timeout")

        result = self.api._fetch_backup_service_status(8093, "Rsync")

        self.assertIn("error", result)
        self.assertEqual(result["error"], "Rsync backup service unavailable")

    @patch("urllib.request.urlopen")
    def test_fetch_backup_service_status_connection_error(self, mock_urlopen):
        """Test handling of backup service connection error."""
        mock_urlopen.side_effect = ConnectionError("Connection refused")

        result = self.api._fetch_backup_service_status(8090, "MySQL")

        self.assertIn("error", result)
        self.assertEqual(result["error"], "MySQL backup service unavailable")

    def test_extract_current_device_error_status(self):
        """Test extracting device from error status returns None."""
        service_status = {"error": "Service unavailable"}

        result = self.api._extract_current_device(service_status)

        self.assertIsNone(result)

    def test_extract_current_device_simplified_format(self):
        """Test extracting device from simplified format."""
        service_status = {"current_device": "ETHOSCOPE_001"}

        result = self.api._extract_current_device(service_status)

        self.assertEqual(result, "ETHOSCOPE_001")

    def test_extract_current_device_array_format(self):
        """Test extracting device from array format."""
        service_status = {
            "processing_devices": [
                {"device_name": "ETHOSCOPE_002", "current_file": "test.sql"}
            ]
        }

        result = self.api._extract_current_device(service_status)

        self.assertEqual(result, "ETHOSCOPE_002")

    def test_extract_current_device_array_format_empty(self):
        """Test extracting device from empty array format returns None."""
        service_status = {"processing_devices": []}

        result = self.api._extract_current_device(service_status)

        self.assertIsNone(result)

    def test_extract_current_device_legacy_format(self):
        """Test extracting device from legacy format."""
        service_status = {
            "device_001": {
                "name": "ETHOSCOPE_001",
                "processing": True,
                "progress": {"current_file": "backup.sql"},
            },
            "device_002": {
                "name": "ETHOSCOPE_002",
                "processing": False,
            },
        }

        result = self.api._extract_current_device(service_status)

        self.assertEqual(result, "ETHOSCOPE_001")

    def test_extract_current_device_legacy_format_no_processing(self):
        """Test legacy format with no processing devices returns None."""
        service_status = {
            "device_001": {
                "name": "ETHOSCOPE_001",
                "processing": False,
            }
        }

        result = self.api._extract_current_device(service_status)

        self.assertIsNone(result)

    def test_extract_current_file_error_status(self):
        """Test extracting file from error status returns None."""
        service_status = {"error": "Service unavailable"}

        result = self.api._extract_current_file(service_status)

        self.assertIsNone(result)

    def test_extract_current_file_simplified_format(self):
        """Test extracting file from simplified format."""
        service_status = {"current_file": "backup_001.sql"}

        result = self.api._extract_current_file(service_status)

        self.assertEqual(result, "backup_001.sql")

    def test_extract_current_file_array_format(self):
        """Test extracting file from array format."""
        service_status = {
            "processing_devices": [
                {"device_name": "ETHOSCOPE_001", "current_file": "video_001.h264"}
            ]
        }

        result = self.api._extract_current_file(service_status)

        self.assertEqual(result, "video_001.h264")

    def test_extract_current_file_array_format_empty(self):
        """Test extracting file from empty array format returns None."""
        service_status = {"processing_devices": []}

        result = self.api._extract_current_file(service_status)

        self.assertIsNone(result)

    def test_extract_current_file_legacy_format_current_file(self):
        """Test extracting file from legacy format with current_file."""
        service_status = {
            "device_001": {
                "processing": True,
                "progress": {"current_file": "backup.sql"},
            }
        }

        result = self.api._extract_current_file(service_status)

        self.assertEqual(result, "backup.sql")

    def test_extract_current_file_legacy_format_backup_filename(self):
        """Test extracting file from legacy format with backup_filename."""
        service_status = {
            "device_001": {
                "processing": True,
                "progress": {"backup_filename": "backup_legacy.sql"},
            }
        }

        result = self.api._extract_current_file(service_status)

        self.assertEqual(result, "backup_legacy.sql")

    def test_extract_current_file_legacy_format_no_processing(self):
        """Test legacy format with no processing devices returns None."""
        service_status = {
            "device_001": {
                "processing": False,
                "progress": {"current_file": "backup.sql"},
            }
        }

        result = self.api._extract_current_file(service_status)

        self.assertIsNone(result)

    def test_get_processing_devices_both_services(self):
        """Test getting processing devices from both services."""
        mysql_status = {"current_device": "ETHOSCOPE_001", "current_file": "db_001.sql"}
        rsync_status = {
            "current_device": "ETHOSCOPE_002",
            "current_file": "video_002.h264",
        }

        result = self.api._get_processing_devices(mysql_status, rsync_status)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["service"], "mysql")
        self.assertEqual(result[0]["device"], "ETHOSCOPE_001")
        self.assertEqual(result[0]["current_file"], "db_001.sql")
        self.assertEqual(result[1]["service"], "rsync")
        self.assertEqual(result[1]["device"], "ETHOSCOPE_002")
        self.assertEqual(result[1]["current_file"], "video_002.h264")

    def test_get_processing_devices_mysql_only(self):
        """Test getting processing devices with only MySQL active."""
        mysql_status = {"current_device": "ETHOSCOPE_001", "current_file": "db_001.sql"}
        rsync_status = {"error": "Service unavailable"}

        result = self.api._get_processing_devices(mysql_status, rsync_status)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "mysql")
        self.assertEqual(result[0]["device"], "ETHOSCOPE_001")

    def test_get_processing_devices_rsync_only(self):
        """Test getting processing devices with only rsync active."""
        mysql_status = {"error": "Service unavailable"}
        rsync_status = {
            "current_device": "ETHOSCOPE_002",
            "current_file": "video_002.h264",
        }

        result = self.api._get_processing_devices(mysql_status, rsync_status)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "rsync")
        self.assertEqual(result[0]["device"], "ETHOSCOPE_002")

    def test_get_processing_devices_none_processing(self):
        """Test getting processing devices when none are processing."""
        mysql_status = {"error": "Service unavailable"}
        rsync_status = {"error": "Service unavailable"}

        result = self.api._get_processing_devices(mysql_status, rsync_status)

        self.assertEqual(len(result), 0)

    def test_get_devices_backup_summary_no_scanner(self):
        """Test device backup summary with no device scanner."""
        self.api.device_scanner = None

        result = self.api._get_devices_backup_summary()

        self.assertEqual(result, {})

    @patch("ethoscope_node.backup.helpers.get_device_backup_info")
    def test_get_devices_backup_summary_online_devices(self, mock_get_backup_info):
        """Test device backup summary with online devices."""
        # Mock device scanner data
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "online",
                "databases": {"db1": {"path": "/path/to/db1.db"}},
            },
            "ETHOSCOPE_002": {
                "status": "online",
                "databases": {"db2": {"path": "/path/to/db2.db"}},
            },
        }

        # Mock backup info
        mock_get_backup_info.return_value = {
            "backup_status": {
                "mysql": {
                    "available": True,
                    "total_size_bytes": 1024,
                    "last_backup": 1000,
                    "database_count": 1,
                    "directory": "/backups/mysql",
                    "message": "OK",
                },
                "sqlite": {
                    "available": True,
                    "total_size_bytes": 2048,
                    "last_backup": 1000,
                    "database_count": 2,
                    "directory": "/backups/sqlite",
                },
                "video": {
                    "available": True,
                    "total_size_bytes": 4096,
                    "last_backup": 1000,
                    "file_count": 5,
                    "directory": "/backups/video",
                    "size_human": "4.0 KB",
                },
            }
        }

        result = self.api._get_devices_backup_summary()

        # Verify both devices are in result
        self.assertIn("ETHOSCOPE_001", result)
        self.assertIn("ETHOSCOPE_002", result)

        # Verify structure for first device
        device_data = result["ETHOSCOPE_001"]
        self.assertIn("backup_types", device_data)
        self.assertIn("overall_status", device_data)
        self.assertEqual(device_data["overall_status"], "success")

        # Verify backup types
        self.assertTrue(device_data["backup_types"]["mysql"]["available"])
        self.assertEqual(device_data["backup_types"]["mysql"]["status"], "success")
        self.assertEqual(device_data["backup_types"]["mysql"]["size"], 1024)
        self.assertEqual(device_data["backup_types"]["mysql"]["last_backup"], 1000)
        self.assertEqual(device_data["backup_types"]["mysql"]["records"], 1)

        self.assertTrue(device_data["backup_types"]["sqlite"]["available"])
        self.assertEqual(device_data["backup_types"]["sqlite"]["files"], 2)

        self.assertTrue(device_data["backup_types"]["video"]["available"])
        self.assertEqual(device_data["backup_types"]["video"]["files"], 5)
        self.assertEqual(device_data["backup_types"]["video"]["size_human"], "4.0 KB")

    @patch("ethoscope_node.backup.helpers.get_device_backup_info")
    def test_get_devices_backup_summary_partial_backups(self, mock_get_backup_info):
        """Test device backup summary with partial backups available."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "online",
                "databases": {"db1": {"path": "/path/to/db1.db"}},
            }
        }

        # Mock partial backup availability
        mock_get_backup_info.return_value = {
            "backup_status": {
                "mysql": {
                    "available": True,
                    "total_size_bytes": 1024,
                    "last_backup": 1000,
                    "database_count": 1,
                    "directory": "/backups/mysql",
                    "message": "OK",
                },
                "sqlite": {
                    "available": False,
                    "total_size_bytes": 0,
                    "last_backup": 0,
                    "database_count": 0,
                    "directory": "",
                },
                "video": {
                    "available": True,
                    "total_size_bytes": 4096,
                    "last_backup": 1000,
                    "file_count": 5,
                    "directory": "/backups/video",
                    "size_human": "4.0 KB",
                },
            }
        }

        result = self.api._get_devices_backup_summary()

        device_data = result["ETHOSCOPE_001"]
        self.assertEqual(device_data["overall_status"], "partial")
        self.assertTrue(device_data["backup_types"]["mysql"]["available"])
        self.assertFalse(device_data["backup_types"]["sqlite"]["available"])
        self.assertTrue(device_data["backup_types"]["video"]["available"])

    @patch("ethoscope_node.backup.helpers.get_device_backup_info")
    def test_get_devices_backup_summary_no_backups(self, mock_get_backup_info):
        """Test device backup summary with no backups available."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "online",
                "databases": {"db1": {"path": "/path/to/db1.db"}},
            }
        }

        # Mock no backups available
        mock_get_backup_info.return_value = {
            "backup_status": {
                "mysql": {
                    "available": False,
                    "total_size_bytes": 0,
                    "last_backup": 0,
                    "database_count": 0,
                    "directory": "",
                    "message": "",
                },
                "sqlite": {
                    "available": False,
                    "total_size_bytes": 0,
                    "last_backup": 0,
                    "database_count": 0,
                    "directory": "",
                },
                "video": {
                    "available": False,
                    "total_size_bytes": 0,
                    "last_backup": 0,
                    "file_count": 0,
                    "directory": "",
                    "size_human": "",
                },
            }
        }

        result = self.api._get_devices_backup_summary()

        device_data = result["ETHOSCOPE_001"]
        self.assertEqual(device_data["overall_status"], "no_backups")
        self.assertFalse(device_data["backup_types"]["mysql"]["available"])
        self.assertFalse(device_data["backup_types"]["sqlite"]["available"])
        self.assertFalse(device_data["backup_types"]["video"]["available"])

    def test_get_devices_backup_summary_offline_device(self):
        """Test device backup summary with offline devices."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "offline",
                "databases": {},
            }
        }

        result = self.api._get_devices_backup_summary()

        device_data = result["ETHOSCOPE_001"]
        self.assertEqual(device_data["overall_status"], "no_backups")
        self.assertEqual(device_data["backup_types"]["mysql"]["status"], "offline")
        self.assertEqual(device_data["backup_types"]["sqlite"]["status"], "offline")
        self.assertEqual(device_data["backup_types"]["video"]["status"], "offline")

    def test_get_devices_backup_summary_no_databases(self):
        """Test device backup summary with online device but no databases."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "online",
                "databases": {},
            }
        }

        result = self.api._get_devices_backup_summary()

        device_data = result["ETHOSCOPE_001"]
        self.assertEqual(device_data["overall_status"], "no_backups")

    @patch("ethoscope_node.backup.helpers.get_device_backup_info")
    def test_get_devices_backup_summary_exception_handling(self, mock_get_backup_info):
        """Test device backup summary handles exceptions gracefully."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "online",
                "databases": {"db1": {"path": "/path/to/db1.db"}},
            }
        }

        # Mock exception during backup info retrieval
        mock_get_backup_info.side_effect = Exception("Backup error")

        result = self.api._get_devices_backup_summary()

        device_data = result["ETHOSCOPE_001"]
        self.assertEqual(device_data["overall_status"], "unknown")
        self.assertEqual(device_data["backup_types"]["mysql"]["status"], "unknown")
        self.assertEqual(device_data["backup_types"]["sqlite"]["status"], "unknown")
        self.assertEqual(device_data["backup_types"]["video"]["status"], "unknown")

    def test_get_devices_backup_summary_scanner_exception(self):
        """Test device backup summary handles scanner exceptions gracefully."""
        self.api.device_scanner.get_all_devices_info.side_effect = Exception(
            "Scanner error"
        )

        result = self.api._get_devices_backup_summary()

        self.assertEqual(result, {})

    @patch("ethoscope_node.api.backup_api.time.time")
    @patch.object(BackupAPI, "_fetch_backup_service_status")
    @patch.object(BackupAPI, "_get_devices_backup_summary")
    def test_get_backup_status_service_unavailable(
        self, mock_get_devices, mock_fetch_status, mock_time
    ):
        """Test backup status when services are unavailable."""
        mock_time.return_value = 1000.0

        # Mock both services unavailable
        mock_fetch_status.side_effect = [
            {"error": "MySQL backup service unavailable"},
            {"error": "Rsync backup service unavailable"},
        ]
        mock_get_devices.return_value = {}

        result = self.api._get_backup_status()
        result_dict = json.loads(result)

        # Verify services are marked as unavailable
        self.assertFalse(result_dict["services"]["mysql_backup"]["available"])
        self.assertFalse(result_dict["services"]["rsync_backup"]["available"])
        self.assertFalse(result_dict["summary"]["mysql_backup_available"])
        self.assertFalse(result_dict["summary"]["rsync_backup_available"])

        # Verify no processing devices
        self.assertEqual(len(result_dict["processing_devices"]), 0)

    @patch("ethoscope_node.api.backup_api.time.time")
    @patch.object(BackupAPI, "_fetch_backup_service_status")
    @patch.object(BackupAPI, "_get_devices_backup_summary")
    def test_get_backup_status_mixed_service_availability(
        self, mock_get_devices, mock_fetch_status, mock_time
    ):
        """Test backup status with mixed service availability."""
        mock_time.return_value = 1000.0

        # Mock MySQL available, rsync unavailable
        mock_fetch_status.side_effect = [
            {"current_device": "ETHOSCOPE_001", "current_file": "backup.sql"},
            {"error": "Rsync backup service unavailable"},
        ]
        mock_get_devices.return_value = {}

        result = self.api._get_backup_status()
        result_dict = json.loads(result)

        # Verify service availability
        self.assertTrue(result_dict["services"]["mysql_backup"]["available"])
        self.assertFalse(result_dict["services"]["rsync_backup"]["available"])

        # Verify only MySQL processing device
        self.assertEqual(len(result_dict["processing_devices"]), 1)
        self.assertEqual(result_dict["processing_devices"][0]["service"], "mysql")

    @patch.object(BackupAPI, "set_json_response")
    @patch("ethoscope_node.api.backup_api.time.time")
    @patch.object(BackupAPI, "_fetch_backup_service_status")
    @patch.object(BackupAPI, "_get_devices_backup_summary")
    def test_get_backup_status_sets_json_response(
        self, mock_get_devices, mock_fetch_status, mock_time, mock_set_json
    ):
        """Test that backup status sets JSON response headers."""
        mock_time.return_value = 1000.0
        mock_fetch_status.side_effect = [{}, {}]
        mock_get_devices.return_value = {}

        self.api._get_backup_status()

        mock_set_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
