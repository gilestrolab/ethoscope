#!/usr/bin/env python

"""
Unit tests for the Slack notification service.
"""

import datetime
import json
import time
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from ethoscope_node.notifications.slack import SlackNotificationService


class TestSlackNotificationService:
    """Test cases for SlackNotificationService class."""

    @pytest.fixture
    def mock_config_webhook(self):
        """Mock configuration object for webhook method."""
        config = Mock()
        config.content = {
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
                "channel": "#alerts",
                "use_webhook": True,
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
    def mock_config_bot_token(self):
        """Mock configuration object for bot token method."""
        config = Mock()
        config.content = {
            "slack": {
                "enabled": True,
                "bot_token": "fake_bot_token_for_testing_only",
                "channel": "#alerts",
                "use_webhook": False,
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
    def mock_config_disabled(self):
        """Mock configuration object with Slack disabled."""
        config = Mock()
        config.content = {
            "slack": {
                "enabled": False,
                "webhook_url": "",
                "bot_token": "",
                "channel": "",
                "use_webhook": True,
            },
            "alerts": {"cooldown_seconds": 300},
        }
        return config

    @pytest.fixture
    def mock_db(self):
        """Mock database object."""
        db = Mock()
        db.hasAlertBeenSent.return_value = False
        db.logAlert.return_value = None
        return db

    @pytest.fixture
    def slack_service_webhook(self, mock_config_webhook, mock_db):
        """Create Slack service instance with webhook configuration."""
        return SlackNotificationService(config=mock_config_webhook, db=mock_db)

    @pytest.fixture
    def slack_service_bot_token(self, mock_config_bot_token, mock_db):
        """Create Slack service instance with bot token configuration."""
        return SlackNotificationService(config=mock_config_bot_token, db=mock_db)

    @pytest.fixture
    def slack_service_disabled(self, mock_config_disabled, mock_db):
        """Create Slack service instance with disabled configuration."""
        return SlackNotificationService(config=mock_config_disabled, db=mock_db)

    def test_init_inherits_from_base(self, slack_service_webhook):
        """Test that SlackNotificationService inherits from NotificationAnalyzer."""
        from ethoscope_node.notifications.base import NotificationAnalyzer

        assert isinstance(slack_service_webhook, NotificationAnalyzer)
        assert hasattr(slack_service_webhook, "_last_alert_times")
        assert hasattr(slack_service_webhook, "_default_cooldown")
        assert slack_service_webhook._default_cooldown == 3600

    def test_get_slack_config_webhook(self, slack_service_webhook):
        """Test Slack configuration retrieval for webhook method."""
        config = slack_service_webhook._get_slack_config()

        assert config["enabled"] == True
        assert (
            config["webhook_url"]
            == "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
        )
        assert config["channel"] == "#alerts"
        assert config["use_webhook"] == True

    def test_get_slack_config_bot_token(self, slack_service_bot_token):
        """Test Slack configuration retrieval for bot token method."""
        config = slack_service_bot_token._get_slack_config()

        assert config["enabled"] == True
        assert config["bot_token"] == "fake_bot_token_for_testing_only"
        assert config["channel"] == "#alerts"
        assert config["use_webhook"] == False

    def test_get_alert_config(self, slack_service_webhook):
        """Test alert configuration retrieval."""
        config = slack_service_webhook._get_alert_config()

        assert config["cooldown_seconds"] == 300

    def test_should_send_alert_first_time(self, slack_service_webhook):
        """Test that alert should be sent the first time."""
        result = slack_service_webhook._should_send_alert(
            "device_001", "device_stopped"
        )

        assert result == True
        assert "device_001:device_stopped" in slack_service_webhook._last_alert_times

    def test_should_send_alert_cooldown_active(self, slack_service_webhook):
        """Test that alert should not be sent during cooldown period."""
        device_id = "device_001"
        alert_type = "device_stopped"

        # Send first alert
        slack_service_webhook._should_send_alert(device_id, alert_type)

        # Try to send again immediately - should be blocked
        result = slack_service_webhook._should_send_alert(device_id, alert_type)

        assert result == False

    def test_should_send_alert_cooldown_expired(self, slack_service_webhook):
        """Test that alert should be sent after cooldown expires."""
        device_id = "device_001"
        alert_type = "device_stopped"

        # Send first alert
        slack_service_webhook._should_send_alert(device_id, alert_type)

        # Manually set last alert time to past (simulate cooldown expiry)
        slack_service_webhook._last_alert_times[f"{device_id}:{alert_type}"] = (
            time.time() - 400
        )

        # Should be allowed now
        result = slack_service_webhook._should_send_alert(device_id, alert_type)

        assert result == True

    def test_should_send_alert_with_run_id(self, slack_service_webhook, mock_db):
        """Test alert with run_id uses database check."""
        mock_db.hasAlertBeenSent.return_value = False

        result = slack_service_webhook._should_send_alert(
            "device_001", "device_stopped", "run123"
        )

        assert result == True
        mock_db.hasAlertBeenSent.assert_called_once_with(
            "device_001", "device_stopped", "run123"
        )

    def test_should_send_alert_with_run_id_already_sent(
        self, slack_service_webhook, mock_db
    ):
        """Test alert with run_id that was already sent."""
        mock_db.hasAlertBeenSent.return_value = True

        result = slack_service_webhook._should_send_alert(
            "device_001", "device_stopped", "run123"
        )

        assert result == False
        mock_db.hasAlertBeenSent.assert_called_once_with(
            "device_001", "device_stopped", "run123"
        )

    @patch("requests.post")
    def test_send_via_webhook_success(self, mock_post, slack_service_webhook):
        """Test successful webhook message sending."""
        mock_response = Mock()
        mock_response.text = "ok"
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}}
        ]
        result = slack_service_webhook._send_via_webhook(blocks, "Test fallback")

        assert result == True
        mock_post.assert_called_once()

        # Verify the payload structure
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert "blocks" in payload
        assert "text" in payload
        assert "channel" in payload
        assert payload["text"] == "Test fallback"
        assert payload["channel"] == "#alerts"

    @patch("requests.post")
    def test_send_via_webhook_failure(self, mock_post, slack_service_webhook):
        """Test webhook message sending failure."""
        mock_response = Mock()
        mock_response.text = "invalid_payload"
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}}
        ]
        result = slack_service_webhook._send_via_webhook(blocks, "Test fallback")

        assert result == False
        mock_post.assert_called_once()

    @patch("requests.post")
    def test_send_via_webhook_network_error(self, mock_post, slack_service_webhook):
        """Test webhook message sending with network error."""
        mock_post.side_effect = Exception("Network error")

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}}
        ]
        result = slack_service_webhook._send_via_webhook(blocks, "Test fallback")

        assert result == False

    @patch("requests.post")
    def test_send_via_bot_token_success(self, mock_post, slack_service_bot_token):
        """Test successful bot token message sending."""
        mock_response = Mock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}}
        ]
        result = slack_service_bot_token._send_via_bot_token(blocks, "Test fallback")

        assert result == True
        mock_post.assert_called_once()

        # Verify the API call
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://slack.com/api/chat.postMessage"
        headers = call_args[1]["headers"]
        assert "Bearer fake_bot_token_for_testing_only" in headers["Authorization"]

        payload = call_args[1]["json"]
        assert payload["channel"] == "#alerts"
        assert "blocks" in payload
        assert "text" in payload

    @patch("requests.post")
    def test_send_via_bot_token_api_error(self, mock_post, slack_service_bot_token):
        """Test bot token message sending with API error."""
        mock_response = Mock()
        mock_response.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}}
        ]
        result = slack_service_bot_token._send_via_bot_token(blocks, "Test fallback")

        assert result == False

    def test_send_message_disabled(self, slack_service_disabled):
        """Test that disabled service doesn't send messages."""
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Test message"}}
        ]
        result = slack_service_disabled._send_message(blocks, "Test fallback")

        assert result == False

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    @patch(
        "ethoscope_node.notifications.slack.SlackNotificationService.analyze_device_failure"
    )
    @patch(
        "ethoscope_node.notifications.slack.SlackNotificationService.get_device_logs"
    )
    def test_send_device_stopped_alert_success(
        self, mock_get_logs, mock_analyze, mock_send, slack_service_webhook, mock_db
    ):
        """Test successful device stopped alert."""
        # Mock return values
        mock_analyze.return_value = {
            "user": "test_user",
            "location": "Lab A",
            "experiment_duration_str": "2 hours",
            "experiment_type": "tracking",
            "status": "Failed while running",
            "problems": "Camera disconnected",
            "device_problems": "Network issues",
        }
        mock_get_logs.return_value = "ERROR: Camera timeout\nWARNING: Network unstable"
        mock_send.return_value = True

        # Test the alert
        result = slack_service_webhook.send_device_stopped_alert(
            device_id="device_001",
            device_name="Test Device",
            run_id="run123",
            last_seen=datetime.datetime.now(),
        )

        assert result == True
        mock_analyze.assert_called_once_with("device_001")
        mock_get_logs.assert_called_once_with("device_001", max_lines=10)
        mock_send.assert_called_once()

        # Verify database logging
        mock_db.logAlert.assert_called_once()
        call_args = mock_db.logAlert.call_args[0]
        assert call_args[0] == "device_001"
        assert call_args[1] == "device_stopped"
        assert call_args[3] == "slack"
        assert call_args[4] == "run123"

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    def test_send_device_stopped_alert_cooldown(self, mock_send, slack_service_webhook):
        """Test device stopped alert blocked by cooldown."""
        # First alert should work
        mock_send.return_value = True
        result1 = slack_service_webhook.send_device_stopped_alert(
            device_id="device_001",
            device_name="Test Device",
            run_id="run123",
            last_seen=datetime.datetime.now(),
        )
        assert result1 == True

        # Second alert immediately should be blocked
        result2 = slack_service_webhook.send_device_stopped_alert(
            device_id="device_001",
            device_name="Test Device",
            run_id="run123",
            last_seen=datetime.datetime.now(),
        )
        assert result2 == False

        # Should only be called once due to cooldown
        assert mock_send.call_count == 1

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    def test_send_storage_warning_alert_success(self, mock_send, slack_service_webhook):
        """Test successful storage warning alert."""
        mock_send.return_value = True

        result = slack_service_webhook.send_storage_warning_alert(
            device_id="device_001",
            device_name="Test Device",
            storage_percent=85.5,
            available_space="2.1 GB",
        )

        assert result == True
        mock_send.assert_called_once()

        # Verify the blocks structure for storage warning
        call_args = mock_send.call_args[0]
        blocks = call_args[0]
        fallback_text = call_args[1]

        assert len(blocks) == 3  # Header, fields, and actions
        assert blocks[0]["type"] == "header"
        assert "⚠️ Storage Warning" in blocks[0]["text"]["text"]
        assert "Test Device" in blocks[0]["text"]["text"]
        assert fallback_text.startswith("⚠️ Storage Warning")

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    def test_send_device_unreachable_alert_success(
        self, mock_send, slack_service_webhook
    ):
        """Test successful device unreachable alert."""
        mock_send.return_value = True

        last_seen = datetime.datetime.now() - datetime.timedelta(hours=2)
        result = slack_service_webhook.send_device_unreachable_alert(
            device_id="device_001", device_name="Test Device", last_seen=last_seen
        )

        assert result == True
        mock_send.assert_called_once()

        # Verify the blocks structure for unreachable alert
        call_args = mock_send.call_args[0]
        blocks = call_args[0]
        fallback_text = call_args[1]

        assert len(blocks) == 3  # Header, fields, and actions
        assert blocks[0]["type"] == "header"
        assert "📵 Device Unreachable" in blocks[0]["text"]["text"]
        assert "Test Device" in blocks[0]["text"]["text"]
        assert fallback_text.startswith("📵 Device Unreachable")

    def test_create_device_stopped_blocks(self, slack_service_webhook):
        """Test device stopped blocks creation."""
        failure_analysis = {
            "user": "test_user",
            "location": "Lab A",
            "experiment_duration_str": "2 hours",
            "experiment_type": "tracking",
            "status": "Failed while running",
            "problems": "Camera disconnected",
            "device_problems": "Network issues",
        }

        device_logs = "ERROR: Camera timeout\nWARNING: Network unstable\nINFO: Attempting reconnect"
        last_seen = datetime.datetime.now()

        blocks = slack_service_webhook._create_device_stopped_blocks(
            device_name="Test Device",
            device_id="device_001",
            failure_analysis=failure_analysis,
            run_id="run123",
            last_seen=last_seen,
            device_logs=device_logs,
        )

        assert len(blocks) >= 4  # Header, info, problems, logs, actions
        assert blocks[0]["type"] == "header"
        assert "🚨 Device Alert" in blocks[0]["text"]["text"]

        # Check info section has all the fields
        info_block = blocks[1]
        assert info_block["type"] == "section"
        assert "fields" in info_block

        # Should have at least device, status, run_id, last_seen fields
        fields = info_block["fields"]
        field_texts = [field["text"] for field in fields]
        assert any("Test Device (device_001)" in text for text in field_texts)
        assert any("Failed while running" in text for text in field_texts)
        assert any("run123" in text for text in field_texts)

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    def test_test_slack_configuration_webhook_success(
        self, mock_send, slack_service_webhook
    ):
        """Test Slack configuration test with webhook method."""
        mock_send.return_value = True

        result = slack_service_webhook.test_slack_configuration()

        assert result["success"] == True
        assert result["method"] == "webhook"
        assert result["webhook_configured"] == True
        assert "Test message sent successfully" in result["message"]
        mock_send.assert_called_once()

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    def test_test_slack_configuration_bot_token_success(
        self, mock_send, slack_service_bot_token
    ):
        """Test Slack configuration test with bot token method."""
        mock_send.return_value = True

        result = slack_service_bot_token.test_slack_configuration()

        assert result["success"] == True
        assert result["method"] == "bot_token"
        assert result["channel"] == "#alerts"
        assert "Test message sent successfully" in result["message"]
        mock_send.assert_called_once()

    def test_test_slack_configuration_disabled(self, slack_service_disabled):
        """Test Slack configuration test when disabled."""
        result = slack_service_disabled.test_slack_configuration()

        assert result["success"] == False
        assert "disabled in configuration" in result["error"]

    def test_test_slack_configuration_missing_webhook_url(
        self, mock_config_webhook, mock_db
    ):
        """Test configuration test with missing webhook URL."""
        mock_config_webhook.content["slack"]["webhook_url"] = ""
        service = SlackNotificationService(config=mock_config_webhook, db=mock_db)

        result = service.test_slack_configuration()

        assert result["success"] == False
        assert "webhook URL not configured" in result["error"]

    def test_test_slack_configuration_missing_bot_token(
        self, mock_config_bot_token, mock_db
    ):
        """Test configuration test with missing bot token."""
        mock_config_bot_token.content["slack"]["bot_token"] = ""
        service = SlackNotificationService(config=mock_config_bot_token, db=mock_db)

        result = service.test_slack_configuration()

        assert result["success"] == False
        assert "bot token not configured" in result["error"]

    def test_test_slack_configuration_missing_channel(
        self, mock_config_bot_token, mock_db
    ):
        """Test configuration test with missing channel for bot token method."""
        mock_config_bot_token.content["slack"]["channel"] = ""
        service = SlackNotificationService(config=mock_config_bot_token, db=mock_db)

        result = service.test_slack_configuration()

        assert result["success"] == False
        assert "channel not configured" in result["error"]

    @patch("ethoscope_node.notifications.slack.SlackNotificationService._send_message")
    def test_test_slack_configuration_send_failure(
        self, mock_send, slack_service_webhook
    ):
        """Test configuration test when message sending fails."""
        mock_send.return_value = False

        result = slack_service_webhook.test_slack_configuration()

        assert result["success"] == False
        assert "Failed to send test message" in result["error"]

    def test_alert_with_exception_handling(self, slack_service_webhook):
        """Test that exceptions in alert methods are handled gracefully."""
        with patch.object(
            slack_service_webhook, "analyze_device_failure"
        ) as mock_analyze:
            mock_analyze.side_effect = Exception("Analysis failed")

            result = slack_service_webhook.send_device_stopped_alert(
                device_id="device_001",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == False
