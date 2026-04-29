#!/usr/bin/env python

"""
Test fixtures and mock data for notification system tests.
"""

import datetime
import json
import time
from unittest.mock import MagicMock, Mock

import pytest


@pytest.fixture
def sample_ethoscope_config():
    """Sample configuration for ethoscope system."""
    return {
        "smtp": {
            "enabled": True,
            "host": "smtp.example.com",
            "port": 587,
            "username": "ethoscope@example.com",
            "password": "secure_password",
            "from_email": "ethoscope@example.com",
            "use_tls": True,
        },
        "alerts": {"cooldown_seconds": 300, "storage_warning_threshold": 80},
        "users": {
            "researcher1": {
                "email": "researcher1@example.com",
                "isAdmin": False,
                "active": True,
                "name": "Dr. Alice Researcher",
            },
            "researcher2": {
                "email": "researcher2@example.com",
                "isAdmin": False,
                "active": True,
                "name": "Dr. Bob Scientist",
            },
            "admin": {
                "email": "admin@example.com",
                "isAdmin": True,
                "active": True,
                "name": "System Administrator",
            },
            "inactive_user": {
                "email": "inactive@example.com",
                "isAdmin": False,
                "active": False,
                "name": "Inactive User",
            },
        },
    }


@pytest.fixture
def sample_ethoscope_data():
    """Sample ethoscope device data."""
    current_time = time.time()
    return {
        "ETHOSCOPE_001": {
            "ethoscope_id": "ETHOSCOPE_001",
            "ethoscope_name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "last_seen": current_time - 60,  # 1 minute ago
            "active": True,
            "problems": "",
            "machineinfo": {
                "platform": "linux",
                "version": "1.2.3",
                "hostname": "ethoscope-001",
            },
        },
        "ETHOSCOPE_002": {
            "ethoscope_id": "ETHOSCOPE_002",
            "ethoscope_name": "ETHOSCOPE_002",
            "ip": "192.168.1.101",
            "last_seen": current_time - 3600,  # 1 hour ago
            "active": False,
            "problems": "Network connectivity issues",
            "machineinfo": {
                "platform": "linux",
                "version": "1.2.3",
                "hostname": "ethoscope-002",
            },
        },
        "ETHOSCOPE_003": {
            "ethoscope_id": "ETHOSCOPE_003",
            "ethoscope_name": "ETHOSCOPE_003",
            "ip": "192.168.1.102",
            "last_seen": current_time - 86400,  # 1 day ago
            "active": False,
            "problems": "Device offline for maintenance",
            "machineinfo": {
                "platform": "linux",
                "version": "1.2.2",
                "hostname": "ethoscope-003",
            },
        },
    }


