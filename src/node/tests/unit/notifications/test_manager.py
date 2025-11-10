#!/usr/bin/env python

"""
Unit tests for the unified notification manager.
"""

import datetime
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from ethoscope_node.notifications.manager import NotificationManager


class TestNotificationManager:
    """Test cases for NotificationManager class."""

    @pytest.fixture
    def mock_config_both_enabled(self):
        """Mock configuration with both email and Mattermost enabled."""
        config = Mock()
        config.content = {
            "smtp": {
                "enabled": True,
                "host": "smtp.example.com",
                "port": 587,
                "username": "test@example.com",
                "password": "password",
                "from_email": "ethoscope@example.com",
            },
            "mattermost": {
                "enabled": True,
                "server_url": "https://mattermost.example.com",
                "bot_token": "token123",
                "channel_id": "channel123",
            },
            "slack": {
                "enabled": False,
                "webhook_url": "",
                "bot_token": "",
                "channel": "",
            },
            "alerts": {"cooldown_seconds": 300},
        }
        return config

    @pytest.fixture
    def mock_config_email_only(self):
        """Mock configuration with only email enabled."""
        config = Mock()
        config.content = {
            "smtp": {
                "enabled": True,
                "host": "smtp.example.com",
                "port": 587,
                "username": "test@example.com",
                "password": "password",
                "from_email": "ethoscope@example.com",
            },
            "mattermost": {
                "enabled": False,
                "server_url": "",
                "bot_token": "",
                "channel_id": "",
            },
            "slack": {
                "enabled": False,
                "webhook_url": "",
                "bot_token": "",
                "channel": "",
            },
            "alerts": {"cooldown_seconds": 300},
        }
        return config

    @pytest.fixture
    def mock_config_none_enabled(self):
        """Mock configuration with no services enabled."""
        config = Mock()
        config.content = {
            "smtp": {"enabled": False, "host": "smtp.example.com", "port": 587},
            "mattermost": {
                "enabled": False,
                "server_url": "",
                "bot_token": "",
                "channel_id": "",
            },
            "slack": {
                "enabled": False,
                "webhook_url": "",
                "bot_token": "",
                "channel": "",
            },
            "alerts": {"cooldown_seconds": 300},
        }
        return config

    @pytest.fixture
    def mock_config_all_enabled(self):
        """Mock configuration with all services enabled."""
        config = Mock()
        config.content = {
            "smtp": {
                "enabled": True,
                "host": "smtp.example.com",
                "port": 587,
                "username": "test@example.com",
                "password": "password",
                "from_email": "ethoscope@example.com",
            },
            "mattermost": {
                "enabled": True,
                "server_url": "https://mattermost.example.com",
                "bot_token": "token123",
                "channel_id": "channel123",
            },
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
                "channel": "#alerts",
                "use_webhook": True,
            },
            "alerts": {"cooldown_seconds": 300},
        }
        return config

    @pytest.fixture
    def mock_config_slack_only(self):
        """Mock configuration with only Slack enabled."""
        config = Mock()
        config.content = {
            "smtp": {"enabled": False, "host": "smtp.example.com", "port": 587},
            "mattermost": {
                "enabled": False,
                "server_url": "",
                "bot_token": "",
                "channel_id": "",
            },
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
                "channel": "#alerts",
                "use_webhook": True,
            },
            "alerts": {"cooldown_seconds": 300},
        }
        return config

    @pytest.fixture
    def mock_db(self):
        """Mock database object."""
        return Mock()

    @patch("ethoscope_node.notifications.manager.EmailNotificationService")
    @patch("ethoscope_node.notifications.manager.MattermostNotificationService")
    @patch("ethoscope_node.notifications.manager.SlackNotificationService")
    def test_init_both_services_enabled(
        self,
        mock_slack_cls,
        mock_mattermost_cls,
        mock_email_cls,
        mock_config_both_enabled,
        mock_db,
    ):
        """Test initialization with both email and Mattermost services enabled."""
        mock_email_service = Mock()
        mock_mattermost_service = Mock()
        mock_email_cls.return_value = mock_email_service
        mock_mattermost_cls.return_value = mock_mattermost_service

        manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

        assert len(manager._services) == 2
        service_names = [name for name, _ in manager._services]
        assert "email" in service_names
        assert "mattermost" in service_names
        assert "slack" not in service_names  # Slack is disabled in this config

        mock_email_cls.assert_called_once_with(mock_config_both_enabled, mock_db)
        mock_mattermost_cls.assert_called_once_with(mock_config_both_enabled, mock_db)
        mock_slack_cls.assert_not_called()

    @patch("ethoscope_node.notifications.manager.EmailNotificationService")
    @patch("ethoscope_node.notifications.manager.MattermostNotificationService")
    def test_init_email_only(
        self, mock_mattermost_cls, mock_email_cls, mock_config_email_only, mock_db
    ):
        """Test initialization with only email enabled."""
        mock_email_service = Mock()
        mock_email_cls.return_value = mock_email_service

        manager = NotificationManager(config=mock_config_email_only, db=mock_db)

        assert len(manager._services) == 1
        service_names = [name for name, _ in manager._services]
        assert "email" in service_names
        assert "mattermost" not in service_names

        mock_email_cls.assert_called_once_with(mock_config_email_only, mock_db)
        mock_mattermost_cls.assert_not_called()

    @patch("ethoscope_node.notifications.manager.EmailNotificationService")
    @patch("ethoscope_node.notifications.manager.MattermostNotificationService")
    def test_init_no_services_enabled(
        self, mock_mattermost_cls, mock_email_cls, mock_config_none_enabled, mock_db
    ):
        """Test initialization with no services enabled."""
        manager = NotificationManager(config=mock_config_none_enabled, db=mock_db)

        assert len(manager._services) == 0
        mock_email_cls.assert_not_called()
        mock_mattermost_cls.assert_not_called()

    def test_get_active_services(self, mock_config_both_enabled, mock_db):
        """Test getting list of active services."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)
            active_services = manager.get_active_services()

            assert len(active_services) == 2
            assert "email" in active_services
            assert "mattermost" in active_services

    def test_send_device_stopped_alert_both_services_success(
        self, mock_config_both_enabled, mock_db
    ):
        """Test device stopped alert with both services succeeding."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_email_service.send_device_stopped_alert.return_value = True
            mock_mattermost_service.send_device_stopped_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == True
            mock_email_service.send_device_stopped_alert.assert_called_once()
            mock_mattermost_service.send_device_stopped_alert.assert_called_once()

    def test_send_device_stopped_alert_partial_success(
        self, mock_config_both_enabled, mock_db
    ):
        """Test device stopped alert with one service failing."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_email_service.send_device_stopped_alert.return_value = False
            mock_mattermost_service.send_device_stopped_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == True  # Should succeed if at least one service works
            mock_email_service.send_device_stopped_alert.assert_called_once()
            mock_mattermost_service.send_device_stopped_alert.assert_called_once()

    def test_send_device_stopped_alert_all_fail(
        self, mock_config_both_enabled, mock_db
    ):
        """Test device stopped alert with all services failing."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_email_service.send_device_stopped_alert.return_value = False
            mock_mattermost_service.send_device_stopped_alert.return_value = False
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == False
            mock_email_service.send_device_stopped_alert.assert_called_once()
            mock_mattermost_service.send_device_stopped_alert.assert_called_once()

    def test_send_device_stopped_alert_no_services(
        self, mock_config_none_enabled, mock_db
    ):
        """Test device stopped alert with no services enabled."""
        manager = NotificationManager(config=mock_config_none_enabled, db=mock_db)

        result = manager.send_device_stopped_alert(
            device_id="test_device",
            device_name="Test Device",
            run_id="run123",
            last_seen=datetime.datetime.now(),
        )

        assert result == False

    def test_send_storage_warning_alert_success(
        self, mock_config_both_enabled, mock_db
    ):
        """Test storage warning alert with both services succeeding."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_email_service.send_storage_warning_alert.return_value = True
            mock_mattermost_service.send_storage_warning_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            result = manager.send_storage_warning_alert(
                device_id="test_device",
                device_name="Test Device",
                storage_percent=85.5,
                available_space="2.1 GB",
            )

            assert result == True
            mock_email_service.send_storage_warning_alert.assert_called_once()
            mock_mattermost_service.send_storage_warning_alert.assert_called_once()

    def test_send_device_unreachable_alert_success(
        self, mock_config_both_enabled, mock_db
    ):
        """Test device unreachable alert with both services succeeding."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_email_service.send_device_unreachable_alert.return_value = True
            mock_mattermost_service.send_device_unreachable_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            result = manager.send_device_unreachable_alert(
                device_id="test_device",
                device_name="Test Device",
                last_seen=datetime.datetime.now(),
            )

            assert result == True
            mock_email_service.send_device_unreachable_alert.assert_called_once()
            mock_mattermost_service.send_device_unreachable_alert.assert_called_once()

    def test_test_all_configurations(self, mock_config_both_enabled, mock_db):
        """Test configuration testing for all services."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_email_service.test_email_configuration.return_value = {"success": True}
            mock_mattermost_service.test_mattermost_configuration.return_value = {
                "success": True
            }
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            results = manager.test_all_configurations()

            assert "email" in results
            assert "mattermost" in results
            assert results["email"]["success"] == True
            assert results["mattermost"]["success"] == True
            mock_email_service.test_email_configuration.assert_called_once()
            mock_mattermost_service.test_mattermost_configuration.assert_called_once()

    def test_service_exception_handling(self, mock_config_both_enabled, mock_db):
        """Test that exceptions in one service don't affect others."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            # Email service throws exception, Mattermost succeeds
            mock_email_service.send_device_stopped_alert.side_effect = Exception(
                "SMTP error"
            )
            mock_mattermost_service.send_device_stopped_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == True  # Should succeed because Mattermost worked
            mock_email_service.send_device_stopped_alert.assert_called_once()
            mock_mattermost_service.send_device_stopped_alert.assert_called_once()

    def test_reload_configuration(self, mock_config_both_enabled, mock_db):
        """Test configuration reloading."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls:

            manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)
            initial_service_count = len(manager._services)

            # Mock config.load() method
            manager.config.load = Mock()

            manager.reload_configuration()

            manager.config.load.assert_called_once()
            # Services should be reinitialized
            assert len(manager._services) == initial_service_count

    def test_manager_inherits_from_base(self, mock_config_both_enabled, mock_db):
        """Test that NotificationManager inherits from NotificationAnalyzer."""
        from ethoscope_node.notifications.base import NotificationAnalyzer

        manager = NotificationManager(config=mock_config_both_enabled, db=mock_db)

        assert isinstance(manager, NotificationAnalyzer)
        # Check that base analyzer methods are available
        assert hasattr(manager, "analyze_device_failure")
        assert hasattr(manager, "get_device_logs")
        assert hasattr(manager, "get_device_users")
        assert hasattr(manager, "get_admin_emails")

    # New test cases for Slack integration

    @patch("ethoscope_node.notifications.manager.EmailNotificationService")
    @patch("ethoscope_node.notifications.manager.MattermostNotificationService")
    @patch("ethoscope_node.notifications.manager.SlackNotificationService")
    def test_init_all_services_enabled(
        self,
        mock_slack_cls,
        mock_mattermost_cls,
        mock_email_cls,
        mock_config_all_enabled,
        mock_db,
    ):
        """Test initialization with all three services enabled."""
        mock_email_service = Mock()
        mock_mattermost_service = Mock()
        mock_slack_service = Mock()
        mock_email_cls.return_value = mock_email_service
        mock_mattermost_cls.return_value = mock_mattermost_service
        mock_slack_cls.return_value = mock_slack_service

        manager = NotificationManager(config=mock_config_all_enabled, db=mock_db)

        assert len(manager._services) == 3
        service_names = [name for name, _ in manager._services]
        assert "email" in service_names
        assert "mattermost" in service_names
        assert "slack" in service_names

        mock_email_cls.assert_called_once_with(mock_config_all_enabled, mock_db)
        mock_mattermost_cls.assert_called_once_with(mock_config_all_enabled, mock_db)
        mock_slack_cls.assert_called_once_with(mock_config_all_enabled, mock_db)

    @patch("ethoscope_node.notifications.manager.EmailNotificationService")
    @patch("ethoscope_node.notifications.manager.MattermostNotificationService")
    @patch("ethoscope_node.notifications.manager.SlackNotificationService")
    def test_init_slack_only(
        self,
        mock_slack_cls,
        mock_mattermost_cls,
        mock_email_cls,
        mock_config_slack_only,
        mock_db,
    ):
        """Test initialization with only Slack enabled."""
        mock_slack_service = Mock()
        mock_slack_cls.return_value = mock_slack_service

        manager = NotificationManager(config=mock_config_slack_only, db=mock_db)

        assert len(manager._services) == 1
        service_names = [name for name, _ in manager._services]
        assert "slack" in service_names
        assert "email" not in service_names
        assert "mattermost" not in service_names

        mock_slack_cls.assert_called_once_with(mock_config_slack_only, mock_db)
        mock_email_cls.assert_not_called()
        mock_mattermost_cls.assert_not_called()

    def test_send_device_stopped_alert_all_services_success(
        self, mock_config_all_enabled, mock_db
    ):
        """Test device stopped alert with all three services succeeding."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls, patch(
            "ethoscope_node.notifications.manager.SlackNotificationService"
        ) as mock_slack_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_slack_service = Mock()
            mock_email_service.send_device_stopped_alert.return_value = True
            mock_mattermost_service.send_device_stopped_alert.return_value = True
            mock_slack_service.send_device_stopped_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service
            mock_slack_cls.return_value = mock_slack_service

            manager = NotificationManager(config=mock_config_all_enabled, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == True
            mock_email_service.send_device_stopped_alert.assert_called_once()
            mock_mattermost_service.send_device_stopped_alert.assert_called_once()
            mock_slack_service.send_device_stopped_alert.assert_called_once()

    def test_send_device_stopped_alert_slack_only_success(
        self, mock_config_slack_only, mock_db
    ):
        """Test device stopped alert with only Slack service succeeding."""
        with patch(
            "ethoscope_node.notifications.manager.SlackNotificationService"
        ) as mock_slack_cls:

            mock_slack_service = Mock()
            mock_slack_service.send_device_stopped_alert.return_value = True
            mock_slack_cls.return_value = mock_slack_service

            manager = NotificationManager(config=mock_config_slack_only, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == True
            mock_slack_service.send_device_stopped_alert.assert_called_once()

    def test_send_storage_warning_alert_all_services_mixed_results(
        self, mock_config_all_enabled, mock_db
    ):
        """Test storage warning alert with mixed success/failure across services."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls, patch(
            "ethoscope_node.notifications.manager.SlackNotificationService"
        ) as mock_slack_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_slack_service = Mock()
            # Email fails, Mattermost fails, Slack succeeds
            mock_email_service.send_storage_warning_alert.return_value = False
            mock_mattermost_service.send_storage_warning_alert.return_value = False
            mock_slack_service.send_storage_warning_alert.return_value = True
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service
            mock_slack_cls.return_value = mock_slack_service

            manager = NotificationManager(config=mock_config_all_enabled, db=mock_db)

            result = manager.send_storage_warning_alert(
                device_id="test_device",
                device_name="Test Device",
                storage_percent=85.5,
                available_space="2.1 GB",
            )

            assert result == True  # Should succeed if at least one service works
            mock_email_service.send_storage_warning_alert.assert_called_once()
            mock_mattermost_service.send_storage_warning_alert.assert_called_once()
            mock_slack_service.send_storage_warning_alert.assert_called_once()

    def test_test_all_configurations_with_slack(self, mock_config_all_enabled, mock_db):
        """Test configuration testing for all services including Slack."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls, patch(
            "ethoscope_node.notifications.manager.SlackNotificationService"
        ) as mock_slack_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_slack_service = Mock()
            mock_email_service.test_email_configuration.return_value = {"success": True}
            mock_mattermost_service.test_mattermost_configuration.return_value = {
                "success": True
            }
            mock_slack_service.test_slack_configuration.return_value = {"success": True}
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service
            mock_slack_cls.return_value = mock_slack_service

            manager = NotificationManager(config=mock_config_all_enabled, db=mock_db)

            results = manager.test_all_configurations()

            assert "email" in results
            assert "mattermost" in results
            assert "slack" in results
            assert results["email"]["success"] == True
            assert results["mattermost"]["success"] == True
            assert results["slack"]["success"] == True
            mock_email_service.test_email_configuration.assert_called_once()
            mock_mattermost_service.test_mattermost_configuration.assert_called_once()
            mock_slack_service.test_slack_configuration.assert_called_once()

    def test_service_exception_handling_with_slack(
        self, mock_config_all_enabled, mock_db
    ):
        """Test that exceptions in Slack service don't affect others."""
        with patch(
            "ethoscope_node.notifications.manager.EmailNotificationService"
        ) as mock_email_cls, patch(
            "ethoscope_node.notifications.manager.MattermostNotificationService"
        ) as mock_mattermost_cls, patch(
            "ethoscope_node.notifications.manager.SlackNotificationService"
        ) as mock_slack_cls:

            mock_email_service = Mock()
            mock_mattermost_service = Mock()
            mock_slack_service = Mock()
            # Email and Mattermost succeed, Slack throws exception
            mock_email_service.send_device_stopped_alert.return_value = True
            mock_mattermost_service.send_device_stopped_alert.return_value = True
            mock_slack_service.send_device_stopped_alert.side_effect = Exception(
                "Slack API error"
            )
            mock_email_cls.return_value = mock_email_service
            mock_mattermost_cls.return_value = mock_mattermost_service
            mock_slack_cls.return_value = mock_slack_service

            manager = NotificationManager(config=mock_config_all_enabled, db=mock_db)

            result = manager.send_device_stopped_alert(
                device_id="test_device",
                device_name="Test Device",
                run_id="run123",
                last_seen=datetime.datetime.now(),
            )

            assert result == True  # Should succeed because email and Mattermost worked
            mock_email_service.send_device_stopped_alert.assert_called_once()
            mock_mattermost_service.send_device_stopped_alert.assert_called_once()
            mock_slack_service.send_device_stopped_alert.assert_called_once()
