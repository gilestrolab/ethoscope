"""
Unit tests for File API endpoints.

Tests file management including browsing, downloading, and file removal.
"""

import datetime
import os
import unittest
from unittest.mock import Mock, call, mock_open, patch

import bottle

from ethoscope_node.api.file_api import FileAPI


class TestFileAPI(unittest.TestCase):
    """Test suite for FileAPI class."""

    def setUp(self):
        """Create mock server instance and FileAPI for testing."""
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

        self.api = FileAPI(self.mock_server)

    def test_register_routes(self):
        """Test that all file management routes are registered."""
        # Track route registrations
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route

        # Register routes
        self.api.register_routes()

        # Verify all 4 routes were registered
        self.assertEqual(len(route_calls), 4)

        # Check specific routes
        paths = [call[0] for call in route_calls]
        self.assertIn("/resultfiles/<type>", paths)
        self.assertIn("/browse/<folder>", paths)
        self.assertIn("/download/<what>", paths)
        self.assertIn("/remove_files", paths)

    @patch("os.walk")
    def test_result_files_all(self, mock_walk):
        """Test getting all result files."""
        # Setup mock file tree
        mock_walk.return_value = [
            ("/tmp/results", [], ["data1.csv", "data2.db", "video.h264"]),
            ("/tmp/results/subfolder", [], ["data3.csv"]),
        ]

        result = self.api._result_files("all")

        # Should return all files with full paths
        self.assertEqual(len(result["files"]), 4)
        self.assertIn("/tmp/results/data1.csv", result["files"])
        self.assertIn("/tmp/results/data2.db", result["files"])
        self.assertIn("/tmp/results/video.h264", result["files"])
        self.assertIn("/tmp/results/subfolder/data3.csv", result["files"])

    @patch("os.walk")
    def test_result_files_by_type(self, mock_walk):
        """Test getting result files filtered by type."""
        mock_walk.return_value = [
            ("/tmp/results", [], ["data1.csv", "data2.db", "video.h264"]),
            ("/tmp/results/subfolder", [], ["data3.csv", "other.txt"]),
        ]

        result = self.api._result_files("csv")

        # Should only return CSV files
        self.assertEqual(len(result["files"]), 2)
        self.assertIn("/tmp/results/data1.csv", result["files"])
        self.assertIn("/tmp/results/subfolder/data3.csv", result["files"])
        # Should not include non-CSV files
        self.assertNotIn("/tmp/results/data2.db", result["files"])
        self.assertNotIn("/tmp/results/video.h264", result["files"])

    @patch("os.walk")
    def test_result_files_no_matches(self, mock_walk):
        """Test getting result files when no files match pattern."""
        mock_walk.return_value = [("/tmp/results", [], ["data.csv", "video.h264"])]

        result = self.api._result_files("txt")

        # Should return empty list
        self.assertEqual(result["files"], [])

    @patch("os.walk")
    def test_result_files_empty_directory(self, mock_walk):
        """Test getting result files from empty directory."""
        mock_walk.return_value = [("/tmp/results", [], [])]

        result = self.api._result_files("all")

        self.assertEqual(result["files"], [])

    @patch("os.walk")
    @patch("os.path.getsize")
    @patch("os.path.getmtime")
    def test_browse_null_folder(self, mock_mtime, mock_getsize, mock_walk):
        """Test browsing with null folder (uses results_dir)."""
        mock_walk.return_value = [("/tmp/results", [], ["file1.csv", "file2.db"])]
        mock_getsize.side_effect = [1000, 2000]
        mock_mtime.side_effect = [1234567890.0, 1234567891.0]

        result = self.api._browse("null")

        # Should use results_dir
        mock_walk.assert_called_once_with("/tmp/results")
        # Should return file metadata
        self.assertEqual(len(result["files"]), 2)
        self.assertIn("file1.csv", result["files"])
        self.assertEqual(result["files"]["file1.csv"]["size"], 1000)
        self.assertEqual(result["files"]["file1.csv"]["mtime"], 1234567890.0)

    @patch("os.walk")
    @patch("os.path.getsize")
    @patch("os.path.getmtime")
    def test_browse_specific_folder(self, mock_mtime, mock_getsize, mock_walk):
        """Test browsing specific folder."""
        mock_walk.return_value = [("/custom/path", [], ["file.txt"])]
        mock_getsize.return_value = 500
        mock_mtime.return_value = 1234567890.0

        result = self.api._browse("custom/path")

        # Should use specified folder with leading slash
        mock_walk.assert_called_once_with("/custom/path")
        self.assertIn("file.txt", result["files"])

    @patch("os.walk")
    @patch("os.path.getsize")
    @patch("os.path.getmtime")
    def test_browse_handles_file_access_errors(
        self, mock_mtime, mock_getsize, mock_walk
    ):
        """Test browse skips files that raise exceptions."""
        mock_walk.return_value = [
            ("/tmp/results", [], ["accessible.csv", "restricted.csv"])
        ]
        # First file accessible, second raises exception
        mock_getsize.side_effect = [1000, PermissionError("Access denied")]
        mock_mtime.side_effect = [1234567890.0, 1234567891.0]

        result = self.api._browse("null")

        # Should only include accessible file
        self.assertEqual(len(result["files"]), 1)
        self.assertIn("accessible.csv", result["files"])
        self.assertNotIn("restricted.csv", result["files"])

    @patch("os.walk")
    def test_browse_empty_directory(self, mock_walk):
        """Test browsing empty directory."""
        mock_walk.return_value = [("/tmp/results", [], [])]

        result = self.api._browse("null")

        self.assertEqual(result["files"], {})

    @patch("bottle.request")
    @patch("datetime.datetime")
    @patch("zipfile.ZipFile")
    def test_download_files_success(self, mock_zipfile, mock_datetime, mock_request):
        """Test creating download archive successfully."""
        # Setup mock request
        mock_request.json = {
            "files": [
                {"url": "/tmp/results/file1.csv"},
                {"url": "/tmp/results/file2.db"},
            ]
        }

        # Setup mock datetime
        mock_now = Mock()
        mock_now.strftime.return_value = "240101_120000"
        mock_datetime.now.return_value = mock_now

        # Setup mock zipfile
        mock_zf = Mock()
        mock_zipfile.return_value.__enter__.return_value = mock_zf

        result = self.api._download("files")

        # Should create zip file with timestamp
        expected_path = "/tmp/results/results_240101_120000.zip"
        self.assertEqual(result["url"], expected_path)
        # Should write both files
        self.assertEqual(mock_zf.write.call_count, 2)
        mock_zf.write.assert_any_call("/tmp/results/file1.csv")
        mock_zf.write.assert_any_call("/tmp/results/file2.db")

    @patch("bottle.request")
    @patch("datetime.datetime")
    @patch("zipfile.ZipFile")
    def test_download_files_with_write_errors(
        self, mock_zipfile, mock_datetime, mock_request
    ):
        """Test download handles file write errors gracefully."""
        mock_request.json = {
            "files": [
                {"url": "/tmp/results/good.csv"},
                {"url": "/tmp/results/bad.csv"},
            ]
        }

        mock_now = Mock()
        mock_now.strftime.return_value = "240101_120000"
        mock_datetime.now.return_value = mock_now

        mock_zf = Mock()
        mock_zf.write.side_effect = [
            None,  # First file succeeds
            OSError("File not found"),  # Second file fails
        ]
        mock_zipfile.return_value.__enter__.return_value = mock_zf

        with patch.object(self.api.logger, "warning") as mock_log:
            result = self.api._download("files")

            # Should still return zip path
            self.assertIn("url", result)
            # Should log warning for failed file
            mock_log.assert_called_once()
            self.assertIn("bad.csv", str(mock_log.call_args))

    @patch("bottle.request")
    def test_download_unsupported_type(self, mock_request):
        """Test download returns error for unsupported types."""
        result = self.api._download("unsupported_type")

        # error_decorator catches NotImplementedError and returns error dict
        self.assertIn("error", result)
        self.assertIn("unsupported_type", result["error"])
        self.assertIn("not supported", result["error"])

    @patch("bottle.request")
    @patch("subprocess.run")
    def test_remove_files_success(self, mock_run, mock_request):
        """Test removing files successfully."""
        mock_request.json = {
            "files": [
                {"url": "/tmp/results/file1.csv"},
                {"url": "/tmp/results/file2.db"},
            ]
        }

        # Mock successful removal
        mock_result = Mock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = self.api._remove_files()

        # Should remove both files
        self.assertEqual(len(result["result"]), 2)
        self.assertIn("/tmp/results/file1.csv", result["result"])
        self.assertIn("/tmp/results/file2.db", result["result"])
        # Should call rm command twice
        self.assertEqual(mock_run.call_count, 2)
        mock_run.assert_any_call(
            ["rm", "/tmp/results/file1.csv"], capture_output=True, text=True
        )

    @patch("bottle.request")
    @patch("subprocess.run")
    def test_remove_files_partial_failure(self, mock_run, mock_request):
        """Test remove files with some failures."""
        mock_request.json = {
            "files": [
                {"url": "/tmp/results/good.csv"},
                {"url": "/tmp/results/bad.csv"},
            ]
        }

        # First succeeds, second fails
        mock_result_success = Mock()
        mock_result_success.returncode = 0
        mock_result_fail = Mock()
        mock_result_fail.returncode = 1
        mock_result_fail.stderr = "No such file"
        mock_run.side_effect = [mock_result_success, mock_result_fail]

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._remove_files()

            # Should only include successfully removed file
            self.assertEqual(len(result["result"]), 1)
            self.assertIn("/tmp/results/good.csv", result["result"])
            self.assertNotIn("/tmp/results/bad.csv", result["result"])
            # Should log error for failed removal
            mock_log.assert_called_once()
            self.assertIn("bad.csv", str(mock_log.call_args))

    @patch("bottle.request")
    @patch("subprocess.run")
    def test_remove_files_exception(self, mock_run, mock_request):
        """Test remove files handles subprocess exceptions."""
        mock_request.json = {"files": [{"url": "/tmp/results/file.csv"}]}

        mock_run.side_effect = Exception("Subprocess error")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._remove_files()

            # Should return empty list
            self.assertEqual(result["result"], [])
            # Should log error
            mock_log.assert_called_once()
            self.assertIn("file.csv", str(mock_log.call_args))


if __name__ == "__main__":
    unittest.main()
