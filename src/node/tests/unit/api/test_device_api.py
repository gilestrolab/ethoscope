"""
Unit tests for Device API endpoints.

Tests device discovery, management, control, information retrieval,
image/video operations, and batch endpoints.
"""

import io
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, call, mock_open, patch

import bottle

from ethoscope_node.api.device_api import DeviceAPI


class TestDeviceAPI(unittest.TestCase):
    """Test suite for DeviceAPI class."""

    def setUp(self):
        """Create mock server instance and DeviceAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = {}
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"

        # Create temp directory for image caching tests
        self.temp_dir = tempfile.mkdtemp()
        self.mock_server.tmp_imgs_dir = self.temp_dir
        self.mock_server._serve_tmp_static = Mock(return_value="/static/tmp/test.jpg")

        self.api = DeviceAPI(self.mock_server)

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_register_routes(self):
        """Test that all device routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 22 routes
        self.assertEqual(len(route_calls), 22)

        # Check specific routes
        paths = [call[0] for call in route_calls]
        self.assertIn("/devices", paths)
        self.assertIn("/devices_list", paths)
        self.assertIn("/devices/retire-inactive", paths)
        self.assertIn("/devices/cleanup-busy", paths)
        self.assertIn("/device/add", paths)
        self.assertIn("/device/<id>/data", paths)
        self.assertIn("/device/<id>/machineinfo", paths)
        self.assertIn("/device/<id>/module", paths)
        self.assertIn("/device/<id>/user_options", paths)
        self.assertIn("/device/<id>/videofiles", paths)
        self.assertIn("/device/<id>/last_img", paths)
        self.assertIn("/device/<id>/dbg_img", paths)
        self.assertIn("/device/<id>/stream", paths)
        self.assertIn("/device/<id>/backup", paths)
        self.assertIn("/device/<id>/dumpSQLdb", paths)
        self.assertIn("/device/<id>/retire", paths)
        self.assertIn("/device/<id>/controls/<instruction>", paths)
        self.assertIn("/device/<id>/log", paths)
        self.assertIn("/device/<id>/batch", paths)
        self.assertIn("/device/<id>/batch-critical", paths)

    @patch("ethoscope_node.api.device_api.BaseAPI.get_query_param")
    def test_get_devices_without_inactive(self, mock_get_param):
        """Test getting devices without inactive filter."""
        mock_get_param.return_value = ""
        mock_devices = [
            {"id": "device1", "status": "active"},
            {"id": "device2", "status": "active"},
        ]
        self.api.device_scanner.get_all_devices_info.return_value = mock_devices

        result = self.api._get_devices()

        self.assertEqual(result, mock_devices)
        self.api.device_scanner.get_all_devices_info.assert_called_once_with(
            include_inactive=False
        )

    @patch("ethoscope_node.api.device_api.BaseAPI.get_query_param")
    def test_get_devices_with_inactive(self, mock_get_param):
        """Test getting devices with inactive filter."""
        mock_get_param.return_value = "true"
        mock_devices = [
            {"id": "device1", "status": "active"},
            {"id": "device2", "status": "inactive"},
        ]
        self.api.device_scanner.get_all_devices_info.return_value = mock_devices

        result = self.api._get_devices()

        self.assertEqual(result, mock_devices)
        self.api.device_scanner.get_all_devices_info.assert_called_once_with(
            include_inactive=True
        )

    def test_get_devices_list_alias(self):
        """Test that _get_devices_list is an alias for _get_devices."""
        mock_devices = [{"id": "device1", "status": "active"}]
        self.api.device_scanner.get_all_devices_info.return_value = mock_devices

        with patch.object(self.api, "_get_devices", return_value=mock_devices):
            result = self.api._get_devices_list()

        self.assertEqual(result, mock_devices)

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_retire_inactive_devices_success(self, mock_get_data):
        """Test retiring inactive devices successfully."""
        mock_get_data.return_value = json.dumps({"threshold_days": 30}).encode("utf-8")

        self.api.database.cleanup_stale_busy_devices.return_value = 2
        self.api.database.purge_unnamed_devices.return_value = 1
        self.api.database.retire_inactive_devices.return_value = 5

        result = self.api._retire_inactive_devices()

        self.assertTrue(result["success"])
        self.assertEqual(result["retired_count"], 5)
        self.assertEqual(result["purged_count"], 1)
        self.assertEqual(result["busy_cleaned_count"], 2)
        self.assertEqual(result["threshold_days"], 30)

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_retire_inactive_devices_default_threshold(self, mock_get_data):
        """Test retiring inactive devices with default threshold."""
        mock_get_data.return_value = b""  # Empty request data

        self.api.database.cleanup_stale_busy_devices.return_value = 0
        self.api.database.purge_unnamed_devices.return_value = 0
        self.api.database.retire_inactive_devices.return_value = 3

        result = self.api._retire_inactive_devices()

        self.assertTrue(result["success"])
        self.assertEqual(result["threshold_days"], 90)  # Default value

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_retire_inactive_devices_invalid_json(self, mock_get_data):
        """Test retiring inactive devices with invalid JSON."""
        mock_get_data.return_value = b"not valid json"

        self.api.database.cleanup_stale_busy_devices.return_value = 0
        self.api.database.purge_unnamed_devices.return_value = 0
        self.api.database.retire_inactive_devices.return_value = 1

        result = self.api._retire_inactive_devices()

        self.assertTrue(result["success"])
        self.assertEqual(result["threshold_days"], 90)  # Falls back to default

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_retire_inactive_devices_exception(self, mock_get_data):
        """Test retiring inactive devices handles exceptions."""
        mock_get_data.return_value = b""
        self.api.database.cleanup_stale_busy_devices.side_effect = RuntimeError(
            "Database error"
        )

        result = self.api._retire_inactive_devices()

        self.assertFalse(result["success"])
        self.assertIn("Database error", result["error"])

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_cleanup_busy_devices_success(self, mock_get_data):
        """Test cleaning up busy devices successfully."""
        mock_get_data.return_value = json.dumps({"threshold_hours": 4}).encode("utf-8")
        self.api.database.cleanup_offline_busy_devices.return_value = 3

        result = self.api._cleanup_busy_devices()

        self.assertTrue(result["success"])
        self.assertEqual(result["cleaned_count"], 3)
        self.assertEqual(result["threshold_hours"], 4)

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_cleanup_busy_devices_default_threshold(self, mock_get_data):
        """Test cleaning up busy devices with default threshold."""
        mock_get_data.return_value = b""
        self.api.database.cleanup_offline_busy_devices.return_value = 2

        result = self.api._cleanup_busy_devices()

        self.assertTrue(result["success"])
        self.assertEqual(result["threshold_hours"], 2)  # Default value

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_cleanup_busy_devices_exception(self, mock_get_data):
        """Test cleanup busy devices handles exceptions."""
        mock_get_data.return_value = b""
        self.api.database.cleanup_offline_busy_devices.side_effect = RuntimeError(
            "Database error"
        )

        result = self.api._cleanup_busy_devices()

        self.assertFalse(result["success"])
        self.assertIn("Database error", result["error"])

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_manual_add_device_success(self, mock_get_data):
        """Test manually adding devices successfully."""
        mock_get_data.return_value = b"192.168.1.100, 192.168.1.101"

        result = self.api._manual_add_device()

        self.assertEqual(len(result["added"]), 2)
        self.assertIn("192.168.1.100", result["added"])
        self.assertIn("192.168.1.101", result["added"])
        self.assertEqual(result["problems"], [])

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_manual_add_device_partial_failure(self, mock_get_data):
        """Test manually adding devices with some failures."""
        mock_get_data.return_value = b"192.168.1.100, 192.168.1.101"

        # First succeeds, second fails
        self.api.device_scanner.add.side_effect = [None, Exception("Connection error")]

        result = self.api._manual_add_device()

        self.assertEqual(len(result["added"]), 1)
        self.assertIn("192.168.1.100", result["added"])
        self.assertEqual(len(result["problems"]), 1)
        self.assertIn("192.168.1.101", result["problems"])

    def test_get_device_info(self):
        """Test getting device information."""
        mock_device = Mock()
        mock_device.info.return_value = {
            "id": "device1",
            "status": "active",
            "databases": {"db1": "info"},  # Should be removed
        }
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_info("device1")

        self.assertEqual(result["id"], "device1")
        self.assertEqual(result["status"], "active")
        self.assertNotIn("databases", result)  # Should be filtered out

    def test_get_device_machine_info_with_device(self):
        """Test getting device machine info when device exists."""
        mock_device = Mock()
        mock_device.machine_info.return_value = {
            "hardware": "RaspberryPi",
            "version": "1.0",
        }
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_machine_info("device1")

        self.assertEqual(result["hardware"], "RaspberryPi")
        mock_device.machine_info.assert_called_once()

    def test_get_device_machine_info_without_device(self):
        """Test getting device machine info when device not in scanner."""
        self.api.device_scanner.get_device.return_value = None
        self.api.device_scanner.get_all_devices_info.return_value = {
            "device1": {"hardware": "RaspberryPi"}
        }

        result = self.api._get_device_machine_info("device1")

        self.assertEqual(result["hardware"], "RaspberryPi")

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_set_device_machine_info_success(self, mock_get_data):
        """Test updating device machine info successfully."""
        mock_get_data.return_value = b'{"hardware": "updated"}'
        mock_device = Mock()
        mock_device.send_settings.return_value = {"haschanged": True}
        mock_device.machine_info.return_value = {"hardware": "updated"}
        mock_device.setup_ssh_authentication.return_value = True
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._set_device_machine_info("device1")

        self.assertTrue(result["haschanged"])
        self.assertEqual(result["hardware"], "updated")
        mock_device.setup_ssh_authentication.assert_called_once()

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_set_device_machine_info_no_change(self, mock_get_data):
        """Test updating device machine info with no changes."""
        mock_get_data.return_value = b'{"hardware": "same"}'
        mock_device = Mock()
        mock_device.send_settings.return_value = {"haschanged": False}
        mock_device.machine_info.return_value = {"hardware": "same"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._set_device_machine_info("device1")

        self.assertFalse(result["haschanged"])
        # SSH setup should not be called if nothing changed
        mock_device.setup_ssh_authentication.assert_not_called()

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_set_device_machine_info_ssh_failure(self, mock_get_data):
        """Test updating device machine info with SSH setup failure."""
        mock_get_data.return_value = b'{"hardware": "updated"}'
        mock_device = Mock()
        mock_device.send_settings.return_value = {"haschanged": True}
        mock_device.machine_info.return_value = {"hardware": "updated"}
        mock_device.setup_ssh_authentication.side_effect = Exception("SSH error")
        self.api.device_scanner.get_device.return_value = mock_device

        with patch.object(self.api.logger, "warning") as mock_log:
            result = self.api._set_device_machine_info("device1")

            self.assertTrue(result["haschanged"])
            # Should log warning but not fail
            mock_log.assert_called_once()
            self.assertIn("SSH", str(mock_log.call_args))

    def test_get_device_module_with_device(self):
        """Test getting device module when device exists."""
        mock_device = Mock()
        mock_device.connected_module.return_value = {"module": "camera"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_module("device1")

        self.assertEqual(result["module"], "camera")

    def test_get_device_module_without_device(self):
        """Test getting device module when device doesn't exist."""
        self.api.device_scanner.get_device.return_value = None

        result = self.api._get_device_module("device1")

        self.assertEqual(result, {})

    def test_get_device_options_with_device(self):
        """Test getting device options when device exists."""
        mock_device = Mock()
        mock_device.user_options.return_value = {"option1": "value1"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_options("device1")

        self.assertEqual(result["option1"], "value1")

    def test_get_device_options_without_device(self):
        """Test getting device options when device doesn't exist."""
        self.api.device_scanner.get_device.return_value = None

        result = self.api._get_device_options("device1")

        self.assertIsNone(result)

    def test_get_device_videofiles_success(self):
        """Test getting device video files successfully."""
        mock_device = Mock()
        mock_device.videofiles.return_value = ["video1.h264", "video2.h264"]
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_videofiles("device1")

        self.assertEqual(len(result), 2)
        self.assertIn("video1.h264", result)

    def test_get_device_videofiles_exception(self):
        """Test getting device video files handles exceptions."""
        mock_device = Mock()
        mock_device.videofiles.side_effect = Exception("Network error")
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_videofiles("device1")

        # Should return empty list on error
        self.assertEqual(result, [])

    def test_get_device_videofiles_no_device(self):
        """Test getting device video files when device doesn't exist."""
        self.api.device_scanner.get_device.return_value = None

        result = self.api._get_device_videofiles("device1")

        self.assertEqual(result, [])

    def test_get_device_last_img_success(self):
        """Test getting device last image successfully."""
        mock_device = Mock()
        mock_device.info.return_value = {"status": "running"}
        mock_img = io.BytesIO(b"fake image data")
        mock_device.last_image.return_value = mock_img
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_last_img("device1")

        self.assertEqual(result, "/static/tmp/test.jpg")
        mock_device.last_image.assert_called_once()

    def test_get_device_last_img_not_in_use(self):
        """Test getting device last image when device not in use."""
        mock_device = Mock()
        mock_device.info.return_value = {"status": "not_in_use"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_last_img("device1")

        # error_decorator catches exception and returns error dict
        self.assertIn("error", result)
        self.assertIn("not in use", result["error"])

    def test_get_device_last_img_no_image(self):
        """Test getting device last image when no image available."""
        mock_device = Mock()
        mock_device.info.return_value = {"status": "running"}
        mock_device.last_image.return_value = None
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_last_img("device1")

        # error_decorator catches exception and returns error dict
        self.assertIn("error", result)
        self.assertIn("No image", result["error"])

    def test_get_device_dbg_img_success(self):
        """Test getting device debug image successfully."""
        mock_device = Mock()
        mock_img = io.BytesIO(b"fake debug image")
        mock_device.dbg_img.return_value = mock_img
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_dbg_img("device1")

        self.assertEqual(result, "/static/tmp/test.jpg")
        mock_device.dbg_img.assert_called_once()

    @patch("bottle.response")
    def test_get_device_stream(self, mock_response):
        """Test getting device stream."""
        mock_device = Mock()
        mock_device.relay_stream.return_value = "stream_data"
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_stream("device1")

        self.assertEqual(result, "stream_data")
        mock_response.set_header.assert_called_once_with(
            "Content-type", "multipart/x-mixed-replace; boundary=frame"
        )

    @patch("ethoscope_node.backup.helpers.get_device_backup_info")
    def test_get_device_backup_info(self, mock_get_backup_info):
        """Test getting device backup information."""
        mock_device = Mock()
        mock_device.info.return_value = {
            "id": "device1",
            "databases": {"db1": {"status": "active"}},
        }
        self.api.device_scanner.get_device.return_value = mock_device
        mock_get_backup_info.return_value = {
            "total_databases": 1,
            "backed_up": 1,
        }

        result = self.api._get_device_backup_info("device1")

        self.assertEqual(result["total_databases"], 1)
        mock_get_backup_info.assert_called_once_with(
            "device1", {"db1": {"status": "active"}}
        )

    @patch("ethoscope_node.backup.helpers.BackupClass")
    def test_force_device_backup_success(self, mock_backup_class):
        """Test forcing device backup successfully."""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "name": "test"}
        self.api.device_scanner.get_device.return_value = mock_device

        # Mock backup job
        mock_backup_job = Mock()
        mock_backup_job.backup.return_value = [
            json.dumps({"status": "running"}),
            json.dumps({"status": "success"}),
        ]
        mock_backup_class.return_value = mock_backup_job

        result = self.api._force_device_backup("device1")

        self.assertTrue(result["success"])
        mock_backup_class.assert_called_once()

    @patch("ethoscope_node.backup.helpers.BackupClass")
    def test_force_device_backup_failure(self, mock_backup_class):
        """Test forcing device backup with failure."""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "name": "test"}
        self.api.device_scanner.get_device.return_value = mock_device

        # Mock backup job that fails
        mock_backup_job = Mock()
        mock_backup_job.backup.return_value = [
            json.dumps({"status": "running"}),
            json.dumps({"status": "error", "message": "Backup failed"}),
        ]
        mock_backup_class.return_value = mock_backup_job

        result = self.api._force_device_backup("device1")

        self.assertFalse(result["success"])

    @patch("ethoscope_node.backup.helpers.BackupClass")
    def test_force_device_backup_exception(self, mock_backup_class):
        """Test forcing device backup handles exceptions."""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "name": "test"}
        self.api.device_scanner.get_device.return_value = mock_device

        mock_backup_class.side_effect = Exception("Backup error")

        result = self.api._force_device_backup("device1")

        # error_decorator catches and returns error dict
        self.assertIn("error", result)

    def test_device_local_dump(self):
        """Test requesting device to perform local SQL dump."""
        mock_device = Mock()
        mock_device.dump_sql_db.return_value = {"success": True}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._device_local_dump("device1")

        self.assertTrue(result["success"])
        mock_device.dump_sql_db.assert_called_once()

    def test_retire_device(self):
        """Test retiring a device."""
        self.api.device_scanner.retire_device.return_value = {"success": True}

        result = self.api._retire_device("device1")

        self.assertTrue(result["success"])
        self.api.device_scanner.retire_device.assert_called_once_with("device1")

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_post_device_instructions_start(self, mock_get_data):
        """Test posting start instruction to device."""
        post_data = {
            "experimental_info": {"arguments": {"database_to_append": "test.db"}}
        }
        mock_get_data.return_value = json.dumps(post_data).encode("utf-8")

        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "status": "started"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._post_device_instructions("device1", "start")

        self.assertEqual(result["status"], "started")
        # Should send instruction with raw bytes
        mock_device.send_instruction.assert_called_once()
        call_args = mock_device.send_instruction.call_args
        self.assertEqual(call_args[0][0], "start")

    @patch("ethoscope_node.api.device_api.BaseAPI.get_request_data")
    def test_post_device_instructions_stop(self, mock_get_data):
        """Test posting stop instruction to device."""
        mock_get_data.return_value = b""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "status": "stopped"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._post_device_instructions("device1", "stop")

        self.assertEqual(result["status"], "stopped")
        mock_device.send_instruction.assert_called_once_with("stop", b"")

    def test_get_log(self):
        """Test getting device logs."""
        mock_device = Mock()
        mock_device.get_log.return_value = {"log": "device log content"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_log("device1")

        self.assertEqual(result["log"], "device log content")
        mock_device.get_log.assert_called_once()

    def test_get_device_batch_success(self):
        """Test getting batched device data successfully."""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "status": "running"}
        mock_device.machine_info.return_value = {"hardware": "RaspberryPi"}
        mock_device.user_options.return_value = {"option1": "value1"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_batch("device1")

        self.assertEqual(result["data"]["id"], "device1")
        self.assertEqual(result["machineinfo"]["hardware"], "RaspberryPi")
        self.assertEqual(result["user_options"]["option1"], "value1")

    def test_get_device_batch_partial_failure(self):
        """Test getting batched device data with partial failures."""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1"}
        mock_device.machine_info.side_effect = Exception("Network error")
        mock_device.user_options.return_value = {"option1": "value1"}
        self.api.device_scanner.get_device.return_value = mock_device

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._get_device_batch("device1")

            self.assertEqual(result["data"]["id"], "device1")
            self.assertIsNone(result["machineinfo"])  # Failed
            self.assertEqual(result["user_options"]["option1"], "value1")
            # Should log error
            mock_log.assert_called_once()

    def test_get_device_batch_critical_success(self):
        """Test getting critical batched device data."""
        mock_device = Mock()
        mock_device.info.return_value = {"id": "device1", "status": "running"}
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api._get_device_batch_critical("device1")

        self.assertEqual(result["data"]["id"], "device1")
        # Critical endpoint only returns data, not machineinfo or user_options
        self.assertNotIn("machineinfo", result)
        self.assertNotIn("user_options", result)

    def test_get_device_batch_critical_failure(self):
        """Test getting critical batched device data with failure."""
        mock_device = Mock()
        mock_device.info.side_effect = Exception("Device error")
        self.api.device_scanner.get_device.return_value = mock_device

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._get_device_batch_critical("device1")

            self.assertIsNone(result["data"])
            mock_log.assert_called_once()

    def test_cache_img_success(self):
        """Test caching image file successfully."""
        mock_file = io.BytesIO(b"fake image data")
        basename = "test_img.jpg"

        result = self.api._cache_img(mock_file, basename)

        self.assertEqual(result, "/static/tmp/test.jpg")
        # Check that file was created
        expected_path = os.path.join(self.temp_dir, basename)
        self.assertTrue(os.path.exists(expected_path))

    def test_cache_img_no_file(self):
        """Test caching image with no file provided."""
        result = self.api._cache_img(None, "test.jpg")

        self.assertEqual(result, "")

    def test_cache_img_exception(self):
        """Test caching image handles exceptions."""
        mock_file = Mock()
        mock_file.read.side_effect = Exception("Read error")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._cache_img(mock_file, "test.jpg")

            self.assertEqual(result, "")
            mock_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
