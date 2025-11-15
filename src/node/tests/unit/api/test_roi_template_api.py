"""
Unit tests for ROI Template API endpoints.

Tests ROI template management including listing, uploading, and deployment
to devices.
"""

import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, mock_open, patch

import bottle

from ethoscope_node.api.roi_template_api import ROITemplateAPI


class TestROITemplateAPI(unittest.TestCase):
    """Test suite for ROITemplateAPI class."""

    def setUp(self):
        """Create mock server instance and ROITemplateAPI for testing."""
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

        self.api = ROITemplateAPI(self.mock_server)

    def test_register_routes(self):
        """Test that all ROI template routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 4 routes
        self.assertEqual(len(route_calls), 4)

        paths = [call[0] for call in route_calls]
        self.assertIn("/roi_templates", paths)
        self.assertIn("/roi_template/<template_name>", paths)
        self.assertIn("/upload_roi_template", paths)
        self.assertIn("/device/<id>/upload_template", paths)

    @patch("os.makedirs")
    @patch("os.listdir")
    @patch("os.path.exists")
    def test_list_roi_templates_builtin_and_custom(
        self, mock_exists, mock_listdir, mock_makedirs
    ):
        """Test listing both builtin and custom templates."""
        # Mock directory existence
        mock_exists.return_value = True

        # Mock directory listings
        def listdir_side_effect(path):
            if "builtin" in path:
                return ["builtin_template.json", "other_file.txt"]
            else:
                return ["custom_template.json"]

        mock_listdir.side_effect = listdir_side_effect

        # Mock template parsing
        with patch.object(self.api, "_parse_template_file") as mock_parse:
            mock_parse.side_effect = [
                {
                    "value": "builtin_template",
                    "text": "Builtin Template",
                    "type": "builtin",
                },
                {
                    "value": "custom_template",
                    "text": "Custom Template",
                    "type": "custom",
                },
            ]

            result = self.api._list_roi_templates()

            self.assertEqual(len(result["templates"]), 2)
            # Should be sorted by text
            self.assertEqual(result["templates"][0]["text"], "Builtin Template")
            self.assertEqual(result["templates"][1]["text"], "Custom Template")

    @patch("os.makedirs")
    @patch("os.listdir")
    @patch("os.path.exists")
    def test_list_roi_templates_no_builtin_dir(
        self, mock_exists, mock_listdir, mock_makedirs
    ):
        """Test listing templates when builtin directory doesn't exist."""

        def exists_side_effect(path):
            return "builtin" not in path

        mock_exists.side_effect = exists_side_effect
        mock_listdir.return_value = ["custom_template.json"]

        with patch.object(self.api, "_parse_template_file") as mock_parse:
            mock_parse.return_value = {
                "value": "custom_template",
                "text": "Custom Template",
                "type": "custom",
            }

            result = self.api._list_roi_templates()

            self.assertEqual(len(result["templates"]), 1)
            self.assertEqual(result["templates"][0]["type"], "custom")

    @patch("os.makedirs")
    @patch("os.listdir")
    @patch("os.path.exists")
    def test_list_roi_templates_filters_non_json(
        self, mock_exists, mock_listdir, mock_makedirs
    ):
        """Test that non-JSON files are filtered out."""
        mock_exists.return_value = True
        mock_listdir.return_value = [
            "template1.json",
            "readme.txt",
            "template2.json",
            "script.py",
        ]

        with patch.object(self.api, "_parse_template_file") as mock_parse:
            mock_parse.return_value = {"value": "template", "text": "Template"}

            result = self.api._list_roi_templates()

            # Should only parse .json files (2 calls for builtin dir, 2 for custom dir)
            self.assertEqual(mock_parse.call_count, 4)
            self.assertIn("templates", result)

    @patch("os.makedirs")
    @patch("os.listdir")
    @patch("os.path.exists")
    def test_list_roi_templates_handles_parse_errors(
        self, mock_exists, mock_listdir, mock_makedirs
    ):
        """Test that parsing errors don't break template listing."""
        mock_exists.return_value = True
        mock_listdir.return_value = ["good.json", "bad.json"]

        with patch.object(self.api, "_parse_template_file") as mock_parse:
            # First returns valid template, second returns None (parse error)
            mock_parse.side_effect = [
                {"value": "good", "text": "Good Template"},
                None,
            ]

            result = self.api._list_roi_templates()

            # Should only include the successfully parsed template
            self.assertEqual(len(result["templates"]), 1)
            self.assertEqual(result["templates"][0]["value"], "good")

    @patch("os.makedirs")
    @patch("os.listdir")
    @patch("os.path.exists")
    def test_list_roi_templates_exception(
        self, mock_exists, mock_listdir, mock_makedirs
    ):
        """Test that exceptions in listing are handled gracefully."""
        mock_exists.return_value = True
        mock_listdir.side_effect = PermissionError("Access denied")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._list_roi_templates()

            # Should return empty list on error
            self.assertEqual(result["templates"], [])
            mock_log.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    def test_parse_template_file_success(self, mock_file):
        """Test parsing a valid template file."""
        template_data = {
            "template_info": {
                "id": "template123",
                "name": "Test Template",
                "description": "A test template",
                "default": True,
            },
            "roi_definition": {"rows": 1, "cols": 1},
        }
        file_content = json.dumps(template_data)
        mock_file.return_value.read.return_value = file_content

        result = self.api._parse_template_file("/path/to/test_template.json", "builtin")

        self.assertEqual(result["value"], "test_template")
        self.assertEqual(result["text"], "Test Template")
        self.assertEqual(result["description"], "A test template")
        self.assertEqual(result["filename"], "test_template.json")
        self.assertEqual(result["id"], "template123")
        self.assertEqual(result["type"], "builtin")
        self.assertTrue(result["is_default"])
        # Check MD5 is calculated
        expected_md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
        self.assertEqual(result["md5"], expected_md5)

    @patch("builtins.open", new_callable=mock_open)
    def test_parse_template_file_minimal_info(self, mock_file):
        """Test parsing template with minimal info."""
        template_data = {"template_info": {}, "roi_definition": {}}
        file_content = json.dumps(template_data)
        mock_file.return_value.read.return_value = file_content

        result = self.api._parse_template_file("/path/to/minimal.json", "custom")

        # Should use filename as fallback for name
        self.assertEqual(result["value"], "minimal")
        self.assertEqual(result["text"], "minimal")
        self.assertEqual(result["description"], "")
        self.assertFalse(result["is_default"])
        # Should generate ID from MD5 when not provided
        expected_md5 = hashlib.md5(file_content.encode("utf-8")).hexdigest()
        self.assertEqual(result["id"], expected_md5)

    @patch("builtins.open")
    def test_parse_template_file_invalid_json(self, mock_file):
        """Test parsing a file with invalid JSON."""
        mock_file.side_effect = json.JSONDecodeError("Invalid", "doc", 0)

        with patch.object(self.api.logger, "warning") as mock_log:
            result = self.api._parse_template_file("/path/to/bad.json", "builtin")

            self.assertIsNone(result)
            mock_log.assert_called_once()

    @patch("builtins.open")
    def test_parse_template_file_file_not_found(self, mock_file):
        """Test parsing a non-existent file."""
        mock_file.side_effect = FileNotFoundError("File not found")

        with patch.object(self.api.logger, "warning") as mock_log:
            result = self.api._parse_template_file("/path/to/missing.json", "builtin")

            self.assertIsNone(result)
            mock_log.assert_called_once()

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_get_roi_template_from_builtin(self, mock_exists, mock_file):
        """Test getting template from builtin directory."""
        template_data = {"template_info": {}, "roi_definition": {"rows": 2}}

        def exists_side_effect(path):
            return "builtin" in path

        mock_exists.side_effect = exists_side_effect
        mock_file.return_value.read.return_value = json.dumps(template_data)

        result = self.api._get_roi_template("test_template")

        self.assertEqual(result, template_data)

    @patch("builtins.open", new_callable=mock_open)
    @patch("os.path.exists")
    def test_get_roi_template_from_custom(self, mock_exists, mock_file):
        """Test getting template from custom directory."""
        template_data = {"template_info": {}, "roi_definition": {"rows": 3}}

        def exists_side_effect(path):
            # Builtin doesn't exist, custom does
            return "builtin" not in path

        mock_exists.side_effect = exists_side_effect
        mock_file.return_value.read.return_value = json.dumps(template_data)

        result = self.api._get_roi_template("custom_template")

        self.assertEqual(result, template_data)

    @patch("os.path.exists")
    def test_get_roi_template_not_found(self, mock_exists):
        """Test getting non-existent template."""
        mock_exists.return_value = False

        result = self.api._get_roi_template("nonexistent")

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    @patch("builtins.open")
    @patch("os.path.exists")
    def test_get_roi_template_read_error_builtin(self, mock_exists, mock_file):
        """Test handling file read errors in builtin directory."""
        mock_exists.return_value = True
        mock_file.side_effect = OSError("Read error")

        result = self.api._get_roi_template("bad_template")

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("Error loading builtin template", result["error"])

    @patch("builtins.open")
    @patch("os.path.exists")
    def test_get_roi_template_read_error_custom(self, mock_exists, mock_file):
        """Test handling file read errors in custom directory."""

        def exists_side_effect(path):
            # Builtin doesn't exist, custom does
            return "builtin" not in path

        mock_exists.side_effect = exists_side_effect
        mock_file.side_effect = OSError("Read error")

        result = self.api._get_roi_template("bad_custom_template")

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("Error loading custom template", result["error"])

    @patch("os.remove")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("bottle.request")
    def test_upload_roi_template_success(
        self, mock_request, mock_file, mock_makedirs, mock_remove
    ):
        """Test successful template upload."""
        # Mock file upload
        mock_upload = Mock()
        mock_upload.filename = "new_template.json"
        mock_upload.save = Mock()
        mock_request.files.get.return_value = mock_upload

        # Mock valid template content
        template_data = {
            "template_info": {"name": "New Template"},
            "roi_definition": {"rows": 1},
        }
        mock_file.return_value.read.return_value = json.dumps(template_data)

        result = self.api._upload_roi_template()

        self.assertTrue(result["success"])
        self.assertEqual(result["filename"], "new_template.json")
        mock_upload.save.assert_called_once()
        mock_makedirs.assert_called_once()

    @patch("bottle.request")
    def test_upload_roi_template_no_file(self, mock_request):
        """Test upload with no file provided."""
        mock_request.files.get.return_value = None

        result = self.api._upload_roi_template()

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("No template file", result["error"])

    @patch("bottle.request")
    def test_upload_roi_template_wrong_extension(self, mock_request):
        """Test upload with non-JSON file."""
        mock_upload = Mock()
        mock_upload.filename = "template.txt"
        mock_request.files.get.return_value = mock_upload

        result = self.api._upload_roi_template()

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("must be a JSON file", result["error"])

    @patch("os.remove")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    @patch("bottle.request")
    def test_upload_roi_template_invalid_format(
        self, mock_request, mock_file, mock_makedirs, mock_remove
    ):
        """Test upload with invalid template format."""
        mock_upload = Mock()
        mock_upload.filename = "invalid.json"
        mock_upload.save = Mock()
        mock_request.files.get.return_value = mock_upload

        # Mock invalid template (missing required fields)
        mock_file.return_value.read.return_value = json.dumps({"bad": "data"})

        result = self.api._upload_roi_template()

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("Invalid template format", result["error"])
        # Should remove invalid file
        mock_remove.assert_called_once()

    @patch("os.path.exists")
    @patch("os.remove")
    @patch("os.makedirs")
    @patch("bottle.request")
    def test_upload_roi_template_save_error(
        self, mock_request, mock_makedirs, mock_remove, mock_exists
    ):
        """Test handling save errors."""
        mock_upload = Mock()
        mock_upload.filename = "template.json"
        mock_upload.save.side_effect = OSError("Save failed")
        mock_request.files.get.return_value = mock_upload
        mock_exists.return_value = True

        result = self.api._upload_roi_template()

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("Error saving template", result["error"])
        # Should cleanup on error
        mock_remove.assert_called_once()

    @patch("requests.post")
    @patch("bottle.request")
    def test_upload_template_to_device_success(self, mock_bottle_request, mock_post):
        """Test uploading template to device successfully."""
        # Mock request JSON
        mock_bottle_request.json = {"template_name": "test_template"}

        # Mock template retrieval
        template_data = {"template_info": {}, "roi_definition": {}}
        with patch.object(self.api, "_get_roi_template", return_value=template_data):
            # Mock device
            mock_device = Mock()
            mock_device.ip.return_value = "192.168.1.100"
            mock_device._port = 9000
            self.api.device_scanner.get_device.return_value = mock_device

            # Mock successful HTTP response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            result = self.api._upload_template_to_device("device1")

            self.assertTrue(result["success"])
            self.assertIn("uploaded to device", result["message"])
            # Verify requests.post was called correctly
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            self.assertIn("http://192.168.1.100:9000/upload/device1", call_args[0])

    @patch("bottle.request")
    def test_upload_template_to_device_no_template_name(self, mock_request):
        """Test upload to device without template name."""
        mock_request.json = {}

        result = self.api._upload_template_to_device("device1")

        # error_decorator catches abort and returns error dict
        self.assertIn("error", result)
        self.assertIn("Template name required", result["error"])

    @patch("requests.post")
    @patch("bottle.request")
    def test_upload_template_to_device_http_error(self, mock_bottle_request, mock_post):
        """Test handling HTTP error when uploading to device."""
        mock_bottle_request.json = {"template_name": "test_template"}

        template_data = {"template_info": {}, "roi_definition": {}}
        with patch.object(self.api, "_get_roi_template", return_value=template_data):
            mock_device = Mock()
            mock_device.ip.return_value = "192.168.1.100"
            mock_device._port = 9000
            self.api.device_scanner.get_device.return_value = mock_device

            # Mock failed HTTP response
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            result = self.api._upload_template_to_device("device1")

            # error_decorator catches abort and returns error dict
            self.assertIn("error", result)
            self.assertIn("Device upload failed", result["error"])

    @patch("bottle.request")
    def test_upload_template_to_device_exception(self, mock_request):
        """Test handling exceptions during device upload."""
        mock_request.json = {"template_name": "test_template"}

        with patch.object(
            self.api, "_get_roi_template", side_effect=Exception("Template error")
        ):
            result = self.api._upload_template_to_device("device1")

            # error_decorator catches abort and returns error dict
            self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
