#!/usr/bin/env python

"""
Unit tests for the Mattermost notification service.
"""

import datetime
import json
import time
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch

import pytest

from ethoscope_node.notifications.mattermost import MattermostNotificationService


class TestMattermostNotificationService:
    """Test cases for MattermostNotificationService class."""

    @pytest.fixture
    def mock_config(self):
        """Mock configuration object."""
        config = Mock()
        config.content = {
            "mattermost": {
                "enabled": True,
                "server_url": "https://mattermost.example.com",
                "bot_token": "3ukwqqtwaiftjqk7awuz89jska",
                "channel_id": "oprdt3widpd5ufg6pznask7wpo",
            },
            "alerts": {"cooldown_seconds": 300},
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
            },
        }
        return config

    @pytest.fixture
    def mock_db(self):
        """Mock database object."""
        db = Mock()
        return db

    @pytest.fixture
    def mattermost_service(self, mock_config, mock_db):
        """Create Mattermost service instance with mocked dependencies."""
        return MattermostNotificationService(config=mock_config, db=mock_db)

    def test_init_inherits_from_base(self, mattermost_service):
        """Test that MattermostNotificationService inherits from NotificationAnalyzer."""
        from ethoscope_node.notifications.base import NotificationAnalyzer

        assert isinstance(mattermost_service, NotificationAnalyzer)
        assert hasattr(mattermost_service, "_last_alert_times")
        assert hasattr(mattermost_service, "_default_cooldown")
        assert mattermost_service._default_cooldown == 3600

    def test_get_mattermost_config(self, mattermost_service):
        """Test Mattermost configuration retrieval."""
        config = mattermost_service._get_mattermost_config()

        assert config["enabled"] == True
        assert config["server_url"] == "https://mattermost.example.com"
        assert config["bot_token"] == "3ukwqqtwaiftjqk7awuz89jska"
        assert config["channel_id"] == "oprdt3widpd5ufg6pznask7wpo"

    def test_get_alert_config(self, mattermost_service):
        """Test alert configuration retrieval."""
        config = mattermost_service._get_alert_config()

        assert config["cooldown_seconds"] == 300

    def test_should_send_alert_first_time(self, mattermost_service):
        """Test that alert should be sent the first time."""
        result = mattermost_service._should_send_alert("device_001", "device_stopped")

        assert result == True
        assert "device_001:device_stopped" in mattermost_service._last_alert_times

    def test_should_send_alert_cooldown_active(self, mattermost_service):
        """Test that alert should not be sent during cooldown period."""
        device_id = "device_001"
        alert_type = "device_stopped"

        # Send first alert
        mattermost_service._should_send_alert(device_id, alert_type)

        # Try to send again immediately - should be blocked
        result = mattermost_service._should_send_alert(device_id, alert_type)

        assert result == False

    def test_should_send_alert_cooldown_expired(self, mattermost_service):
        """Test that alert should be sent after cooldown expires."""
        device_id = "device_001"
        alert_type = "device_stopped"

        # Send first alert
        mattermost_service._should_send_alert(device_id, alert_type)

        # Manually set last alert time to past
        mattermost_service._last_alert_times[f"{device_id}:{alert_type}"] = (
            time.time() - 400
        )

        # Should be able to send again
        result = mattermost_service._should_send_alert(device_id, alert_type)

        assert result == True

    def test_should_send_alert_with_run_id(self, mattermost_service):
        """Test alert sending with run_id for database duplicate checking."""
        device_id = "device_001"
        alert_type = "device_stopped"
        run_id = "run_123"

        # Mock database response - alert not sent before
        mattermost_service.db.hasAlertBeenSent.return_value = False

        result = mattermost_service._should_send_alert(device_id, alert_type, run_id)

        assert result == True
        mattermost_service.db.hasAlertBeenSent.assert_called_once_with(
            device_id, alert_type, run_id
        )

    def test_should_send_alert_duplicate_run_id(self, mattermost_service):
        """Test alert prevention for duplicate run_id."""
        device_id = "device_001"
        alert_type = "device_stopped"
        run_id = "run_123"

        # Mock database response - alert already sent
        mattermost_service.db.hasAlertBeenSent.return_value = True

        result = mattermost_service._should_send_alert(device_id, alert_type, run_id)

        assert result == False
        mattermost_service.db.hasAlertBeenSent.assert_called_once_with(
            device_id, alert_type, run_id
        )

    @patch("ethoscope_node.notifications.mattermost.requests.post")
    def test_send_message_success(self, mock_post, mattermost_service):
        """Test successful message sending."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = mattermost_service._send_message("Test message")

        assert result == True
        mock_post.assert_called_once()

        # Check API call parameters
        call_args = mock_post.call_args
        assert (
            call_args[0][0] == "https://mattermost.example.com/api/v4/posts"
        )  # URL as first positional arg
        assert (
            call_args[1]["headers"]["Authorization"]
            == "Bearer 3ukwqqtwaiftjqk7awuz89jska"
        )
        assert call_args[1]["headers"]["Content-Type"] == "application/json"
        assert call_args[1]["json"]["channel_id"] == "oprdt3widpd5ufg6pznask7wpo"
        assert call_args[1]["json"]["message"] == "Test message"
        assert call_args[1]["timeout"] == 10

    @patch("ethoscope_node.notifications.mattermost.requests.post")
    def test_send_message_disabled(self, mock_post, mattermost_service):
        """Test message sending when disabled in config."""
        mattermost_service.config.content["mattermost"]["enabled"] = False

        result = mattermost_service._send_message("Test message")

        assert result == False
        mock_post.assert_not_called()

    @patch("ethoscope_node.notifications.mattermost.requests.post")
    def test_send_message_missing_config(self, mock_post, mattermost_service):
        """Test message sending with incomplete configuration."""
        mattermost_service.config.content["mattermost"]["bot_token"] = None

        result = mattermost_service._send_message("Test message")

        assert result == False
        mock_post.assert_not_called()

    @patch("ethoscope_node.notifications.mattermost.requests.post")
    def test_send_message_http_error(self, mock_post, mattermost_service):
        """Test message sending when HTTP request fails."""
        import requests

        mock_post.side_effect = requests.RequestException("Connection failed")

        result = mattermost_service._send_message("Test message")

        assert result == False

    @patch("ethoscope_node.notifications.mattermost.requests.post")
    def test_send_message_http_status_error(self, mock_post, mattermost_service):
        """Test message sending when HTTP status indicates error."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
        mock_post.return_value = mock_response

        result = mattermost_service._send_message("Test message")

        assert result == False

    @patch.object(MattermostNotificationService, "_send_message")
    @patch.object(MattermostNotificationService, "get_device_logs")
    @patch.object(MattermostNotificationService, "analyze_device_failure")
    def test_send_device_stopped_alert_success(
        self, mock_analyze, mock_get_logs, mock_send, mattermost_service
    ):
        """Test successful device stopped alert."""
        device_id = "device_001"
        device_name = "Test Device"
        run_id = "run_123"
        last_seen = datetime.datetime.now()

        # Mock return values
        mock_analyze.return_value = {
            "user": "test_user",
            "location": "Incubator_A",
            "experiment_duration_str": "2.5 hours",
            "experiment_type": "tracking",
            "status": "Failed while running",
            "start_time": datetime.datetime.now() - datetime.timedelta(hours=2),
            "problems": "Network timeout",
            "device_problems": "Camera issue",
        }
        mock_get_logs.return_value = (
            "Log line 1\nLog line 2\nError occurred\nLog line 4\nLog line 5"
        )
        mock_send.return_value = True

        # Mock database methods
        with patch.object(
            mattermost_service.db, "hasAlertBeenSent", return_value=False
        ), patch.object(mattermost_service.db, "logAlert", return_value=1):
            result = mattermost_service.send_device_stopped_alert(
                device_id, device_name, run_id, last_seen
            )

            assert result == True
            mock_analyze.assert_called_once_with(device_id)
            mock_get_logs.assert_called_once_with(device_id, max_lines=10)
            mock_send.assert_called_once()

            # Check that message contains key information
            call_args = mock_send.call_args[0][0]  # Get the message argument
            assert device_name in call_args
            assert device_id in call_args
            assert run_id in call_args
            assert "test_user" in call_args
            assert "Incubator_A" in call_args
            assert "2.5 hours" in call_args
            assert "tracking" in call_args
            assert "Failed while running" in call_args
            assert "Network timeout" in call_args
            assert "Camera issue" in call_args

            # Check that recent logs are included
            assert "Recent logs:" in call_args
            assert "Log line 5" in call_args  # Should show last 5 lines

    @patch.object(MattermostNotificationService, "_should_send_alert")
    def test_send_device_stopped_alert_cooldown(
        self, mock_should_send, mattermost_service
    ):
        """Test device stopped alert blocked by cooldown."""
        mock_should_send.return_value = False

        result = mattermost_service.send_device_stopped_alert(
            "device_001", "Test Device", "run_123", datetime.datetime.now()
        )

        assert result == False
        mock_should_send.assert_called_once_with(
            "device_001", "device_stopped", "run_123"
        )

    @patch.object(MattermostNotificationService, "analyze_device_failure")
    def test_send_device_stopped_alert_exception(
        self, mock_analyze, mattermost_service
    ):
        """Test device stopped alert when exception occurs."""
        mock_analyze.side_effect = Exception("Database error")

        result = mattermost_service.send_device_stopped_alert(
            "device_001", "Test Device", "run_123", datetime.datetime.now()
        )

        assert result == False

    @patch.object(MattermostNotificationService, "_send_message")
    def test_send_storage_warning_alert_success(self, mock_send, mattermost_service):
        """Test successful storage warning alert."""
        device_id = "device_001"
        device_name = "Test Device"
        storage_percent = 85.5
        available_space = "2.1 GB"

        mock_send.return_value = True

        result = mattermost_service.send_storage_warning_alert(
            device_id, device_name, storage_percent, available_space
        )

        assert result == True
        mock_send.assert_called_once()

        # Check message content
        call_args = mock_send.call_args[0][0]
        assert "Storage Warning" in call_args
        assert device_name in call_args
        assert device_id in call_args
        assert "85.5%" in call_args
        assert "2.1 GB" in call_args

    @patch.object(MattermostNotificationService, "_should_send_alert")
    def test_send_storage_warning_alert_cooldown(
        self, mock_should_send, mattermost_service
    ):
        """Test storage warning alert blocked by cooldown."""
        mock_should_send.return_value = False

        result = mattermost_service.send_storage_warning_alert(
            "device_001", "Test Device", 85.5, "2.1 GB"
        )

        assert result == False
        mock_should_send.assert_called_once_with("device_001", "storage_warning")

    @patch.object(MattermostNotificationService, "_send_message")
    def test_send_device_unreachable_alert_success(self, mock_send, mattermost_service):
        """Test successful device unreachable alert."""
        device_id = "device_001"
        device_name = "Test Device"
        last_seen = datetime.datetime.now() - datetime.timedelta(hours=2)

        mock_send.return_value = True

        result = mattermost_service.send_device_unreachable_alert(
            device_id, device_name, last_seen
        )

        assert result == True
        mock_send.assert_called_once()

        # Check message content
        call_args = mock_send.call_args[0][0]
        assert "Device Unreachable" in call_args
        assert device_name in call_args
        assert device_id in call_args
        assert "2.0 hours" in call_args  # Offline duration

    @patch.object(MattermostNotificationService, "_should_send_alert")
    def test_send_device_unreachable_alert_cooldown(
        self, mock_should_send, mattermost_service
    ):
        """Test device unreachable alert blocked by cooldown."""
        mock_should_send.return_value = False

        result = mattermost_service.send_device_unreachable_alert(
            "device_001", "Test Device", datetime.datetime.now()
        )

        assert result == False
        mock_should_send.assert_called_once_with("device_001", "device_unreachable")

    @patch.object(MattermostNotificationService, "_send_message")
    def test_test_mattermost_configuration_success(self, mock_send, mattermost_service):
        """Test successful Mattermost configuration test."""
        mock_send.return_value = True

        result = mattermost_service.test_mattermost_configuration()

        assert result["success"] == True
        assert result["server_url"] == "https://mattermost.example.com"
        assert result["channel_id"] == "oprdt3widpd5ufg6pznask7wpo"
        assert "Test message sent successfully" in result["message"]
        mock_send.assert_called_once()

        # Check that test message was sent
        call_args = mock_send.call_args[0][0]
        assert "Ethoscope Test Message" in call_args
        assert "Mattermost notifications are working correctly!" in call_args

    def test_test_mattermost_configuration_disabled(self, mattermost_service):
        """Test Mattermost configuration test when disabled."""
        mattermost_service.config.content["mattermost"]["enabled"] = False

        result = mattermost_service.test_mattermost_configuration()

        assert result["success"] == False
        assert "disabled" in result["error"]

    def test_test_mattermost_configuration_missing_config(self, mattermost_service):
        """Test Mattermost configuration test with incomplete config."""
        mattermost_service.config.content["mattermost"]["bot_token"] = None

        result = mattermost_service.test_mattermost_configuration()

        assert result["success"] == False
        assert "configuration incomplete" in result["error"]

    @patch.object(MattermostNotificationService, "_send_message")
    def test_test_mattermost_configuration_send_failure(
        self, mock_send, mattermost_service
    ):
        """Test Mattermost configuration test when sending fails."""
        mock_send.return_value = False

        result = mattermost_service.test_mattermost_configuration()

        assert result["success"] == False
        assert "Failed to send test message" in result["error"]

    @patch.object(MattermostNotificationService, "_send_message")
    def test_test_mattermost_configuration_exception(
        self, mock_send, mattermost_service
    ):
        """Test Mattermost configuration test when exception occurs."""
        mock_send.side_effect = Exception("API error")

        result = mattermost_service.test_mattermost_configuration()

        assert result["success"] == False
        assert "Exception during test: API error" in result["error"]

    def test_mattermost_service_inherits_all_base_methods(self, mattermost_service):
        """Test that Mattermost service has all base analyzer methods."""
        # Check that key methods from base class are available
        assert hasattr(mattermost_service, "analyze_device_failure")
        assert hasattr(mattermost_service, "get_device_logs")
        assert hasattr(mattermost_service, "get_device_status_info")
        assert hasattr(mattermost_service, "get_device_users")
        assert hasattr(mattermost_service, "get_admin_emails")
        assert hasattr(mattermost_service, "_format_duration")

    def test_send_device_stopped_alert_without_logs(self, mattermost_service):
        """Test device stopped alert when logs are not available."""
        with patch.object(
            mattermost_service, "analyze_device_failure"
        ) as mock_analyze, patch.object(
            mattermost_service, "get_device_logs"
        ) as mock_get_logs, patch.object(
            mattermost_service, "_send_message"
        ) as mock_send:

            mock_analyze.return_value = {
                "user": "test_user",
                "location": "Incubator_A",
                "experiment_duration_str": "2.5 hours",
                "experiment_type": "tracking",
                "status": "Failed while running",
                "start_time": datetime.datetime.now(),
                "problems": "",
                "device_problems": "",
            }
            mock_get_logs.return_value = None  # No logs available
            mock_send.return_value = True

            # Mock database methods
            with patch.object(
                mattermost_service.db, "hasAlertBeenSent", return_value=False
            ), patch.object(mattermost_service.db, "logAlert", return_value=1):

                result = mattermost_service.send_device_stopped_alert(
                    "device_001", "Test Device", "run_123", datetime.datetime.now()
                )

                assert result == True

                # Check that message was created without logs section
                call_args = mock_send.call_args[0][0]
                assert "Recent logs:" not in call_args

    def test_send_device_stopped_alert_empty_logs(self, mattermost_service):
        """Test device stopped alert when logs are empty."""
        with patch.object(
            mattermost_service, "analyze_device_failure"
        ) as mock_analyze, patch.object(
            mattermost_service, "get_device_logs"
        ) as mock_get_logs, patch.object(
            mattermost_service, "_send_message"
        ) as mock_send:

            mock_analyze.return_value = {
                "user": "test_user",
                "status": "Failed while running",
            }
            mock_get_logs.return_value = ""  # Empty logs
            mock_send.return_value = True

            # Mock database methods
            with patch.object(
                mattermost_service.db, "hasAlertBeenSent", return_value=False
            ), patch.object(mattermost_service.db, "logAlert", return_value=1):

                result = mattermost_service.send_device_stopped_alert(
                    "device_001", "Test Device", "run_123", datetime.datetime.now()
                )

                assert result == True

                # Check that message was created without logs section
                call_args = mock_send.call_args[0][0]
                assert "Recent logs:" not in call_args
