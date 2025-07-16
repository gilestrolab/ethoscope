#!/usr/bin/env python
# -*- coding: utf-8 -*-

import smtplib
import logging
import datetime
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate
from typing import Dict, Any, Optional, List
from .configuration import EthoscopeConfiguration
from .etho_db import ExperimentalDB


class EmailNotificationService:
    """
    Email notification service for Ethoscope system alerts.
    
    Handles sending email notifications for device events like:
    - Device stopped unexpectedly
    - Storage warnings (80% full)
    - Device unreachable
    - Long-running experiments
    """
    
    def __init__(self, config: Optional[EthoscopeConfiguration] = None, 
                 db: Optional[ExperimentalDB] = None):
        """
        Initialize email notification service.
        
        Args:
            config: Configuration instance, will create new one if None
            db: Database instance, will create new one if None
        """
        self.config = config or EthoscopeConfiguration()
        self.db = db or ExperimentalDB()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Rate limiting: track last alert time per device/type
        self._last_alert_times = {}
        self._default_cooldown = 3600  # 1 hour between similar alerts
        
    def _get_smtp_config(self) -> Dict[str, Any]:
        """Get SMTP configuration from settings."""
        return self.config.content.get('smtp', {})
    
    def _get_alert_config(self) -> Dict[str, Any]:
        """Get alert configuration from settings."""
        return self.config.content.get('alerts', {})
    
    def _should_send_alert(self, device_id: str, alert_type: str) -> bool:
        """
        Check if we should send an alert based on rate limiting.
        
        Args:
            device_id: Device identifier
            alert_type: Type of alert (device_stopped, storage_warning, etc.)
            
        Returns:
            True if alert should be sent
        """
        alert_config = self._get_alert_config()
        cooldown = alert_config.get('cooldown_seconds', self._default_cooldown)
        
        key = f"{device_id}:{alert_type}"
        current_time = time.time()
        
        if key in self._last_alert_times:
            time_since_last = current_time - self._last_alert_times[key]
            if time_since_last < cooldown:
                self.logger.debug(f"Alert {key} suppressed due to cooldown ({time_since_last:.0f}s < {cooldown}s)")
                return False
        
        self._last_alert_times[key] = current_time
        return True
    
    def _get_device_users(self, device_id: str) -> List[str]:
        """
        Get list of user email addresses associated with a device.
        
        Args:
            device_id: Device identifier
            
        Returns:
            List of email addresses
        """
        try:
            # Get recent runs for this device
            runs = self.db.getRun('all', asdict=True)
            
            user_emails = set()
            for run_id, run_data in runs.items():
                if run_data.get('ethoscope_id') == device_id:
                    user_name = run_data.get('user_name')
                    if user_name:
                        # Get user email from configuration
                        users = self.config.content.get('users', {})
                        if user_name in users:
                            email = users[user_name].get('email')
                            if email:
                                user_emails.add(email)
            
            return list(user_emails)
            
        except Exception as e:
            self.logger.error(f"Error getting device users for {device_id}: {e}")
            return []
    
    def _get_admin_emails(self) -> List[str]:
        """Get list of admin email addresses."""
        try:
            users = self.config.content.get('users', {})
            admin_emails = []
            
            for user_data in users.values():
                if user_data.get('isAdmin', False) and user_data.get('active', False):
                    email = user_data.get('email')
                    if email:
                        admin_emails.append(email)
            
            return admin_emails
            
        except Exception as e:
            self.logger.error(f"Error getting admin emails: {e}")
            return []
    
    def _create_email_message(self, to_emails: List[str], subject: str, 
                             html_body: str, text_body: str) -> MIMEMultipart:
        """
        Create email message with HTML and text parts.
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_body: HTML email body
            text_body: Plain text email body
            
        Returns:
            Email message object
        """
        smtp_config = self._get_smtp_config()
        from_email = smtp_config.get('from_email', 'ethoscope@localhost')
        
        msg = MIMEMultipart('alternative')
        msg['From'] = from_email
        msg['To'] = ', '.join(to_emails)
        msg['Subject'] = subject
        msg['Date'] = formatdate(localtime=True)
        
        # Add text and HTML parts
        text_part = MIMEText(text_body, 'plain')
        html_part = MIMEText(html_body, 'html')
        
        msg.attach(text_part)
        msg.attach(html_part)
        
        return msg
    
    def _send_email(self, msg: MIMEMultipart) -> bool:
        """
        Send email message via SMTP.
        
        Args:
            msg: Email message to send
            
        Returns:
            True if email was sent successfully
        """
        smtp_config = self._get_smtp_config()
        
        if not smtp_config.get('enabled', False):
            self.logger.info("Email notifications disabled in configuration")
            return False
        
        try:
            port = smtp_config.get('port', 587)
            host = smtp_config.get('host', 'localhost')
            
            # Auto-detect protocol based on standard ports
            # Port 465: SMTP over SSL (SMTPS)
            # Port 587: SMTP with STARTTLS 
            # Port 25: Plain SMTP (usually with optional STARTTLS)
            if port == 465:
                server = smtplib.SMTP_SSL(host, port)
            else:
                server = smtplib.SMTP(host, port)
                # Use STARTTLS for ports 587 and 25 (if use_tls is not explicitly disabled)
                if smtp_config.get('use_tls', True):
                    server.starttls()
            
            username = smtp_config.get('username')
            password = smtp_config.get('password')
            if username and password:
                server.login(username, password)
            
            server.send_message(msg)
            server.quit()
            
            self.logger.info(f"Email sent successfully to {msg['To']}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to send email: {e}")
            return False
    
    def send_device_stopped_alert(self, device_id: str, device_name: str, 
                                 run_id: str, last_seen: datetime.datetime) -> bool:
        """
        Send alert when device stops unexpectedly.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            run_id: Run ID that was interrupted
            last_seen: When device was last seen
            
        Returns:
            True if alert was sent
        """
        if not self._should_send_alert(device_id, 'device_stopped'):
            return False
        
        # Get recipients
        device_users = self._get_device_users(device_id)
        admin_emails = self._get_admin_emails()
        all_emails = list(set(device_users + admin_emails))
        
        if not all_emails:
            self.logger.warning(f"No email recipients for device {device_id}")
            return False
        
        # Create email content
        subject = f"Ethoscope Alert: {device_name} stopped unexpectedly"
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .alert {{ background-color: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .info {{ background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                .details {{ background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                h1 {{ color: #721c24; }}
                .timestamp {{ font-style: italic; color: #6c757d; }}
            </style>
        </head>
        <body>
            <h1>Ethoscope Device Alert</h1>
            
            <div class="alert">
                <strong>Device Stopped Unexpectedly</strong><br>
                Your ethoscope device has stopped running and may need attention.
            </div>
            
            <div class="details">
                <h3>Device Information:</h3>
                <ul>
                    <li><strong>Device Name:</strong> {device_name}</li>
                    <li><strong>Device ID:</strong> {device_id}</li>
                    <li><strong>Run ID:</strong> {run_id}</li>
                    <li><strong>Last Seen:</strong> {last_seen.strftime('%Y-%m-%d %H:%M:%S')}</li>
                </ul>
            </div>
            
            <div class="info">
                <strong>What to do:</strong>
                <ol>
                    <li>Check if the device is powered on and connected to the network</li>
                    <li>Verify the device status in the ethoscope web interface</li>
                    <li>Check for any error messages or hardware issues</li>
                    <li>Restart the device if necessary</li>
                </ol>
            </div>
            
            <p class="timestamp">Alert sent at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        """
        
        text_body = f"""
        ETHOSCOPE DEVICE ALERT
        
        Device Stopped Unexpectedly
        
        Your ethoscope device has stopped running and may need attention.
        
        Device Information:
        - Device Name: {device_name}
        - Device ID: {device_id}
        - Run ID: {run_id}
        - Last Seen: {last_seen.strftime('%Y-%m-%d %H:%M:%S')}
        
        What to do:
        1. Check if the device is powered on and connected to the network
        2. Verify the device status in the ethoscope web interface
        3. Check for any error messages or hardware issues
        4. Restart the device if necessary
        
        Alert sent at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        msg = self._create_email_message(all_emails, subject, html_body, text_body)
        return self._send_email(msg)
    
    def send_storage_warning_alert(self, device_id: str, device_name: str, 
                                  storage_percent: float, available_space: str) -> bool:
        """
        Send alert when device storage is running low.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            storage_percent: Storage usage percentage
            available_space: Available space string (e.g., "2.1 GB")
            
        Returns:
            True if alert was sent
        """
        if not self._should_send_alert(device_id, 'storage_warning'):
            return False
        
        # Get recipients
        device_users = self._get_device_users(device_id)
        admin_emails = self._get_admin_emails()
        all_emails = list(set(device_users + admin_emails))
        
        if not all_emails:
            self.logger.warning(f"No email recipients for device {device_id}")
            return False
        
        # Create email content
        subject = f"Ethoscope Alert: {device_name} storage warning ({storage_percent:.1f}% full)"
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .warning {{ background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .info {{ background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                .details {{ background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                h1 {{ color: #856404; }}
                .timestamp {{ font-style: italic; color: #6c757d; }}
                .progress {{ background-color: #e9ecef; border-radius: 5px; height: 20px; margin: 10px 0; }}
                .progress-bar {{ background-color: #dc3545; height: 100%; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>Ethoscope Storage Warning</h1>
            
            <div class="warning">
                <strong>Storage Space Running Low</strong><br>
                Your ethoscope device storage is {storage_percent:.1f}% full and may need attention.
            </div>
            
            <div class="details">
                <h3>Device Information:</h3>
                <ul>
                    <li><strong>Device Name:</strong> {device_name}</li>
                    <li><strong>Device ID:</strong> {device_id}</li>
                    <li><strong>Storage Usage:</strong> {storage_percent:.1f}%</li>
                    <li><strong>Available Space:</strong> {available_space}</li>
                </ul>
                
                <div class="progress">
                    <div class="progress-bar" style="width: {storage_percent}%"></div>
                </div>
            </div>
            
            <div class="info">
                <strong>What to do:</strong>
                <ol>
                    <li>Check the device's data folder for old files that can be cleaned up</li>
                    <li>Ensure backup processes are running properly</li>
                    <li>Consider stopping non-essential experiments</li>
                    <li>Contact the system administrator if storage continues to fill up</li>
                </ol>
            </div>
            
            <p class="timestamp">Alert sent at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        """
        
        text_body = f"""
        ETHOSCOPE STORAGE WARNING
        
        Storage Space Running Low
        
        Your ethoscope device storage is {storage_percent:.1f}% full and may need attention.
        
        Device Information:
        - Device Name: {device_name}
        - Device ID: {device_id}
        - Storage Usage: {storage_percent:.1f}%
        - Available Space: {available_space}
        
        What to do:
        1. Check the device's data folder for old files that can be cleaned up
        2. Ensure backup processes are running properly
        3. Consider stopping non-essential experiments
        4. Contact the system administrator if storage continues to fill up
        
        Alert sent at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        msg = self._create_email_message(all_emails, subject, html_body, text_body)
        return self._send_email(msg)
    
    def send_device_unreachable_alert(self, device_id: str, device_name: str, 
                                     last_seen: datetime.datetime) -> bool:
        """
        Send alert when device becomes unreachable.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            last_seen: When device was last seen
            
        Returns:
            True if alert was sent
        """
        if not self._should_send_alert(device_id, 'device_unreachable'):
            return False
        
        # Get recipients (mainly admins for unreachable devices)
        admin_emails = self._get_admin_emails()
        
        if not admin_emails:
            self.logger.warning(f"No admin email recipients for unreachable device {device_id}")
            return False
        
        # Create email content
        subject = f"Ethoscope Alert: {device_name} is unreachable"
        
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .alert {{ background-color: #f8d7da; color: #721c24; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .info {{ background-color: #d4edda; color: #155724; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                .details {{ background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                h1 {{ color: #721c24; }}
                .timestamp {{ font-style: italic; color: #6c757d; }}
            </style>
        </head>
        <body>
            <h1>Ethoscope Device Alert</h1>
            
            <div class="alert">
                <strong>Device Unreachable</strong><br>
                An ethoscope device has become unreachable and may be offline.
            </div>
            
            <div class="details">
                <h3>Device Information:</h3>
                <ul>
                    <li><strong>Device Name:</strong> {device_name}</li>
                    <li><strong>Device ID:</strong> {device_id}</li>
                    <li><strong>Last Seen:</strong> {last_seen.strftime('%Y-%m-%d %H:%M:%S')}</li>
                </ul>
            </div>
            
            <div class="info">
                <strong>What to do:</strong>
                <ol>
                    <li>Check if the device is powered on</li>
                    <li>Verify network connectivity</li>
                    <li>Check for any hardware issues</li>
                    <li>Restart the device if necessary</li>
                    <li>Check the ethoscope web interface for more details</li>
                </ol>
            </div>
            
            <p class="timestamp">Alert sent at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        """
        
        text_body = f"""
        ETHOSCOPE DEVICE ALERT
        
        Device Unreachable
        
        An ethoscope device has become unreachable and may be offline.
        
        Device Information:
        - Device Name: {device_name}
        - Device ID: {device_id}
        - Last Seen: {last_seen.strftime('%Y-%m-%d %H:%M:%S')}
        
        What to do:
        1. Check if the device is powered on
        2. Verify network connectivity
        3. Check for any hardware issues
        4. Restart the device if necessary
        5. Check the ethoscope web interface for more details
        
        Alert sent at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        msg = self._create_email_message(admin_emails, subject, html_body, text_body)
        return self._send_email(msg)
    
    def test_email_configuration(self) -> Dict[str, Any]:
        """
        Test email configuration by sending a test message.
        
        Returns:
            Dictionary with test results
        """
        smtp_config = self._get_smtp_config()
        
        if not smtp_config.get('enabled', False):
            return {
                'success': False,
                'error': 'Email notifications are disabled in configuration'
            }
        
        # Send test email to admins
        admin_emails = self._get_admin_emails()
        if not admin_emails:
            return {
                'success': False,
                'error': 'No admin email addresses configured'
            }
        
        try:
            subject = "Ethoscope Email Test"
            html_body = """
            <html>
            <body>
                <h1>Ethoscope Email Test</h1>
                <p>This is a test email from the Ethoscope notification system.</p>
                <p>If you received this message, email notifications are working correctly.</p>
            </body>
            </html>
            """
            text_body = "This is a test email from the Ethoscope notification system."
            
            msg = self._create_email_message(admin_emails, subject, html_body, text_body)
            success = self._send_email(msg)
            
            return {
                'success': success,
                'recipients': admin_emails,
                'smtp_host': smtp_config.get('host', 'localhost'),
                'smtp_port': smtp_config.get('port', 587)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }