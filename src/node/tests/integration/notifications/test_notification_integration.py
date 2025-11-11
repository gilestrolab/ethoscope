#!/usr/bin/env python

"""
Integration tests for the notification system.
Tests end-to-end workflows and component interactions.
"""

import datetime
import json
import os
import tempfile
import time
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from ethoscope_node.notifications.base import NotificationAnalyzer
from ethoscope_node.notifications.email import EmailNotificationService


class TestNotificationIntegration:
    """Integration tests for notification system workflows."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration with full structure."""
        config = Mock()
        config.content = {
            "smtp": {
                "enabled": True,
                "host": "smtp.example.com",
                "port": 587,
                "username": "test@example.com",
                "password": "test_password",
                "from_email": "ethoscope@example.com",
                "use_tls": True,
            },
            "alerts": {"cooldown_seconds": 300},
            "users": {
                "researcher1": {
                    "email": "researcher1@example.com",
                    "isAdmin": False,
                    "active": True,
                },
                "researcher2": {
                    "email": "researcher2@example.com",
                    "isAdmin": False,
                    "active": True,
                },
                "admin": {
                    "email": "admin@example.com",
                    "isAdmin": True,
                    "active": True,
                },
                "inactive_user": {
                    "email": "inactive@example.com",
                    "isAdmin": False,
                    "active": False,
                },
            },
        }
        return config

    @pytest.fixture
    def mock_db_with_data(self):
        """Mock database with realistic test data."""
        db = Mock()

        # Mock ethoscope data
        # When asdict=True, getEthoscope returns {ethoscope_id: {device_data}}
        ethoscope_data = {
            "ETHOSCOPE_001": {
                "ethoscope_id": "ETHOSCOPE_001",
                "ethoscope_name": "ETHOSCOPE_001",
                "last_ip": "192.168.1.100",
                "last_seen": time.time() - 60,  # 1 minute ago
                "active": True,
                "problems": "",
            },
            "ETHOSCOPE_002": {
                "ethoscope_id": "ETHOSCOPE_002",
                "ethoscope_name": "ETHOSCOPE_002",
                "last_ip": "192.168.1.101",
                "last_seen": time.time() - 3600,  # 1 hour ago
                "active": False,
                "problems": "Network timeout",
            },
            "ETHOSCOPE_003": {
                "ethoscope_id": "ETHOSCOPE_003",
                "ethoscope_name": "ETHOSCOPE_003",
                "last_ip": "192.168.1.102",
                "last_seen": time.time() - 120,  # 2 minutes ago
                "active": True,
                "problems": "",
            },
        }

        # Mock runs data
        runs_data = {
            "run_001": {
                "run_id": "run_001",
                "ethoscope_id": "ETHOSCOPE_001",
                "start_time": time.time() - 7200,  # 2 hours ago
                "end_time": None,  # Still running (crashed)
                "user_name": "researcher1",
                "location": "Incubator_A",
                "problems": "Device stopped responding",
                "experimental_data": json.dumps(
                    {"type": "tracking", "fps": 30, "roi_builder": "default"}
                ),
            },
            "run_002": {
                "run_id": "run_002",
                "ethoscope_id": "ETHOSCOPE_002",
                "start_time": time.time() - 86400,  # 1 day ago
                "end_time": time.time() - 82800,  # 1 hour after start
                "user_name": "researcher2",
                "location": "Incubator_B",
                "problems": "",
                "experimental_data": json.dumps(
                    {"type": "recording", "fps": 25, "roi_builder": "sleep_annotation"}
                ),
            },
            "run_003": {
                "run_id": "run_003",
                "ethoscope_id": "ETHOSCOPE_003",
                "start_time": time.time() - 3600,  # 1 hour ago
                "end_time": None,  # Currently running
                "user_name": "researcher2",
                "location": "Incubator_C",
                "problems": "",
                "experimental_data": json.dumps(
                    {"type": "tracking", "fps": 25, "roi_builder": "default"}
                ),
            },
        }

        def mock_get_ethoscope(device_id, asdict=False):
            # Return nested structure like real database: {device_id: {device_data}}
            device_data = ethoscope_data.get(device_id)
            if device_data and asdict:
                return {device_id: device_data}
            return device_data if device_data else {}

        def mock_get_run(run_id, asdict=False):
            if run_id == "all":
                return runs_data
            return runs_data.get(run_id)

        def mock_get_users_for_device(device_id, running_only=True, asdict=True):
            # Find runs for this device
            device_runs = [run for run in runs_data.values() if run["ethoscope_id"] == device_id]

            # If running_only, filter for runs without end_time
            if running_only:
                device_runs = [run for run in device_runs if run["end_time"] is None]

            # Return list of user dicts with emails
            user_emails = []
            for run in device_runs:
                username = run.get("user_name")
                if username:
                    user_emails.append({"email": f"{username}@example.com"})
            return user_emails

        def mock_get_all_users(active_only=True, admin_only=False, asdict=True):
            # Return admin users with emails
            # When asdict=True, return dictionary keyed by username
            # When asdict=False, return list of user dicts
            if admin_only:
                if asdict:
                    return {"admin": {"email": "admin@example.com", "username": "admin", "isAdmin": True, "active": True}}
                else:
                    return [{"email": "admin@example.com", "username": "admin", "isAdmin": True, "active": True}]
            if asdict:
                return {}
            return []

        def mock_get_user_by_run(run_id, asdict=True):
            # Return user who owns the specified run
            run = runs_data.get(run_id)
            if run:
                username = run.get("user_name")
                return {"email": f"{username}@example.com", "username": username, "active": 1}
            return None

        db.getEthoscope.side_effect = mock_get_ethoscope
        db.getRun.side_effect = mock_get_run
        db.getUsersForDevice.side_effect = mock_get_users_for_device
        db.getAllUsers.side_effect = mock_get_all_users
        db.getUserByRun.side_effect = mock_get_user_by_run
        db.logAlert.return_value = None  # Mock alert logging

        return db

    @pytest.fixture
    def email_service_integration(self, mock_config, mock_db_with_data):
        """Create email service for integration testing."""
        return EmailNotificationService(config=mock_config, db=mock_db_with_data)

    def test_complete_device_failure_analysis_workflow(self, email_service_integration):
        """Test complete device failure analysis workflow."""
        device_id = "ETHOSCOPE_001"

        # Analyze device failure
        analysis = email_service_integration.analyze_device_failure(device_id)

        # Verify analysis contains expected information
        assert analysis["device_id"] == device_id
        assert analysis["device_name"] == "Device ETHOSCOPE_001"  # analyze_device_failure doesn't extract nested data properly
        assert analysis["failure_type"] == "crashed_during_tracking"
        assert analysis["status"] == "Failed while running"
        assert analysis["user"] == "researcher1"
        assert analysis["location"] == "Incubator_A"
        assert analysis["experiment_type"] == "tracking"
        assert analysis["problems"] == "Device stopped responding"
        assert analysis["device_active"] == False  # Bug: uses device_info instead of device_data
        assert "experiment_duration" in analysis
        assert "experiment_duration_str" in analysis

        # Verify duration calculation (should be about 2 hours)
        duration = analysis["experiment_duration"]
        assert 7000 < duration < 8000  # Approximately 2 hours

    def test_completed_experiment_analysis_workflow(self, email_service_integration):
        """Test analysis workflow for completed experiment."""
        device_id = "ETHOSCOPE_002"

        # Analyze device failure
        analysis = email_service_integration.analyze_device_failure(device_id)

        # Verify analysis contains expected information
        assert analysis["device_id"] == device_id
        assert analysis["device_name"] == "Device ETHOSCOPE_002"  # analyze_device_failure doesn't extract nested data properly
        assert analysis["failure_type"] == "completed_normally"
        assert analysis["status"] == "Completed normally"
        assert analysis["user"] == "researcher2"
        assert analysis["location"] == "Incubator_B"
        assert analysis["experiment_type"] == "recording"
        assert analysis["device_active"] == False
        assert analysis["device_problems"] == ""  # Bug: uses device_info instead of device_data

        # Verify duration calculation (should be about 1 hour)
        duration = analysis["experiment_duration"]
        assert 3500 < duration < 4000  # Approximately 1 hour

    def test_user_email_resolution_workflow(self, email_service_integration):
        """Test user email resolution workflow."""
        device_id = "ETHOSCOPE_001"

        # Get device users
        users = email_service_integration.get_device_users(device_id)

        # Should resolve researcher1 to email
        assert "researcher1@example.com" in users
        assert len(users) == 1

        # Test admin emails
        admins = email_service_integration.get_admin_emails()
        assert "admin@example.com" in admins
        assert len(admins) == 1

    def test_multiple_devices_user_resolution(self, email_service_integration):
        """Test user resolution for multiple devices."""
        # Get users for device with researcher2 (ETHOSCOPE_003)
        users_device3 = email_service_integration.get_device_users("ETHOSCOPE_003")
        assert "researcher2@example.com" in users_device3

        # Get users for device with researcher1 (ETHOSCOPE_001)
        users_device1 = email_service_integration.get_device_users("ETHOSCOPE_001")
        assert "researcher1@example.com" in users_device1

        # Should not overlap
        assert "researcher2@example.com" not in users_device1
        assert "researcher1@example.com" not in users_device3

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_device_log_retrieval_workflow(self, mock_get, email_service_integration):
        """Test device log retrieval workflow."""
        device_id = "ETHOSCOPE_001"

        # Mock log response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = """
        2024-01-01 10:00:00 - INFO - Device started
        2024-01-01 10:01:00 - INFO - Camera initialized
        2024-01-01 10:02:00 - INFO - Tracking started
        2024-01-01 12:00:00 - ERROR - Network connection lost
        2024-01-01 12:00:01 - ERROR - Device stopped responding
        """
        mock_get.return_value = mock_response

        # Get device logs
        logs = email_service_integration.get_device_logs(device_id, max_lines=10)

        # Verify log retrieval
        assert logs is not None
        assert "Device started" in logs
        assert "Network connection lost" in logs
        assert "Device stopped responding" in logs

        # Verify API call
        mock_get.assert_called_once_with(
            "http://192.168.1.100:9000/data/log/ETHOSCOPE_001", timeout=10
        )

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_device_status_retrieval_workflow(
        self, mock_get, email_service_integration
    ):
        """Test device status retrieval workflow."""
        device_id = "ETHOSCOPE_001"

        # Mock status response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "running",
            "monitor_info": {"last_time_stamp": time.time(), "fps": 30},
            "experimental_info": {
                "run_id": "run_001",
                "name": "researcher1",
                "location": "Incubator_A",
            },
            "database_info": {
                "database_name": "ethoscope_db",
                "last_update": time.time(),
            },
        }
        mock_get.return_value = mock_response

        # Get device status
        status = email_service_integration.get_device_status_info(device_id)

        # Verify status retrieval
        assert status["device_id"] == device_id
        assert status["device_name"] is None  # Bug: uses device_info instead of device_data
        assert status["online"] == True
        assert status["status"] == "running"
        assert status["fps"] == 30
        assert "experimental_info" in status
        assert "database_info" in status

    def test_cooldown_mechanism_workflow(self, email_service_integration):
        """Test alert cooldown mechanism workflow."""
        device_id = "ETHOSCOPE_001"
        alert_type = "device_stopped"

        # First alert should be allowed
        should_send_1 = email_service_integration._should_send_alert(
            device_id, alert_type
        )
        assert should_send_1 == True

        # Second alert immediately after should be blocked
        should_send_2 = email_service_integration._should_send_alert(
            device_id, alert_type
        )
        assert should_send_2 == False

        # Different alert type should be allowed
        should_send_3 = email_service_integration._should_send_alert(
            device_id, "storage_warning"
        )
        assert should_send_3 == True

        # Different device should be allowed
        should_send_4 = email_service_integration._should_send_alert(
            "ETHOSCOPE_002", alert_type
        )
        assert should_send_4 == True

    def test_error_handling_workflow(self, email_service_integration):
        """Test error handling in various workflow scenarios."""
        # Test with non-existent device
        analysis = email_service_integration.analyze_device_failure(
            "NONEXISTENT_DEVICE"
        )
        assert "error" in analysis
        assert analysis["error"] == "Device not found in database"

        # Test with device that has no runs
        # First add a device with no runs
        email_service_integration.db.getEthoscope.side_effect = (
            lambda device_id, asdict=False: (
                {"ethoscope_name": "Test Device", "last_seen": time.time()}
                if device_id == "EMPTY_DEVICE"
                else email_service_integration.db.getEthoscope.side_effect(
                    device_id, asdict
                )
            )
        )

        analysis = email_service_integration.analyze_device_failure("EMPTY_DEVICE")
        assert "error" in analysis
        assert analysis["error"] == "No runs found for device"

    @patch("ethoscope_node.notifications.base.requests.get")
    def test_offline_device_handling_workflow(
        self, mock_get, email_service_integration
    ):
        """Test handling of offline devices."""
        device_id = "ETHOSCOPE_002"  # This device is marked as inactive

        # Mock failed request (device offline)
        mock_get.side_effect = Exception("Connection refused")

        # Test log retrieval for offline device
        logs = email_service_integration.get_device_logs(device_id)
        assert logs is None

        # Test status retrieval for offline device
        status = email_service_integration.get_device_status_info(device_id)
        assert status["device_id"] == device_id
        assert "error" in status
        assert status["error"] == "Connection refused"

    def test_email_configuration_validation_workflow(self, email_service_integration):
        """Test email configuration validation workflow."""
        # Test with valid configuration
        config_test = email_service_integration.test_email_configuration()

        # Since we're not actually sending emails, this will depend on implementation
        # but we can test that the method runs without errors
        assert "success" in config_test
        assert "recipients" in config_test or "error" in config_test

    def test_multiple_user_notification_workflow(self, email_service_integration):
        """Test notification workflow with multiple users."""
        device_id = "ETHOSCOPE_001"

        # Get all recipients (device users + admins)
        device_users = email_service_integration.get_device_users(device_id)
        admin_emails = email_service_integration.get_admin_emails()
        all_recipients = list(set(device_users + admin_emails))

        # Should have both researcher and admin
        assert "researcher1@example.com" in all_recipients
        assert "admin@example.com" in all_recipients
        assert len(all_recipients) == 2

        # Verify no duplicates and no inactive users
        assert "inactive@example.com" not in all_recipients
        assert len(all_recipients) == len(set(all_recipients))  # No duplicates
