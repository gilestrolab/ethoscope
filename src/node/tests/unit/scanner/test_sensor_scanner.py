"""
Unit tests for sensor_scanner module.

This module tests Sensor-specific scanner functionality including
CSV data logging, sensor data retrieval, and remote configuration.
"""

import csv
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from unittest.mock import MagicMock, Mock, patch

import pytest

from ethoscope_node.scanner.sensor_scanner import Sensor, SensorScanner


class TestSensor:
    """Test Sensor device class."""

    def test_initialization_with_csv(self):
        """Test Sensor initialization with CSV saving enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor(
                "192.168.1.200", port=80, results_dir=tmpdir, save_to_csv=True
            )
            assert sensor._ip == "192.168.1.200"
            assert sensor._port == 80
            assert sensor.save_to_csv is True
            assert sensor.CSV_PATH == tmpdir
            assert os.path.exists(tmpdir)

    def test_initialization_without_csv(self):
        """Test Sensor initialization without CSV saving."""
        sensor = Sensor("192.168.1.200", save_to_csv=False)
        assert sensor.save_to_csv is False

    def test_url_setup(self):
        """Test sensor-specific URL setup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor(
                "192.168.1.200", port=80, results_dir=tmpdir, save_to_csv=False
            )
            assert sensor._data_url == "http://192.168.1.200:80/"
            assert sensor._id_url == "http://192.168.1.200:80/id"
            assert sensor._post_url == "http://192.168.1.200:80/set"

    def test_sensor_fields_constant(self):
        """Test SENSOR_FIELDS constant."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=False)
            assert "Time" in sensor.SENSOR_FIELDS
            assert "Temperature" in sensor.SENSOR_FIELDS
            assert "Humidity" in sensor.SENSOR_FIELDS
            assert "Pressure" in sensor.SENSOR_FIELDS
            assert "Light" in sensor.SENSOR_FIELDS

    @patch("urllib.request.urlopen")
    def test_set_with_json(self, mock_urlopen):
        """Test setting sensor variables with JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=False)

            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response
            mock_response.read.return_value = json.dumps({"status": "ok"}).encode()
            mock_urlopen.return_value = mock_response

            with patch.object(sensor, "_update_info"):
                result = sensor.set({"key": "value"}, use_json=True)
                assert result == {"status": "ok"}

    @patch("urllib.request.urlopen")
    def test_set_without_json(self, mock_urlopen):
        """Test setting sensor variables without JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=False)

            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response
            mock_response.read.return_value = b"OK"
            mock_urlopen.return_value = mock_response

            with patch.object(sensor, "_update_info"):
                result = sensor.set({"key": "value"}, use_json=False)
                assert result == b"OK"

    @patch("urllib.request.urlopen")
    def test_set_error_handling(self, mock_urlopen):
        """Test error handling in set method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=False)

            mock_urlopen.side_effect = Exception("Connection error")

            with pytest.raises(Exception, match="Connection error"):
                sensor.set({"key": "value"})

    def test_extract_sensor_data(self):
        """Test sensor data extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=False)
            sensor._info = {
                "id": "sensor_001",
                "ip": "192.168.1.200",
                "name": "Test Sensor",
                "location": "Lab 1",
                "temperature": 22.5,
                "humidity": 45.2,
                "pressure": 1013.25,
                "light": 500,
            }

            data = sensor._extract_sensor_data()

            assert data["id"] == "sensor_001"
            assert data["name"] == "Test Sensor"
            assert data["temperature"] == 22.5
            assert data["humidity"] == 45.2
            assert data["pressure"] == 1013.25
            assert data["light"] == 500

    def test_extract_sensor_data_with_defaults(self):
        """Test sensor data extraction with missing fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=False)
            sensor._info = {}

            data = sensor._extract_sensor_data()

            assert data["id"] == "unknown_id"
            assert data["name"] == "unknown_sensor"
            assert data["temperature"] == "N/A"
            assert data["humidity"] == "N/A"

    def test_get_csv_filename(self):
        """Test CSV filename generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir)

            filename = sensor._get_csv_filename("Test Sensor 123")
            assert filename == os.path.join(tmpdir, "TestSensor123.csv")

    def test_get_csv_filename_special_chars(self):
        """Test CSV filename generation with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir)

            filename = sensor._get_csv_filename("Sensor@#$%^&*()[]{}|;:'\"<>?/\\")
            # Should only keep alphanumeric and _-
            assert "Sensor" in filename
            assert "@" not in filename
            assert "#" not in filename

    def test_write_csv_header(self):
        """Test CSV header writing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir)

            test_file = os.path.join(tmpdir, "test.csv")
            sensor_data = {
                "id": "sensor_001",
                "ip": "192.168.1.200",
                "name": "Test Sensor",
                "location": "Lab 1",
            }

            with open(test_file, "w") as f:
                sensor._write_csv_header(f, sensor_data)

            with open(test_file) as f:
                content = f.read()
                assert "# Sensor ID: sensor_001" in content
                assert "# IP: 192.168.1.200" in content
                assert "# Name: Test Sensor" in content
                assert "# Location: Lab 1" in content

    @patch("urllib.request.urlopen")
    def test_save_to_csv_new_file(self, mock_urlopen):
        """Test saving sensor data to new CSV file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=True)
            sensor._id = "sensor_001"
            sensor._info = {
                "id": "sensor_001",
                "ip": "192.168.1.200",
                "name": "Test_Sensor",
                "location": "Lab 1",
                "temperature": 22.5,
                "humidity": 45.2,
                "pressure": 1013.25,
                "light": 500,
            }

            sensor._save_to_csv()

            csv_file = os.path.join(tmpdir, "Test_Sensor.csv")
            assert os.path.exists(csv_file)

            with open(csv_file) as f:
                content = f.read()
                assert "# Sensor ID: sensor_001" in content
                assert "Temperature" in content
                assert "22.5" in content

    @patch("urllib.request.urlopen")
    def test_save_to_csv_append_existing(self, mock_urlopen):
        """Test appending sensor data to existing CSV file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=True)
            sensor._id = "sensor_001"
            sensor._info = {
                "id": "sensor_001",
                "ip": "192.168.1.200",
                "name": "Test_Sensor",
                "location": "Lab 1",
                "temperature": 22.5,
                "humidity": 45.2,
                "pressure": 1013.25,
                "light": 500,
            }

            # Save first time
            sensor._save_to_csv()

            # Change data and save again
            sensor._info["temperature"] = 23.0
            sensor._save_to_csv()

            csv_file = os.path.join(tmpdir, "Test_Sensor.csv")

            # Count data rows (excluding header lines)
            with open(csv_file) as f:
                lines = [line for line in f if not line.startswith("#")]

            reader = csv.reader(lines)
            data_rows = [row for row in reader if row and row[0] != "Time"]
            assert len(data_rows) == 2

    def test_save_to_csv_error_handling(self):
        """Test error handling in CSV saving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=True)
            sensor._info = {"id": "sensor_001", "name": "Test"}

            # Create a file at the location where CSV would be written
            csv_path = sensor._get_csv_filename("Test")
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)

            # Make directory read-only to cause permission error during write
            with patch(
                "builtins.open", side_effect=PermissionError("No write permission")
            ):
                # Should not raise exception, just log error
                sensor._save_to_csv()

    @patch("urllib.request.urlopen")
    def test_update_info_success(self, mock_urlopen):
        """Test successful sensor info update."""
        sensor = Sensor("192.168.1.200", save_to_csv=False)

        # Mock ID response
        id_response = MagicMock()
        id_response.__enter__.return_value = id_response
        id_response.read.return_value = json.dumps({"id": "sensor_001"}).encode()

        # Mock data response
        data_response = MagicMock()
        data_response.__enter__.return_value = data_response
        data_response.read.return_value = json.dumps(
            {"temperature": 22.5, "humidity": 45.2}
        ).encode()

        mock_urlopen.side_effect = [id_response, data_response]

        sensor._update_info()

        assert sensor._info["temperature"] == 22.5
        assert sensor._info["humidity"] == 45.2
        assert sensor._device_status.status_name == "online"

    @patch("urllib.request.urlopen")
    def test_update_info_with_csv_saving(self, mock_urlopen):
        """Test sensor info update with CSV saving."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sensor = Sensor("192.168.1.200", results_dir=tmpdir, save_to_csv=True)

            # Mock responses
            id_response = MagicMock()
            id_response.__enter__.return_value = id_response
            id_response.read.return_value = json.dumps({"id": "sensor_001"}).encode()

            data_response = MagicMock()
            data_response.__enter__.return_value = data_response
            data_response.read.return_value = json.dumps(
                {
                    "id": "sensor_001",
                    "name": "Test_Sensor",
                    "temperature": 22.5,
                    "humidity": 45.2,
                    "pressure": 1013.25,
                    "light": 500,
                }
            ).encode()

            mock_urlopen.side_effect = [id_response, data_response]

            sensor._update_info()

            csv_file = os.path.join(tmpdir, "Test_Sensor.csv")
            assert os.path.exists(csv_file)


class TestSensorScanner:
    """Test SensorScanner class."""

    def test_initialization(self):
        """Test SensorScanner initialization."""
        scanner = SensorScanner(results_dir="/tmp/sensors", device_refresh_period=300)

        assert scanner.results_dir == "/tmp/sensors"
        assert scanner.device_refresh_period == 300
        assert scanner._device_class == Sensor

    def test_service_type(self):
        """Test service type constant."""
        scanner = SensorScanner()
        assert scanner.SERVICE_TYPE == "_sensor._tcp.local."
        assert scanner.DEVICE_TYPE == "sensor"

    def test_default_refresh_period(self):
        """Test default refresh period for sensors."""
        scanner = SensorScanner()
        # Sensors should have longer refresh period (300s)
        assert scanner.device_refresh_period == 300
