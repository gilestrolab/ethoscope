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
        assert result["device_active"] == True
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
        assert result["online"] == True
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
        assert result["online"] == False
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

        runs_data = {
            "run_123": {"ethoscope_id": device_id, "user_name": "test_user"},
            "run_456": {"ethoscope_id": device_id, "user_name": "another_user"},
            "run_789": {"ethoscope_id": "other_device", "user_name": "test_user"},
        }

        analyzer.db.getRun.return_value = runs_data

        result = analyzer.get_device_users(device_id)

        assert "test@example.com" in result
        # another_user doesn't exist in config, so shouldn't be in result
        assert len(result) == 1

    def test_get_device_users_no_runs(self, analyzer):
        """Test device user retrieval when no runs exist."""
        device_id = "test_device_001"

        analyzer.db.getRun.return_value = {}

        result = analyzer.get_device_users(device_id)

        assert result == []

    def test_get_device_users_exception(self, analyzer):
        """Test device user retrieval when exception occurs."""
        device_id = "test_device_001"

        analyzer.db.getRun.side_effect = Exception("Database error")

        result = analyzer.get_device_users(device_id)

        assert result == []

    def test_get_admin_emails_success(self, analyzer):
        """Test successful admin email retrieval."""
        result = analyzer.get_admin_emails()

        assert "admin@example.com" in result
        assert "test@example.com" not in result  # Not an admin
        assert len(result) == 1

    def test_get_admin_emails_no_admins(self, analyzer):
        """Test admin email retrieval when no admins exist."""
        # Override config to have no admins
        analyzer.config.content = {"users": {}}

        result = analyzer.get_admin_emails()

        assert result == []

    def test_get_admin_emails_exception(self, analyzer):
        """Test admin email retrieval when exception occurs."""
        analyzer.config.content = None

        result = analyzer.get_admin_emails()

        assert result == []