@pytest.fixture
def sample_runs_data():
    """Sample experimental runs data."""
    current_time = time.time()
    return {
        "run_001": {
            "run_id": "run_001",
            "ethoscope_id": "ETHOSCOPE_001",
            "start_time": current_time - 7200,  # 2 hours ago
            "end_time": None,  # Still running (crashed)
            "user_name": "researcher1",
            "location": "Incubator_A",
            "problems": "Device stopped responding after 2 hours",
            "experimental_data": json.dumps(
                {
                    "type": "tracking",
                    "fps": 30,
                    "roi_builder": "default",
                    "stimulus": "sleep_deprivation",
                    "metadata": {
                        "temperature": 25,
                        "humidity": 60,
                        "light_cycle": "12:12",
                    },
                }
            ),
        },
        "run_002": {
            "run_id": "run_002",
            "ethoscope_id": "ETHOSCOPE_002",
            "start_time": current_time - 86400,  # 1 day ago
            "end_time": current_time - 82800,  # 1 hour after start
            "user_name": "researcher2",
            "location": "Incubator_B",
            "problems": "",
            "experimental_data": json.dumps(
                {
                    "type": "recording",
                    "fps": 25,
                    "roi_builder": "sleep_annotation",
                    "stimulus": "optomotor",
                    "metadata": {
                        "temperature": 22,
                        "humidity": 55,
                        "light_cycle": "12:12",
                    },
                }
            ),
        },
        "run_003": {
            "run_id": "run_003",
            "ethoscope_id": "ETHOSCOPE_001",
            "start_time": current_time - 172800,  # 2 days ago
            "end_time": current_time - 86400,  # 1 day ago
            "user_name": "researcher1",
            "location": "Incubator_A",
            "problems": "",
            "experimental_data": json.dumps(
                {
                    "type": "tracking",
                    "fps": 30,
                    "roi_builder": "default",
                    "stimulus": "control",
                    "metadata": {
                        "temperature": 25,
                        "humidity": 60,
                        "light_cycle": "12:12",
                    },
                }
            ),
        },
        "run_004": {
            "run_id": "run_004",
            "ethoscope_id": "ETHOSCOPE_003",
            "start_time": current_time - 259200,  # 3 days ago
            "end_time": current_time - 172800,  # 2 days ago
            "user_name": "researcher2",
            "location": "Incubator_C",
            "problems": "Completed successfully",
            "experimental_data": json.dumps(
                {
                    "type": "tracking",
                    "fps": 30,
                    "roi_builder": "sleep_annotation",
                    "stimulus": "mechanical",
                    "metadata": {
                        "temperature": 20,
                        "humidity": 50,
                        "light_cycle": "16:8",
                    },
                }
            ),
        },
    }


@pytest.fixture
def sample_device_logs():
    """Sample device log data."""
    return {
        "ETHOSCOPE_001": """
2024-01-01 10:00:00 - INFO - Device startup initiated
2024-01-01 10:00:01 - INFO - Camera module initialized
2024-01-01 10:00:02 - INFO - ROI builder loaded: default
2024-01-01 10:00:03 - INFO - Tracking thread started
2024-01-01 10:00:04 - INFO - Experimental run started: run_001
2024-01-01 11:30:00 - WARNING - High CPU usage detected: 95%
2024-01-01 11:30:01 - WARNING - Frame rate dropped to 25 fps
2024-01-01 12:00:00 - ERROR - Network connection timeout
2024-01-01 12:00:01 - ERROR - Failed to save tracking data
2024-01-01 12:00:02 - CRITICAL - Device stopped responding
2024-01-01 12:00:03 - CRITICAL - Tracking thread terminated
        """,
        "ETHOSCOPE_002": """
2024-01-01 09:00:00 - INFO - Device startup initiated
2024-01-01 09:00:01 - INFO - Camera module initialized
2024-01-01 09:00:02 - INFO - ROI builder loaded: sleep_annotation
2024-01-01 09:00:03 - INFO - Recording thread started
2024-01-01 09:00:04 - INFO - Experimental run started: run_002
2024-01-01 10:00:00 - INFO - Recording completed successfully
2024-01-01 10:00:01 - INFO - Data saved to database
2024-01-01 10:00:02 - INFO - Device shutdown initiated
2024-01-01 10:00:03 - INFO - Clean shutdown completed
        """,
        "ETHOSCOPE_003": """
2024-01-01 08:00:00 - INFO - Device startup initiated
2024-01-01 08:00:01 - ERROR - Camera initialization failed
2024-01-01 08:00:02 - ERROR - Retrying camera initialization
2024-01-01 08:00:03 - ERROR - Camera initialization failed after 3 attempts
2024-01-01 08:00:04 - CRITICAL - Device offline for maintenance
        """,
    }


