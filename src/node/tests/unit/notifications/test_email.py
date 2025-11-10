#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Unit tests for the email notification service.
"""

import pytest
import datetime
import time
import smtplib
from unittest.mock import Mock, patch, MagicMock, call
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from ethoscope_node.notifications.email import EmailNotificationService


class TestEmailNotificationService:
    """Test cases for EmailNotificationService class."""
    
    @pytest.fixture
    def mock_config(self):
        """Mock configuration object."""
        config = Mock()
        config.content = {
            'smtp': {
                'enabled': True,
                'host': 'smtp.example.com',
                'port': 587,
                'username': 'test@example.com',
                'password': 'test_password',
                'from_email': 'ethoscope@example.com',
                'use_tls': True
            },
            'alerts': {
                'cooldown_seconds': 300
            },
            'users': {
                'test_user': {
                    'email': 'test@example.com',
                    'isAdmin': False,
                    'active': True
                },
                'admin_user': {
                    'email': 'admin@example.com',
                    'isAdmin': True,
                    'active': True
                }
            }
        }
        return config
    
    @pytest.fixture
    def mock_db(self):
        """Mock database object."""
        db = Mock()
        return db
    
    @pytest.fixture
    def email_service(self, mock_config, mock_db):
        """Create email service instance with mocked dependencies."""
        return EmailNotificationService(config=mock_config, db=mock_db)
    
    def test_init_inherits_from_base(self, email_service):
        """Test that EmailNotificationService inherits from NotificationAnalyzer."""
        from ethoscope_node.notifications.base import NotificationAnalyzer
        assert isinstance(email_service, NotificationAnalyzer)
        assert hasattr(email_service, '_last_alert_times')
        assert hasattr(email_service, '_default_cooldown')
        assert email_service._default_cooldown == 3600
    
    def test_get_smtp_config(self, email_service):
        """Test SMTP configuration retrieval."""
        config = email_service._get_smtp_config()
        
        assert config['enabled'] == True
        assert config['host'] == 'smtp.example.com'
        assert config['port'] == 587
        assert config['username'] == 'test@example.com'
    
    def test_get_alert_config(self, email_service):
        """Test alert configuration retrieval."""
        config = email_service._get_alert_config()
        
        assert config['cooldown_seconds'] == 300
    
    def test_should_send_alert_first_time(self, email_service):
        """Test that alert should be sent the first time."""
        result = email_service._should_send_alert('device_001', 'device_stopped')
        
        assert result == True
        assert 'device_001:device_stopped' in email_service._last_alert_times
    
    def test_should_send_alert_cooldown_active(self, email_service):
        """Test that alert should not be sent during cooldown period."""
        device_id = 'device_001'
        alert_type = 'device_stopped'
        
        # Send first alert
        email_service._should_send_alert(device_id, alert_type)
        
        # Try to send again immediately - should be blocked
        result = email_service._should_send_alert(device_id, alert_type)
        
        assert result == False
    
    def test_should_send_alert_cooldown_expired(self, email_service):
        """Test that alert should be sent after cooldown expires."""
        device_id = 'device_001'
        alert_type = 'device_stopped'
        
        # Send first alert
        email_service._should_send_alert(device_id, alert_type)
        
        # Manually set last alert time to past
        email_service._last_alert_times[f'{device_id}:{alert_type}'] = time.time() - 400
        
        # Should be able to send again
        result = email_service._should_send_alert(device_id, alert_type)
        
        assert result == True
    
    def test_create_email_message_basic(self, email_service):
        """Test basic email message creation."""
        to_emails = ['test@example.com']
        subject = 'Test Subject'
        html_body = '<html><body><h1>Test</h1></body></html>'
        text_body = 'Test message'
        
        msg = email_service._create_email_message(to_emails, subject, html_body, text_body)
        
        assert isinstance(msg, MIMEMultipart)
        assert msg['To'] == 'test@example.com'
        assert msg['Subject'] == subject
        assert msg['From'] == 'ethoscope@example.com'
        assert msg['Date'] is not None
        
        # Check that it has both text and HTML parts
        payload = msg.get_payload()
        assert len(payload) >= 1  # At least the alternative container
        
        alternative_container = payload[0]
        alt_payload = alternative_container.get_payload()
        assert len(alt_payload) == 2  # Text and HTML parts
    
    def test_create_email_message_with_attachments(self, email_service):
        """Test email message creation with attachments."""
        to_emails = ['test@example.com']
        subject = 'Test Subject'
        html_body = '<html><body><h1>Test</h1></body></html>'
        text_body = 'Test message'
        attachments = [
            {
                'filename': 'test.log',
                'content': 'Log content here',
                'content_type': 'text/plain'
            }
        ]
        
        msg = email_service._create_email_message(to_emails, subject, html_body, text_body, attachments)
        
        # Should have alternative container + attachment
        payload = msg.get_payload()
        assert len(payload) == 2  # Alternative container + attachment
        
        # Check attachment
        attachment = payload[1]
        assert isinstance(attachment, MIMEApplication)
    
    def test_create_email_message_multiple_recipients(self, email_service):
        """Test email message creation with multiple recipients."""
        to_emails = ['test1@example.com', 'test2@example.com']
        subject = 'Test Subject'
        html_body = '<html><body><h1>Test</h1></body></html>'
        text_body = 'Test message'
        
        msg = email_service._create_email_message(to_emails, subject, html_body, text_body)
        
        assert msg['To'] == 'test1@example.com, test2@example.com'
    
    @patch('ethoscope_node.notifications.email.smtplib.SMTP')
    def test_send_email_success_starttls(self, mock_smtp, email_service):
        """Test successful email sending with STARTTLS."""
        mock_server = Mock()
        mock_smtp.return_value = mock_server
        
        msg = MIMEMultipart()
        msg['To'] = 'test@example.com'
        msg['Subject'] = 'Test'
        
        result = email_service._send_email(msg)
        
        assert result == True
        mock_smtp.assert_called_once_with('smtp.example.com', 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with('test@example.com', 'test_password')
        mock_server.send_message.assert_called_once_with(msg)
        mock_server.quit.assert_called_once()
    
    @patch('ethoscope_node.notifications.email.smtplib.SMTP_SSL')
    def test_send_email_success_ssl(self, mock_smtp_ssl, email_service):
        """Test successful email sending with SSL."""
        # Override config to use SSL port
        email_service.config.content['smtp']['port'] = 465
        
        mock_server = Mock()
        mock_smtp_ssl.return_value = mock_server
        
        msg = MIMEMultipart()
        msg['To'] = 'test@example.com'
        msg['Subject'] = 'Test'
        
        result = email_service._send_email(msg)
        
        assert result == True
        mock_smtp_ssl.assert_called_once_with('smtp.example.com', 465)
        mock_server.starttls.assert_not_called()  # SSL doesn't use STARTTLS
        mock_server.login.assert_called_once_with('test@example.com', 'test_password')
        mock_server.send_message.assert_called_once_with(msg)
        mock_server.quit.assert_called_once()
    
    @patch('ethoscope_node.notifications.email.smtplib.SMTP')
    def test_send_email_disabled(self, mock_smtp, email_service):
        """Test email sending when disabled in config."""
        email_service.config.content['smtp']['enabled'] = False
        
        msg = MIMEMultipart()
        msg['To'] = 'test@example.com'
        msg['Subject'] = 'Test'
        
        result = email_service._send_email(msg)
        
        assert result == False
        mock_smtp.assert_not_called()
    
    @patch('ethoscope_node.notifications.email.smtplib.SMTP')
    def test_send_email_exception(self, mock_smtp, email_service):
        """Test email sending when SMTP raises exception."""
        mock_smtp.side_effect = Exception("SMTP error")
        
        msg = MIMEMultipart()
        msg['To'] = 'test@example.com'
        msg['Subject'] = 'Test'
        
        result = email_service._send_email(msg)
        
        assert result == False
    
    @patch('ethoscope_node.notifications.email.smtplib.SMTP')
    def test_send_email_no_credentials(self, mock_smtp, email_service):
        """Test email sending without credentials."""
        # Remove credentials from config
        email_service.config.content['smtp']['username'] = None
        email_service.config.content['smtp']['password'] = None
        
        mock_server = Mock()
        mock_smtp.return_value = mock_server
        
        msg = MIMEMultipart()
        msg['To'] = 'test@example.com'
        msg['Subject'] = 'Test'
        
        result = email_service._send_email(msg)
        
        assert result == True
        mock_server.login.assert_not_called()  # No login without credentials
        mock_server.send_message.assert_called_once_with(msg)
    
    @patch.object(EmailNotificationService, '_send_email')
    @patch.object(EmailNotificationService, 'get_device_logs')
    @patch.object(EmailNotificationService, 'analyze_device_failure')
    @patch.object(EmailNotificationService, 'get_stopped_experiment_user')
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_send_device_stopped_alert_success(self, mock_get_admin, mock_get_stopped_user,
                                             mock_analyze, mock_get_logs, mock_send, email_service):
        """Test successful device stopped alert."""
        device_id = 'device_001'
        device_name = 'Test Device'
        run_id = 'run_123'
        last_seen = datetime.datetime.now()

        # Mock return values
        mock_get_stopped_user.return_value = ['user@example.com']
        mock_get_admin.return_value = ['admin@example.com']
        mock_analyze.return_value = {
            'failure_type': 'crashed_during_tracking',
            'user': 'test_user',
            'location': 'Incubator_A',
            'experiment_duration_str': '2.5 hours',
            'experiment_type': 'tracking',
            'status': 'Failed while running',
            'start_time': datetime.datetime.now() - datetime.timedelta(hours=2),
            'problems': 'Network timeout',
            'device_problems': 'Camera issue'
        }
        mock_get_logs.return_value = 'Log line 1\nLog line 2\nError occurred'
        mock_send.return_value = True

        # Mock database methods
        with patch.object(email_service.db, 'hasAlertBeenSent', return_value=False), \
             patch.object(email_service.db, 'logAlert', return_value=1):
            result = email_service.send_device_stopped_alert(device_id, device_name, run_id, last_seen)

            assert result == True
            mock_get_stopped_user.assert_called_once_with(run_id)
            mock_get_admin.assert_called_once()
            mock_analyze.assert_called_once_with(device_id)
            mock_get_logs.assert_called_once_with(device_id, max_lines=500)
            mock_send.assert_called_once()
            
            # Check that email was created with correct content
            call_args = mock_send.call_args[0][0]  # Get the message argument
            assert 'Test Device' in call_args['Subject']
            to_addresses = call_args['To']
            assert 'user@example.com' in to_addresses
            assert 'admin@example.com' in to_addresses
        
        # Check that email has attachments
        payload = call_args.get_payload()
        assert len(payload) == 2  # Alternative container + attachment
    
    @patch.object(EmailNotificationService, '_should_send_alert')
    def test_send_device_stopped_alert_cooldown(self, mock_should_send, email_service):
        """Test device stopped alert blocked by cooldown."""
        mock_should_send.return_value = False

        result = email_service.send_device_stopped_alert('device_001', 'Test Device', 'run_123', datetime.datetime.now())

        assert result == False
        mock_should_send.assert_called_once_with('device_001', 'device_stopped', 'run_123')

    @patch.object(EmailNotificationService, 'analyze_device_failure')
    @patch.object(EmailNotificationService, '_should_send_alert')
    def test_send_device_stopped_alert_completed_normally(self, mock_should_send, mock_analyze, email_service):
        """Test device stopped alert suppressed for normally completed runs."""
        mock_should_send.return_value = True
        mock_analyze.return_value = {
            'failure_type': 'completed_normally',
            'status': 'Completed normally',
            'user': 'test_user',
            'location': 'Incubator_A',
            'experiment_duration_str': '3.1 days',
            'experiment_type': 'tracking'
        }

        result = email_service.send_device_stopped_alert('device_001', 'Test Device', 'run_123', datetime.datetime.now())

        assert result == False
        mock_should_send.assert_called_once_with('device_001', 'device_stopped', 'run_123')
        mock_analyze.assert_called_once_with('device_001')

    @patch.object(EmailNotificationService, 'get_device_users')
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_send_device_stopped_alert_no_recipients(self, mock_get_admin, mock_get_users, email_service):
        """Test device stopped alert with no recipients."""
        mock_get_users.return_value = []
        mock_get_admin.return_value = []
        
        result = email_service.send_device_stopped_alert('device_001', 'Test Device', 'run_123', datetime.datetime.now())
        
        assert result == False
    
    @patch.object(EmailNotificationService, '_send_email')
    @patch.object(EmailNotificationService, 'get_device_users')
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_send_storage_warning_alert_success(self, mock_get_admin, mock_get_users, mock_send, email_service):
        """Test successful storage warning alert."""
        device_id = 'device_001'
        device_name = 'Test Device'
        storage_percent = 85.5
        available_space = '2.1 GB'
        
        mock_get_users.return_value = ['user@example.com']
        mock_get_admin.return_value = ['admin@example.com']
        mock_send.return_value = True
        
        result = email_service.send_storage_warning_alert(device_id, device_name, storage_percent, available_space)
        
        assert result == True
        mock_send.assert_called_once()
        
        # Check email content
        call_args = mock_send.call_args[0][0]
        assert 'storage warning' in call_args['Subject']
        assert '85.5%' in call_args['Subject']
        assert '2.1 GB' in str(call_args)
    
    @patch.object(EmailNotificationService, '_send_email')
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_send_device_unreachable_alert_success(self, mock_get_admin, mock_send, email_service):
        """Test successful device unreachable alert."""
        device_id = 'device_001'
        device_name = 'Test Device'
        last_seen = datetime.datetime.now()
        
        mock_get_admin.return_value = ['admin@example.com']
        mock_send.return_value = True
        
        result = email_service.send_device_unreachable_alert(device_id, device_name, last_seen)
        
        assert result == True
        mock_send.assert_called_once()
        
        # Check email content
        call_args = mock_send.call_args[0][0]
        assert 'unreachable' in call_args['Subject']
        assert 'admin@example.com' in call_args['To']
    
    @patch.object(EmailNotificationService, '_send_email')
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_test_email_configuration_success(self, mock_get_admin, mock_send, email_service):
        """Test successful email configuration test."""
        mock_get_admin.return_value = ['admin@example.com']
        mock_send.return_value = True
        
        result = email_service.test_email_configuration()
        
        assert result['success'] == True
        assert result['recipients'] == ['admin@example.com']
        assert result['smtp_host'] == 'smtp.example.com'
        assert result['smtp_port'] == 587
        mock_send.assert_called_once()
    
    def test_test_email_configuration_disabled(self, email_service):
        """Test email configuration test when disabled."""
        email_service.config.content['smtp']['enabled'] = False
        
        result = email_service.test_email_configuration()
        
        assert result['success'] == False
        assert 'disabled' in result['error']
    
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_test_email_configuration_no_admins(self, mock_get_admin, email_service):
        """Test email configuration test with no admin emails."""
        mock_get_admin.return_value = []
        
        result = email_service.test_email_configuration()
        
        assert result['success'] == False
        assert 'No admin email addresses' in result['error']
    
    @patch.object(EmailNotificationService, '_send_email')
    @patch.object(EmailNotificationService, 'get_admin_emails')
    def test_test_email_configuration_exception(self, mock_get_admin, mock_send, email_service):
        """Test email configuration test when exception occurs."""
        mock_get_admin.return_value = ['admin@example.com']
        mock_send.side_effect = Exception("SMTP error")
        
        result = email_service.test_email_configuration()
        
        assert result['success'] == False
        assert 'SMTP error' in result['error']
    
    def test_email_service_inherits_all_base_methods(self, email_service):
        """Test that email service has all base analyzer methods."""
        # Check that key methods from base class are available
        assert hasattr(email_service, 'analyze_device_failure')
        assert hasattr(email_service, 'get_device_logs')
        assert hasattr(email_service, 'get_device_status_info')
        assert hasattr(email_service, 'get_device_users')
        assert hasattr(email_service, 'get_admin_emails')
        assert hasattr(email_service, '_format_duration')
    
    @patch.object(EmailNotificationService, 'get_device_logs')
    @patch.object(EmailNotificationService, 'analyze_device_failure')
    def test_send_device_stopped_alert_without_logs(self, mock_analyze, mock_get_logs, email_service):
        """Test device stopped alert when logs are not available."""
        mock_analyze.return_value = {
            'failure_type': 'crashed_during_tracking',
            'user': 'test_user',
            'location': 'Incubator_A',
            'experiment_duration_str': '2.5 hours',
            'experiment_type': 'tracking',
            'status': 'Failed while running',
            'start_time': datetime.datetime.now(),
            'problems': '',
            'device_problems': ''
        }
        mock_get_logs.return_value = None  # No logs available
        
        # Mock other dependencies
        with patch.object(email_service, 'get_device_users', return_value=['user@example.com']), \
             patch.object(email_service, 'get_admin_emails', return_value=['admin@example.com']), \
             patch.object(email_service, '_send_email', return_value=True) as mock_send, \
             patch.object(email_service.db, 'hasAlertBeenSent', return_value=False), \
             patch.object(email_service.db, 'logAlert', return_value=1):
            
            result = email_service.send_device_stopped_alert('device_001', 'Test Device', 'run_123', datetime.datetime.now())
            
            assert result == True
            
            # Check that email was created without attachments
            call_args = mock_send.call_args[0][0]
            payload = call_args.get_payload()
            assert len(payload) == 1  # Only alternative container, no attachments