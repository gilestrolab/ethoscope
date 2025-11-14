"""
Unit tests for Sensor API endpoints.

Tests sensor management including discovery, configuration, and data visualization.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import Mock, mock_open, patch

from ethoscope_node.api.sensor_api import SensorAPI


class TestSensorAPI(unittest.TestCase):
    """Test suite for SensorAPI class."""

    def setUp(self):
        """Create mock server instance and SensorAPI for testing."""
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

        self.api = SensorAPI(self.mock_server)

    def test_register_routes(self):
        """Test that all sensor routes are registered."""
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
        self.assertIn("/sensors", paths)
        self.assertIn("/sensor/set", paths)
        self.assertIn("/list_sensor_csv_files", paths)
        self.assertIn("/get_sensor_csv_data/<filename>", paths)

    def test_get_sensors_with_scanner(self):
        """Test getting sensors when scanner is available."""
        mock_sensor_data = {
            "sensor1": {"id": "sensor1", "name": "Temperature Sensor"},
            "sensor2": {"id": "sensor2", "name": "Humidity Sensor"},
        }
        self.api.sensor_scanner.get_all_devices_info.return_value = mock_sensor_data

        result = self.api._get_sensors()

        self.assertEqual(result, mock_sensor_data)
        self.api.sensor_scanner.get_all_devices_info.assert_called_once()

    def test_get_sensors_no_scanner(self):
        """Test getting sensors when scanner is None."""
        self.api.sensor_scanner = None

        result = self.api._get_sensors()

        self.assertEqual(result, {})

    def test_get_sensors_scanner_exception(self):
        """Test get_sensors handles exceptions from scanner."""
        self.api.sensor_scanner.get_all_devices_info.side_effect = RuntimeError(
            "Scanner error"
        )

        result = self.api._get_sensors()

        # error_decorator should catch and return error dict
        self.assertIn("error", result)
        self.assertIn("Scanner error", result["error"])

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_with_valid_json(self, mock_get_data):
        """Test editing sensor with valid JSON data."""
        sensor_data = {"id": "sensor1", "location": "Lab A", "name": "Temp Sensor"}
        mock_get_data.return_value = json.dumps(sensor_data).encode("utf-8")

        mock_sensor = Mock()
        mock_sensor.set.return_value = {"success": True}
        self.api.sensor_scanner.get_device.return_value = mock_sensor

        result = self.api._edit_sensor()

        self.assertEqual(result, {"success": True})
        self.api.sensor_scanner.get_device.assert_called_once_with("sensor1")
        mock_sensor.set.assert_called_once_with(
            {"location": "Lab A", "sensor_name": "Temp Sensor"}
        )

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_with_eval_fallback(self, mock_get_data):
        """Test editing sensor falls back to eval for non-JSON."""
        # Python dict string (not valid JSON)
        sensor_data = "{'id': 'sensor1', 'location': 'Lab B', 'name': 'Sensor'}"
        mock_get_data.return_value = sensor_data.encode("utf-8")

        mock_sensor = Mock()
        mock_sensor.set.return_value = {"success": True}
        self.api.sensor_scanner.get_device.return_value = mock_sensor

        result = self.api._edit_sensor()

        self.assertEqual(result, {"success": True})
        mock_sensor.set.assert_called_once()

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_invalid_data_format(self, mock_get_data):
        """Test editing sensor with invalid data format."""
        mock_get_data.return_value = b"not valid json or python"

        result = self.api._edit_sensor()

        self.assertEqual(result, {"error": "Invalid data format"})

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_no_scanner(self, mock_get_data):
        """Test editing sensor when scanner is None."""
        sensor_data = {"id": "sensor1", "location": "Lab A", "name": "Sensor"}
        mock_get_data.return_value = json.dumps(sensor_data).encode("utf-8")

        self.api.sensor_scanner = None

        result = self.api._edit_sensor()

        self.assertEqual(result, {"error": "Sensor not found"})

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_not_found(self, mock_get_data):
        """Test editing sensor when sensor doesn't exist."""
        sensor_data = {"id": "nonexistent", "location": "Lab A", "name": "Sensor"}
        mock_get_data.return_value = json.dumps(sensor_data).encode("utf-8")

        self.api.sensor_scanner.get_device.return_value = None

        result = self.api._edit_sensor()

        self.assertEqual(result, {"error": "Sensor not found"})

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_set_exception(self, mock_get_data):
        """Test editing sensor when set() raises exception."""
        sensor_data = {"id": "sensor1", "location": "Lab A", "name": "Sensor"}
        mock_get_data.return_value = json.dumps(sensor_data).encode("utf-8")

        mock_sensor = Mock()
        mock_sensor.set.side_effect = RuntimeError("Connection failed")
        self.api.sensor_scanner.get_device.return_value = mock_sensor

        result = self.api._edit_sensor()

        self.assertIn("error", result)
        self.assertIn("Connection failed", result["error"])

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_list_csv_files_success(self, mock_listdir, mock_exists):
        """Test listing CSV files successfully."""
        mock_exists.return_value = True
        mock_listdir.return_value = [
            "sensor1.csv",
            "sensor2.csv",
            "data.txt",
            "sensor3.csv",
        ]

        result = self.api._list_csv_files()

        self.assertEqual(
            result, {"files": ["sensor1.csv", "sensor2.csv", "sensor3.csv"]}
        )
        mock_exists.assert_called_once_with("/ethoscope_data/sensors/")
        mock_listdir.assert_called_once_with("/ethoscope_data/sensors/")

    @patch("os.path.exists")
    def test_list_csv_files_directory_not_exists(self, mock_exists):
        """Test listing CSV files when directory doesn't exist."""
        mock_exists.return_value = False

        result = self.api._list_csv_files()

        self.assertEqual(result, {"files": []})

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_list_csv_files_no_csv_files(self, mock_listdir, mock_exists):
        """Test listing CSV files when no CSV files exist."""
        mock_exists.return_value = True
        mock_listdir.return_value = ["data.txt", "info.json"]

        result = self.api._list_csv_files()

        self.assertEqual(result, {"files": []})

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_list_csv_files_exception(self, mock_listdir, mock_exists):
        """Test listing CSV files when exception occurs."""
        mock_exists.return_value = True
        mock_listdir.side_effect = PermissionError("Access denied")

        result = self.api._list_csv_files()

        # error_decorator catches exception, returns empty list
        self.assertEqual(result, {"files": []})

    def test_get_csv_data_success(self):
        """Test reading CSV data successfully."""
        csv_content = (
            "timestamp,temperature,humidity\n2024-01-01,22.5,45\n2024-01-02,23.0,46\n"
        )

        with patch("builtins.open", mock_open(read_data=csv_content)):
            result = self.api._get_csv_data("sensor1.csv")

        self.assertEqual(result["headers"], ["timestamp", "temperature", "humidity"])
        self.assertEqual(len(result["data"]), 2)
        self.assertEqual(result["data"][0], ["2024-01-01", "22.5", "45"])
        self.assertEqual(result["data"][1], ["2024-01-02", "23.0", "46"])

    def test_get_csv_data_empty_file(self):
        """Test reading empty CSV file."""
        csv_content = "timestamp,temperature,humidity\n"

        with patch("builtins.open", mock_open(read_data=csv_content)):
            result = self.api._get_csv_data("empty.csv")

        self.assertEqual(result["headers"], ["timestamp", "temperature", "humidity"])
        self.assertEqual(result["data"], [])

    def test_get_csv_data_file_not_found(self):
        """Test reading CSV when file doesn't exist."""
        with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
            result = self.api._get_csv_data("nonexistent.csv")

        # error_decorator should catch and return error dict
        self.assertIn("error", result)

    def test_get_csv_data_permission_error(self):
        """Test reading CSV when permission denied."""
        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            result = self.api._get_csv_data("protected.csv")

        # error_decorator should catch and return error dict
        self.assertIn("error", result)

    def test_get_csv_data_malformed_csv(self):
        """Test reading malformed CSV data."""
        csv_content = (
            "timestamp,temperature\n2024-01-01,22.5\nmalformed line\n2024-01-02,23.0\n"
        )

        with patch("builtins.open", mock_open(read_data=csv_content)):
            result = self.api._get_csv_data("malformed.csv")

        # Should still parse, but malformed line is included
        self.assertEqual(result["headers"], ["timestamp", "temperature"])
        self.assertEqual(len(result["data"]), 3)
        self.assertEqual(result["data"][1], ["malformed line"])

    def test_get_csv_data_with_whitespace(self):
        """Test reading CSV with extra whitespace."""
        csv_content = (
            "  timestamp  ,  temp  ,  humid  \n  2024-01-01  ,  22.5  ,  45  \n"
        )

        with patch("builtins.open", mock_open(read_data=csv_content)):
            result = self.api._get_csv_data("whitespace.csv")

        # strip() removes leading/trailing whitespace from entire line
        # First element loses leading spaces, last element loses trailing spaces
        # Middle elements keep internal spaces after commas
        self.assertEqual(result["headers"], ["timestamp  ", "  temp  ", "  humid"])
        self.assertEqual(result["data"][0], ["2024-01-01  ", "  22.5  ", "  45"])

    @patch("ethoscope_node.api.sensor_api.SensorAPI.get_request_data")
    def test_edit_sensor_missing_fields(self, mock_get_data):
        """Test editing sensor with missing required fields."""
        sensor_data = {"id": "sensor1"}  # Missing location and name
        mock_get_data.return_value = json.dumps(sensor_data).encode("utf-8")

        mock_sensor = Mock()
        self.api.sensor_scanner.get_device.return_value = mock_sensor

        # Should raise KeyError which gets caught
        result = self.api._edit_sensor()

        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