@pytest.fixture
def sample_device_status():
    """Sample device status data."""
    current_time = time.time()
    return {
        "ETHOSCOPE_001": {
            "status": "error",
            "monitor_info": {
                "last_time_stamp": current_time - 3600,  # 1 hour ago
                "fps": 0,
                "frame_count": 216000,
            },
            "experimental_info": {
                "run_id": "run_001",
                "name": "researcher1",
                "location": "Incubator_A",
                "start_time": current_time - 7200,
            },
            "database_info": {
                "database_name": "ethoscope_db_001",
                "table_count": 5,
                "last_update": current_time - 3600,
            },
            "machine_info": {
                "hostname": "ethoscope-001",
                "platform": "linux",
                "version": "1.2.3",
            },
        },
        "ETHOSCOPE_002": {
            "status": "stopped",
            "monitor_info": {
                "last_time_stamp": current_time - 82800,  # When it finished
                "fps": 0,
                "frame_count": 90000,
            },
            "experimental_info": {
                "run_id": "run_002",
                "name": "researcher2",
                "location": "Incubator_B",
                "start_time": current_time - 86400,
                "end_time": current_time - 82800,
            },
            "database_info": {
                "database_name": "ethoscope_db_002",
                "table_count": 3,
                "last_update": current_time - 82800,
            },
            "machine_info": {
                "hostname": "ethoscope-002",
                "platform": "linux",
                "version": "1.2.3",
            },
        },
    }


@pytest.fixture
def mock_configuration_service(sample_ethoscope_config):
    """Mock configuration service."""
    mock_config = Mock()
    mock_config.content = sample_ethoscope_config
    return mock_config


@pytest.fixture
def mock_database_service(sample_ethoscope_data, sample_runs_data):
    """Mock database service."""
    mock_db = Mock()

    def mock_get_ethoscope(device_id, asdict=False):
        return sample_ethoscope_data.get(device_id)

    def mock_get_run(run_id, asdict=False):
        if run_id == "all":
            return sample_runs_data
        return sample_runs_data.get(run_id)

    mock_db.getEthoscope = Mock(side_effect=mock_get_ethoscope)
    mock_db.getRun = Mock(side_effect=mock_get_run)

    return mock_db


@pytest.fixture
def mock_smtp_server():
    """Mock SMTP server for email testing."""
    mock_server = Mock()
    mock_server.starttls = Mock()
    mock_server.login = Mock()
    mock_server.send_message = Mock()
    mock_server.quit = Mock()
    return mock_server


@pytest.fixture
def mock_requests_response():
    """Mock requests response for HTTP calls."""

    def create_response(status_code=200, json_data=None, text_data=None):
        response = Mock()
        response.status_code = status_code
        if json_data:
            response.json = Mock(return_value=json_data)
        if text_data:
            response.text = text_data
        return response

    return create_response


@pytest.fixture
def notification_test_data():
    """Complete test data package for notification tests."""
    return {
        "devices": {
            "active_device": {
                "id": "ETHOSCOPE_001",
                "name": "ETHOSCOPE_001",
                "ip": "192.168.1.100",
                "status": "running",
                "last_seen": time.time() - 60,
            },
            "failed_device": {
                "id": "ETHOSCOPE_002",
                "name": "ETHOSCOPE_002",
                "ip": "192.168.1.101",
                "status": "error",
                "last_seen": time.time() - 3600,
            },
            "offline_device": {
                "id": "ETHOSCOPE_003",
                "name": "ETHOSCOPE_003",
                "ip": "192.168.1.102",
                "status": "offline",
                "last_seen": time.time() - 86400,
            },
        },
        "experiments": {
            "active_experiment": {
                "run_id": "run_001",
                "device_id": "ETHOSCOPE_001",
                "user": "researcher1",
                "type": "tracking",
                "status": "running",
                "duration": 7200,
            },
            "failed_experiment": {
                "run_id": "run_002",
                "device_id": "ETHOSCOPE_002",
                "user": "researcher2",
                "type": "recording",
                "status": "failed",
                "duration": 1800,
            },
            "completed_experiment": {
                "run_id": "run_003",
                "device_id": "ETHOSCOPE_001",
                "user": "researcher1",
                "type": "tracking",
                "status": "completed",
                "duration": 3600,
            },
        },
        "users": {
            "researcher1": {
                "email": "researcher1@example.com",
                "name": "Dr. Alice Researcher",
                "isAdmin": False,
            },
            "researcher2": {
                "email": "researcher2@example.com",
                "name": "Dr. Bob Scientist",
                "isAdmin": False,
            },
            "admin": {
                "email": "admin@example.com",
                "name": "System Administrator",
                "isAdmin": True,
            },
        },
    }


