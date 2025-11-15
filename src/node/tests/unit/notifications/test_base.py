#!/usr/bin/env python

"""
Unit tests for the notification base analyzer.
"""

import datetime
import json
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from ethoscope_node.notifications.base import NotificationAnalyzer


class TestNotificationAnalyzer:
    """Test cases for NotificationAnalyzer class."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration object."""
        config = Mock()
        config.content = {
            "users": {
                "test_user": {
                    "email": "test@example.com",
                    "isAdmin": False,
                    "active": True,
                },
                "admin_user": {
                    "email": "admin@example.com",
                    "isAdmin": True,
                    "active": True,
                },
            }
        }
        return config

    @pytest.fixture
    def mock_db(self):
        """Mock database object."""
        db = Mock()
        return db

    @pytest.fixture
    def analyzer(self, mock_config, mock_db):
        """Create analyzer instance with mocked dependencies."""
        return NotificationAnalyzer(config=mock_config, db=mock_db)

    def test_init_with_dependencies(self, mock_config, mock_db):
        """Test initialization with provided dependencies."""
        analyzer = NotificationAnalyzer(config=mock_config, db=mock_db)

        assert analyzer.config == mock_config
        assert analyzer.db == mock_db
        assert analyzer.logger is not None

    @patch("ethoscope_node.notifications.base.EthoscopeConfiguration")
    @patch("ethoscope_node.notifications.base.ExperimentalDB")
    def test_init_without_dependencies(self, mock_db_class, mock_config_class):
        """Test initialization without provided dependencies."""
        mock_config_instance = Mock()
        mock_db_instance = Mock()
        mock_config_class.return_value = mock_config_instance
        mock_db_class.return_value = mock_db_instance

        analyzer = NotificationAnalyzer()

        assert analyzer.config == mock_config_instance
        assert analyzer.db == mock_db_instance
        mock_config_class.assert_called_once()
        mock_db_class.assert_called_once()

    def test_analyze_device_failure_success(self, analyzer):
        """Test successful device failure analysis."""
        device_id = "test_device_001"
        current_time = time.time()
        start_time = current_time - 3600  # 1 hour ago

        # Mock device info
        device_info = {
            "ethoscope_name": "Test Ethoscope 001",
            "last_seen": current_time - 60,  # 1 minute ago
            "active": True,
            "problems": "Some device issues",
        }

        # Mock runs data
        runs_data = {
            "run_123": {
                "ethoscope_id": device_id,
                "start_time": start_time,
                "end_time": None,  # Device crashed
                "user_name": "test_user",
                "location": "Incubator_A",
                "run_id": "run_123",
                "problems": "Network timeout",
                "experimental_data": json.dumps({"type": "tracking", "fps": 30}),
            }
        }

        analyzer.db.getEthoscope.return_value = device_info
        analyzer.db.getRun.return_value = runs_data

        result = analyzer.analyze_device_failure(device_id)

        assert result["device_id"] == device_id
        assert result["device_name"] == "Test Ethoscope 001"
        assert result["failure_type"] == "crashed_during_tracking"
        assert result["status"] == "Failed while running"
        assert result["user"] == "test_user"
        assert result["location"] == "Incubator_A"
        assert result["run_id"] == "run_123"
        assert result["problems"] == "Network timeout"
        assert result["experiment_type"] == "tracking"
        assert result["device_active"]
        assert result["device_problems"] == "Some device issues"
        assert "experiment_duration" in result
        assert "experiment_duration_str" in result

        analyzer.db.getEthoscope.assert_called_once_with(device_id, asdict=True)
        analyzer.db.getRun.assert_called_once_with("all", asdict=True)

    def test_analyze_device_failure_device_not_found(self, analyzer):
        """Test device failure analysis when device is not found."""
        device_id = "nonexistent_device"

        analyzer.db.getEthoscope.return_value = None

        result = analyzer.analyze_device_failure(device_id)

        assert result["device_id"] == device_id
        assert result["device_name"] == f"Unknown device {device_id}"
        assert "error" in result
        assert result["error"] == "Device not found in database"

    def test_analyze_device_failure_no_runs(self, analyzer):
        """Test device failure analysis when no runs are found."""
        device_id = "test_device_001"

        device_info = {"ethoscope_name": "Test Ethoscope 001", "last_seen": time.time()}

        analyzer.db.getEthoscope.return_value = device_info
        analyzer.db.getRun.return_value = {}  # No runs

        result = analyzer.analyze_device_failure(device_id)

        assert result["device_id"] == device_id
        assert result["device_name"] == "Test Ethoscope 001"
        assert "error" in result
        assert result["error"] == "No runs found for device"

    def test_analyze_device_failure_completed_experiment(self, analyzer):
        """Test device failure analysis for completed experiment."""
        device_id = "test_device_001"
        current_time = time.time()
        start_time = current_time - 7200  # 2 hours ago
        end_time = current_time - 3600  # 1 hour ago (more than 1 hour ago)

        device_info = {
            "ethoscope_name": "Test Ethoscope 001",
            "last_seen": current_time - 60,
        }

        runs_data = {
            "run_123": {
                "ethoscope_id": device_id,
                "start_time": start_time,
                "end_time": end_time,
                "user_name": "test_user",
                "location": "Incubator_A",
                "run_id": "run_123",
                "experimental_data": "{}",
            }
        }

        analyzer.db.getEthoscope.return_value = device_info
        analyzer.db.getRun.return_value = runs_data

        result = analyzer.analyze_device_failure(device_id)

        assert result["failure_type"] == "completed_normally"
        assert result["status"] == "Completed normally"
        assert result["experiment_duration"] == (end_time - start_time)

    def test_analyze_device_failure_exception(self, analyzer):
        """Test device failure analysis when an exception occurs."""
        device_id = "test_device_001"

        analyzer.db.getEthoscope.side_effect = Exception("Database error")

        result = analyzer.analyze_device_failure(device_id)

        assert result["device_id"] == device_id
        assert result["device_name"] == f"Device {device_id}"
        assert "error" in result
        assert result["error"] == "Database error"

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_get_device_logs_success(self, mock_get, analyzer):
        """Test successful device log retrieval."""
        device_id = "test_device_001"
        log_content = "Log line 1\nLog line 2\nLog line 3"

        # Mock device info - nested structure like getEthoscope returns
        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": "192.168.1.100",
            }
        }

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = log_content
        mock_get.return_value = mock_response

        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_logs(device_id, max_lines=10)

        assert result == log_content
        mock_get.assert_called_once_with(
            f"http://192.168.1.100:9000/data/log/{device_id}", timeout=10
        )

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_get_device_logs_request_failure(self, mock_get, analyzer):
        """Test device log retrieval when HTTP request fails."""
        device_id = "test_device_001"

        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": "192.168.1.100",
            }
        }

        mock_get.side_effect = Exception("Connection timeout")
        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_logs(device_id)

        assert result is None

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_get_device_logs_line_limiting(self, mock_get, analyzer):
        """Test device log retrieval with line limiting."""
        device_id = "test_device_001"
        log_content = "\n".join([f"Line {i}" for i in range(100)])

        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": "192.168.1.100",
            }
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = log_content
        mock_get.return_value = mock_response

        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_logs(device_id, max_lines=5)

        # Should only get last 5 lines
        lines = result.split("\n")
        assert len(lines) == 5
        assert lines[-1] == "Line 99"

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_get_device_status_info_online(self, mock_get, analyzer):
        """Test device status retrieval for online device."""
        device_id = "test_device_001"

        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": "192.168.1.100",
            }
        }

        status_data = {
            "status": "running",
            "monitor_info": {"last_time_stamp": time.time(), "fps": 30},
            "experimental_info": {"run_id": "run_123"},
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = status_data
        mock_get.return_value = mock_response

        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_status_info(device_id)

        assert result["device_id"] == device_id
        assert result["device_name"] == device_info.get("ethoscope_name")
        assert result["online"]
        assert result["status"] == "running"
        assert result["fps"] == 30
        assert "experimental_info" in result

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_get_device_status_info_offline(self, mock_get, analyzer):
        """Test device status retrieval for offline device."""
        device_id = "test_device_001"

        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": "192.168.1.100",
                "last_seen": time.time() - 3600,
                "active": False,
                "problems": "Device offline",
            }
        }

        import requests

        mock_get.side_effect = requests.RequestException("Connection refused")
        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_status_info(device_id)

        assert result["device_id"] == device_id
        assert not result["online"]
        assert result["status"] == "offline"

    def test_format_duration_seconds(self, analyzer):
        """Test duration formatting for seconds."""
        result = analyzer._format_duration(30.5)
        assert result == "30.5 seconds"

    def test_format_duration_minutes(self, analyzer):
        """Test duration formatting for minutes."""
        result = analyzer._format_duration(150)  # 2.5 minutes
        assert result == "2.5 minutes"

    def test_format_duration_hours(self, analyzer):
        """Test duration formatting for hours."""
        result = analyzer._format_duration(7200)  # 2 hours
        assert result == "2.0 hours"

    def test_format_duration_days(self, analyzer):
        """Test duration formatting for days."""
        result = analyzer._format_duration(172800)  # 2 days
        assert result == "2.0 days"

    def test_get_device_users_success(self, analyzer):
        """Test successful device user retrieval."""
        device_id = "test_device_001"

        # Mock getUsersForDevice to return user data with emails
        users_data = [
            {"username": "test_user", "email": "test@example.com"},
            {"username": "another_user", "email": "another@example.com"},
        ]

        analyzer.db.getUsersForDevice.return_value = users_data

        result = analyzer.get_device_users(device_id)

        assert "test@example.com" in result
        assert "another@example.com" in result
        assert len(result) == 2

    def test_get_device_users_no_runs(self, analyzer):
        """Test device user retrieval when no runs exist."""
        device_id = "test_device_001"

        analyzer.db.getUsersForDevice.return_value = []

        result = analyzer.get_device_users(device_id)

        assert result == []

    def test_get_device_users_exception(self, analyzer):
        """Test device user retrieval when exception occurs."""
        device_id = "test_device_001"

        analyzer.db.getUsersForDevice.side_effect = Exception("Database error")

        result = analyzer.get_device_users(device_id)

        assert result == []

    def test_get_admin_emails_success(self, analyzer):
        """Test successful admin email retrieval."""
        # Mock getAllUsers to return admin users
        users_data = {
            "admin_user": {
                "username": "admin_user",
                "email": "admin@example.com",
                "isAdmin": True,
            },
        }

        analyzer.db.getAllUsers.return_value = users_data

        result = analyzer.get_admin_emails()

        assert "admin@example.com" in result
        assert "test@example.com" not in result  # Not an admin
        assert len(result) == 1

    def test_get_admin_emails_no_admins(self, analyzer):
        """Test admin email retrieval when no admins exist."""
        analyzer.db.getAllUsers.return_value = {}

        result = analyzer.get_admin_emails()

        assert result == []

    def test_get_admin_emails_exception(self, analyzer):
        """Test admin email retrieval when exception occurs."""
        analyzer.db.getAllUsers.side_effect = Exception("Database error")

        result = analyzer.get_admin_emails()

        assert result == []

    def test_get_stopped_experiment_user_success(self, analyzer):
        """Test successful stopped experiment user retrieval."""
        run_id = "run_123"

        # Mock getUserByRun to return active user with email
        user_data = {
            "username": "test_user",
            "email": "test@example.com",
            "active": 1,
        }

        analyzer.db.getUserByRun.return_value = user_data

        result = analyzer.get_stopped_experiment_user(run_id)

        assert result == ["test@example.com"]
        analyzer.db.getUserByRun.assert_called_once_with(run_id, asdict=True)

    def test_get_stopped_experiment_user_inactive(self, analyzer):
        """Test stopped experiment user retrieval for inactive user."""
        run_id = "run_123"

        # Mock getUserByRun to return inactive user
        user_data = {
            "username": "test_user",
            "email": "test@example.com",
            "active": 0,
        }

        analyzer.db.getUserByRun.return_value = user_data

        result = analyzer.get_stopped_experiment_user(run_id)

        assert result == []

    def test_get_stopped_experiment_user_no_email(self, analyzer):
        """Test stopped experiment user retrieval when user has no email."""
        run_id = "run_123"

        # Mock getUserByRun to return active user without email
        user_data = {"username": "test_user", "email": None, "active": 1}

        analyzer.db.getUserByRun.return_value = user_data

        result = analyzer.get_stopped_experiment_user(run_id)

        assert result == []

    def test_get_stopped_experiment_user_exception(self, analyzer):
        """Test stopped experiment user retrieval when exception occurs."""
        run_id = "run_123"

        analyzer.db.getUserByRun.side_effect = Exception("Database error")

        result = analyzer.get_stopped_experiment_user(run_id)

        assert result == []

    def test_parse_timestamp_none(self, analyzer):
        """Test timestamp parsing with None value."""
        result = analyzer._parse_timestamp(None)
        assert result == 0

    def test_parse_timestamp_zero_int(self, analyzer):
        """Test timestamp parsing with zero integer."""
        result = analyzer._parse_timestamp(0)
        assert result == 0

    def test_parse_timestamp_zero_float(self, analyzer):
        """Test timestamp parsing with zero float."""
        result = analyzer._parse_timestamp(0.0)
        assert result == 0

    def test_parse_timestamp_zero_string(self, analyzer):
        """Test timestamp parsing with zero string."""
        result = analyzer._parse_timestamp("0")
        assert result == 0

    def test_parse_timestamp_empty_string(self, analyzer):
        """Test timestamp parsing with empty string."""
        result = analyzer._parse_timestamp("")
        assert result == 0

    def test_parse_timestamp_valid_float(self, analyzer):
        """Test timestamp parsing with valid float."""
        timestamp = 1234567890.5
        result = analyzer._parse_timestamp(timestamp)
        assert result == timestamp

    def test_parse_timestamp_valid_int(self, analyzer):
        """Test timestamp parsing with valid integer."""
        timestamp = 1234567890
        result = analyzer._parse_timestamp(timestamp)
        assert result == float(timestamp)

    def test_parse_timestamp_datetime_format1(self, analyzer):
        """Test timestamp parsing with datetime format '%Y-%m-%d %H:%M:%S.%f'."""
        timestamp_str = "2023-01-15 12:34:56.789123"
        result = analyzer._parse_timestamp(timestamp_str)
        expected = datetime.datetime.strptime(
            timestamp_str, "%Y-%m-%d %H:%M:%S.%f"
        ).timestamp()
        assert result == expected

    def test_parse_timestamp_datetime_format2(self, analyzer):
        """Test timestamp parsing with datetime format '%Y-%m-%d %H:%M:%S'."""
        timestamp_str = "2023-01-15 12:34:56"
        result = analyzer._parse_timestamp(timestamp_str)
        expected = datetime.datetime.strptime(
            timestamp_str, "%Y-%m-%d %H:%M:%S"
        ).timestamp()
        assert result == expected

    def test_parse_timestamp_datetime_format3(self, analyzer):
        """Test timestamp parsing with datetime format '%Y-%m-%d_%H-%M-%S'."""
        timestamp_str = "2023-01-15_12-34-56"
        result = analyzer._parse_timestamp(timestamp_str)
        expected = datetime.datetime.strptime(
            timestamp_str, "%Y-%m-%d_%H-%M-%S"
        ).timestamp()
        assert result == expected

    def test_parse_timestamp_datetime_format4(self, analyzer):
        """Test timestamp parsing with datetime format '%Y%m%d_%H%M%S'."""
        timestamp_str = "20230115_123456"
        result = analyzer._parse_timestamp(timestamp_str)
        expected = datetime.datetime.strptime(
            timestamp_str, "%Y%m%d_%H%M%S"
        ).timestamp()
        assert result == expected

    def test_parse_timestamp_string_float(self, analyzer):
        """Test timestamp parsing with string representation of float."""
        timestamp_str = "1234567890.5"
        result = analyzer._parse_timestamp(timestamp_str)
        assert result == 1234567890.5

    def test_parse_timestamp_datetime_object(self, analyzer):
        """Test timestamp parsing with datetime object."""
        dt = datetime.datetime(2023, 1, 15, 12, 34, 56)
        result = analyzer._parse_timestamp(dt)
        assert result == dt.timestamp()

    def test_parse_timestamp_invalid_format(self, analyzer):
        """Test timestamp parsing with invalid format triggers warning."""
        result = analyzer._parse_timestamp("invalid-format")
        assert result == 0

    def test_parse_timestamp_exception(self, analyzer):
        """Test timestamp parsing with exception scenario."""

        # Create an object that will raise exception when accessing timestamp
        class BadTimestamp:
            @property
            def timestamp(self):
                raise ValueError("Cannot convert to timestamp")

        result = analyzer._parse_timestamp(BadTimestamp())
        assert result == 0

    def test_analyze_device_failure_orphaned_sessions(self, analyzer):
        """Test device failure analysis with orphaned running sessions."""
        device_id = "test_device_001"
        current_time = time.time()
        old_start_time = current_time - (25 * 3600)  # 25 hours ago (orphaned)

        device_info = {
            "ethoscope_name": "Test Ethoscope 001",
            "last_seen": current_time - 60,
        }

        # All runs are orphaned (status='running', end_time='0', >24h old)
        runs_data = {
            "run_123": {
                "ethoscope_id": device_id,
                "start_time": old_start_time,
                "end_time": "0",
                "status": "running",
                "user_name": "test_user",
                "run_id": "run_123",
            }
        }

        analyzer.db.getEthoscope.return_value = device_info
        analyzer.db.getRun.return_value = runs_data

        result = analyzer.analyze_device_failure(device_id)

        assert result["device_id"] == device_id
        assert "error" in result
        assert "orphaned" in result["error"].lower()
        assert result["orphaned_count"] == 1

    def test_analyze_device_failure_stopped_recently(self, analyzer):
        """Test device failure analysis for experiment stopped recently."""
        device_id = "test_device_001"
        current_time = time.time()
        start_time = current_time - 1800  # 30 minutes ago
        end_time = current_time - 600  # 10 minutes ago (within last hour)

        device_info = {
            "ethoscope_name": "Test Ethoscope 001",
            "last_seen": current_time - 60,
        }

        runs_data = {
            "run_123": {
                "ethoscope_id": device_id,
                "start_time": start_time,
                "end_time": end_time,
                "user_name": "test_user",
                "location": "Incubator_A",
                "run_id": "run_123",
                "experimental_data": "{}",
            }
        }

        analyzer.db.getEthoscope.return_value = device_info
        analyzer.db.getRun.return_value = runs_data

        result = analyzer.analyze_device_failure(device_id)

        assert result["failure_type"] == "stopped_recently"
        assert result["status"] == "Stopped recently"

    def test_analyze_device_failure_invalid_experimental_data(self, analyzer):
        """Test device failure analysis with invalid JSON in experimental_data."""
        device_id = "test_device_001"
        current_time = time.time()
        start_time = current_time - 3600

        device_info = {
            "ethoscope_name": "Test Ethoscope 001",
            "last_seen": current_time,
        }

        runs_data = {
            "run_123": {
                "ethoscope_id": device_id,
                "start_time": start_time,
                "end_time": None,
                "user_name": "test_user",
                "location": "Incubator_A",
                "run_id": "run_123",
                "experimental_data": "not valid json{",  # Invalid JSON
            }
        }

        analyzer.db.getEthoscope.return_value = device_info
        analyzer.db.getRun.return_value = runs_data

        result = analyzer.analyze_device_failure(device_id)

        # Should handle the invalid JSON gracefully
        assert "experimental_data" in result
        assert result["experimental_data"] == {}
        assert result["experiment_type"] == "tracking"  # Default value

    def test_get_device_logs_device_not_found(self, analyzer):
        """Test device log retrieval when device not found."""
        device_id = "nonexistent_device"

        analyzer.db.getEthoscope.return_value = None

        result = analyzer.get_device_logs(device_id)

        assert result is None

    def test_get_device_logs_no_valid_ip(self, analyzer):
        """Test device log retrieval when device has no valid IP."""
        device_id = "test_device_001"

        # Device info with device_id as IP (invalid scenario)
        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": device_id,  # IP same as device ID (invalid)
            }
        }

        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_logs(device_id)

        assert result is None

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_get_device_logs_request_exception(self, mock_get, analyzer):
        """Test device log retrieval with requests.RequestException."""
        device_id = "test_device_001"

        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": "192.168.1.100",
            }
        }

        import requests

        mock_get.side_effect = requests.RequestException("Network error")
        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_logs(device_id)

        assert result is None

    def test_get_device_status_info_device_not_found(self, analyzer):
        """Test device status retrieval when device not found."""
        device_id = "nonexistent_device"

        analyzer.db.getEthoscope.return_value = None

        result = analyzer.get_device_status_info(device_id)

        assert "error" in result
        assert result["error"] == "Device not found"

    def test_get_device_status_info_no_valid_ip(self, analyzer):
        """Test device status retrieval when device has no valid IP."""
        device_id = "test_device_001"

        # Device info with device_id as IP (invalid scenario)
        device_info = {
            device_id: {
                "ethoscope_name": "Test Ethoscope 001",
                "last_ip": device_id,  # IP same as device ID (invalid)
                "last_seen": time.time() - 3600,
                "active": False,
                "problems": "No valid IP",
            }
        }

        analyzer.db.getEthoscope.return_value = device_info

        result = analyzer.get_device_status_info(device_id)

        assert not result["online"]
        assert result["status"] == "offline"

    def test_get_device_status_info_exception(self, analyzer):
        """Test device status retrieval when exception occurs."""
        device_id = "test_device_001"

        analyzer.db.getEthoscope.side_effect = Exception("Database error")

        result = analyzer.get_device_status_info(device_id)

        assert result["device_id"] == device_id
        assert "error" in result
        assert result["error"] == "Database error"