class MockNotificationService:
    """Mock notification service for testing."""

    def __init__(self):
        self.sent_notifications = []
        self.failed_notifications = []

    def send_notification(self, notification_type, device_id, **kwargs):
        """Mock send notification method."""
        notification = {
            "type": notification_type,
            "device_id": device_id,
            "timestamp": datetime.datetime.now(),
            "kwargs": kwargs,
        }

        # Simulate some failures for testing
        if device_id == "FAIL_DEVICE":
            self.failed_notifications.append(notification)
            return False

        self.sent_notifications.append(notification)
        return True

    def get_sent_notifications(self):
        """Get list of sent notifications."""
        return self.sent_notifications

    def get_failed_notifications(self):
        """Get list of failed notifications."""
        return self.failed_notifications

    def clear_notifications(self):
        """Clear notification history."""
        self.sent_notifications = []
        self.failed_notifications = []


@pytest.fixture
def mock_notification_service():
    """Mock notification service fixture."""
    return MockNotificationService()


# Slack-specific fixtures


@pytest.fixture
def slack_webhook_config():
    """Slack webhook configuration for testing."""
    return {
        "slack": {
            "enabled": True,
            "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
            "channel": "#ethoscope-alerts",
            "use_webhook": True,
        },
        "alerts": {"cooldown_seconds": 300},
    }


@pytest.fixture
def slack_bot_token_config():
    """Slack bot token configuration for testing."""
    return {
        "slack": {
            "enabled": True,
            "bot_token": "fake_bot_token_for_testing_only",
            "channel": "#ethoscope-alerts",
            "use_webhook": False,
        },
        "alerts": {"cooldown_seconds": 300},
    }


@pytest.fixture
def slack_disabled_config():
    """Disabled Slack configuration for testing."""
    return {
        "slack": {
            "enabled": False,
            "webhook_url": "",
            "bot_token": "",
            "channel": "",
            "use_webhook": True,
        },
        "alerts": {"cooldown_seconds": 300},
    }


@pytest.fixture
def slack_webhook_response_success():
    """Mock successful Slack webhook response."""
    response = Mock()
    response.status_code = 200
    response.text = "ok"
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def slack_webhook_response_failure():
    """Mock failed Slack webhook response."""
    response = Mock()
    response.status_code = 200
    response.text = "invalid_payload"
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def slack_bot_api_response_success():
    """Mock successful Slack bot API response."""
    response = Mock()
    response.status_code = 200
    response.json = Mock(return_value={"ok": True, "ts": "1234567890.123456"})
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def slack_bot_api_response_failure():
    """Mock failed Slack bot API response."""
    response = Mock()
    response.status_code = 200
    response.json = Mock(return_value={"ok": False, "error": "channel_not_found"})
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def sample_slack_blocks_device_stopped():
    """Sample Slack blocks for device stopped alert."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 Device Alert: Test Device stopped",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Device:* Test Device (ETHOSCOPE_001)"},
                {"type": "mrkdwn", "text": "*Status:* Failed while running"},
                {"type": "mrkdwn", "text": "*Run ID:* run_001"},
                {"type": "mrkdwn", "text": "*Last Seen:* 2024-01-01 12:00:00"},
            ],
        },
    ]


@pytest.fixture
def sample_slack_blocks_storage_warning():
    """Sample Slack blocks for storage warning alert."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚠️ Storage Warning: Test Device",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Device:* Test Device (ETHOSCOPE_001)"},
                {"type": "mrkdwn", "text": "*Storage Used:* 85.5%"},
                {"type": "mrkdwn", "text": "*Available Space:* 2.1 GB"},
                {"type": "mrkdwn", "text": "*Status:* 🟡 Warning"},
            ],
        },
    ]


@pytest.fixture
def sample_slack_blocks_device_unreachable():
    """Sample Slack blocks for device unreachable alert."""
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📵 Device Unreachable: Test Device",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*Device:* Test Device (ETHOSCOPE_001)"},
                {"type": "mrkdwn", "text": "*Last Seen:* 2024-01-01 10:00:00"},
                {"type": "mrkdwn", "text": "*Offline Duration:* 2.0 hours"},
                {"type": "mrkdwn", "text": "*Status:* 🔴 Offline"},
            ],
        },
    ]


class MockSlackService:
    """Mock Slack service for comprehensive testing."""

    def __init__(self, config=None):
        self.config = config or {}
        self.sent_messages = []
        self.failed_messages = []
        self.webhook_calls = []
        self.bot_api_calls = []

    def send_webhook_message(self, blocks, text=None):
        """Mock webhook message sending."""
        call_data = {
            "method": "webhook",
            "blocks": blocks,
            "text": text,
            "timestamp": datetime.datetime.now(),
        }
        self.webhook_calls.append(call_data)

        # Simulate failure for certain conditions
        if text and "FAIL" in text:
            self.failed_messages.append(call_data)
            return False

        self.sent_messages.append(call_data)
        return True

    def send_bot_api_message(self, blocks, text=None, channel=None):
        """Mock bot API message sending."""
        call_data = {
            "method": "bot_api",
            "blocks": blocks,
            "text": text,
            "channel": channel,
            "timestamp": datetime.datetime.now(),
        }
        self.bot_api_calls.append(call_data)

        # Simulate failure for certain conditions
        if channel and "invalid" in channel:
            self.failed_messages.append(call_data)
            return False

        self.sent_messages.append(call_data)
        return True

    def get_sent_messages(self):
        """Get all sent messages."""
        return self.sent_messages

    def get_failed_messages(self):
        """Get all failed messages."""
        return self.failed_messages

    def get_webhook_calls(self):
        """Get all webhook calls."""
        return self.webhook_calls

    def get_bot_api_calls(self):
        """Get all bot API calls."""
        return self.bot_api_calls

    def clear_history(self):
        """Clear all call history."""
        self.sent_messages = []
        self.failed_messages = []
        self.webhook_calls = []
        self.bot_api_calls = []


@pytest.fixture
def mock_slack_service():
    """Mock Slack service fixture."""
    return MockSlackService()


@pytest.fixture
def complete_notification_config():
    """Complete notification configuration with all services enabled."""
    return {
        "smtp": {
            "enabled": True,
            "host": "smtp.example.com",
            "port": 587,
            "username": "ethoscope@example.com",
            "password": "secure_password",
            "from_email": "ethoscope@example.com",
            "use_tls": True,
        },
        "mattermost": {
            "enabled": True,
            "server_url": "https://mattermost.example.com",
            "bot_token": "mmtoken123456789",
            "channel_id": "channel123456789",
        },
        "slack": {
            "enabled": True,
            "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
            "channel": "#ethoscope-alerts",
            "use_webhook": True,
        },
        "alerts": {"cooldown_seconds": 300, "storage_warning_threshold": 80},
        "users": {
            "researcher1": {
                "email": "researcher1@example.com",
                "isAdmin": False,
                "active": True,
                "name": "Dr. Alice Researcher",
            },
            "admin": {
                "email": "admin@example.com",
                "isAdmin": True,
                "active": True,
                "name": "System Administrator",
            },
        },
    }
