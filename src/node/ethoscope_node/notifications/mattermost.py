#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import requests
import datetime
import time
from typing import Dict, Any, Optional, List
from .base import NotificationAnalyzer
from ..utils.configuration import EthoscopeConfiguration
from ..utils.etho_db import ExperimentalDB


class MattermostNotificationService(NotificationAnalyzer):
    """
    Mattermost notification service for Ethoscope system alerts.
    
    Handles sending Mattermost notifications for device events like:
    - Device stopped unexpectedly
    - Storage warnings (80% full)
    - Device unreachable
    - Long-running experiments
    """
    
    def __init__(self, config: Optional[EthoscopeConfiguration] = None, 
                 db: Optional[ExperimentalDB] = None):
        """
        Initialize Mattermost notification service.
        
        Args:
            config: Configuration instance, will create new one if None
            db: Database instance, will create new one if None
        """
        super().__init__(config, db)
        
        # Rate limiting: track last alert time per device/type
        self._last_alert_times = {}
        self._default_cooldown = 3600  # 1 hour between similar alerts
        
    def _get_mattermost_config(self) -> Dict[str, Any]:
        """Get Mattermost configuration from settings."""
        return self.config.content.get('mattermost', {})
    
    def _get_alert_config(self) -> Dict[str, Any]:
        """Get alert configuration from settings."""
        return self.config.content.get('alerts', {})
    
    def _should_send_alert(self, device_id: str, alert_type: str, run_id: str = None) -> bool:
        """
        Check if we should send an alert based on rate limiting and database history.
        
        Args:
            device_id: Device identifier
            alert_type: Type of alert (device_stopped, storage_warning, etc.)
            run_id: Run ID for device_stopped alerts (prevents duplicates for same run)
            
        Returns:
            True if alert should be sent
        """
        # For device_stopped alerts, check database for duplicates based on run_id
        if alert_type == 'device_stopped' and run_id:
            has_been_sent = self.db.hasAlertBeenSent(device_id, alert_type, run_id)
            if has_been_sent:
                self.logger.debug(f"Alert {device_id}:{alert_type}:{run_id} already sent - preventing duplicate")
                return False
        elif alert_type == 'device_stopped' and not run_id:
            # For alerts without run_id, use timestamp-based approach to prevent spam
            self.logger.debug(f"No run_id provided for device_stopped alert - using cooldown only")
        
        # For other alerts or when no run_id, use traditional cooldown
        alert_config = self._get_alert_config()
        cooldown = alert_config.get('cooldown_seconds', self._default_cooldown)
        
        # Use run_id in key for device_stopped alerts, otherwise use traditional key
        if alert_type == 'device_stopped' and run_id:
            key = f"{device_id}:{alert_type}:{run_id}"
        else:
            key = f"{device_id}:{alert_type}"
        
        current_time = time.time()
        
        if key in self._last_alert_times:
            time_since_last = current_time - self._last_alert_times[key]
            if time_since_last < cooldown:
                self.logger.debug(f"Alert {key} suppressed due to cooldown ({time_since_last:.0f}s < {cooldown}s)")
                return False
        
        self._last_alert_times[key] = current_time
        return True
    
    def _send_message(self, message: str, attachments: Optional[List[Dict[str, Any]]] = None) -> bool:
        """
        Send message to Mattermost channel.
        
        Args:
            message: Message text to send
            attachments: Optional attachments (file uploads not implemented yet)
            
        Returns:
            True if message sent successfully
        """
        config = self._get_mattermost_config()
        
        # Check if Mattermost is enabled
        if not config.get('enabled', False):
            self.logger.debug("Mattermost notifications are disabled")
            return False
        
        # Get required configuration
        server_url = config.get('server_url')
        bot_token = config.get('bot_token')
        channel_id = config.get('channel_id')
        
        if not all([server_url, bot_token, channel_id]):
            self.logger.error("Mattermost configuration incomplete - missing server_url, bot_token, or channel_id")
            return False
        
        # Ensure server URL has proper scheme
        if not server_url.startswith(('http://', 'https://')):
            server_url = f"https://{server_url}"
        
        # Prepare API request
        url = f"{server_url}/api/v4/posts"
        headers = {
            'Authorization': f'Bearer {bot_token}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'channel_id': channel_id,
            'message': message
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            
            self.logger.info(f"Mattermost message sent successfully to channel {channel_id}")
            return True
            
        except requests.RequestException as e:
            self.logger.error(f"Failed to send Mattermost message: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending Mattermost message: {e}")
            return False
    
    def send_device_stopped_alert(self, device_id: str, device_name: str, 
                                 run_id: str, last_seen: datetime.datetime) -> bool:
        """
        Send alert when device has stopped unexpectedly.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            run_id: Run identifier
            last_seen: Last time device was seen
            
        Returns:
            True if alert sent successfully
        """
        if not self._should_send_alert(device_id, 'device_stopped', run_id):
            return False
        
        try:
            # Get comprehensive device failure analysis
            failure_analysis = self.analyze_device_failure(device_id)
            
            # Format alert message
            message_parts = [
                f"🚨 **Device Alert: {device_name} has stopped**",
                f"",
                f"**Device:** {device_name} ({device_id})",
                f"**Status:** {failure_analysis.get('status', 'Unknown')}",
                f"**Run ID:** {run_id}",
                f"**Last Seen:** {last_seen.strftime('%Y-%m-%d %H:%M:%S')}"
            ]
            
            # Add experiment details if available
            if failure_analysis.get('user'):
                message_parts.append(f"**User:** {failure_analysis['user']}")
            if failure_analysis.get('location'):
                message_parts.append(f"**Location:** {failure_analysis['location']}")
            if failure_analysis.get('experiment_duration_str'):
                message_parts.append(f"**Duration:** {failure_analysis['experiment_duration_str']}")
            if failure_analysis.get('experiment_type'):
                message_parts.append(f"**Type:** {failure_analysis['experiment_type']}")
            
            # Add problems if any
            problems = []
            if failure_analysis.get('problems'):
                problems.append(f"Run issues: {failure_analysis['problems']}")
            if failure_analysis.get('device_problems'):
                problems.append(f"Device issues: {failure_analysis['device_problems']}")
            
            if problems:
                message_parts.append("")
                message_parts.append("**Issues:**")
                for problem in problems:
                    message_parts.append(f"- {problem}")
            
            # Add device logs summary if available
            device_logs = self.get_device_logs(device_id, max_lines=10)
            if device_logs:
                log_lines = device_logs.strip().split('\n')
                if log_lines:
                    message_parts.append("")
                    message_parts.append("**Recent logs:**")
                    message_parts.append("```")
                    for line in log_lines[-5:]:  # Show last 5 lines
                        message_parts.append(line)
                    message_parts.append("```")
            
            message = "\n".join(message_parts)
            
            # Send the message
            success = self._send_message(message)
            
            # Log alert in database if sent successfully
            if success:
                try:
                    self.db.logAlert(device_id, 'device_stopped', run_id, 
                                   datetime.datetime.now(), 'mattermost')
                except Exception as e:
                    self.logger.warning(f"Failed to log alert in database: {e}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error sending device stopped alert: {e}")
            return False
    
    def send_storage_warning_alert(self, device_id: str, device_name: str, 
                                  storage_percent: float, available_space: str) -> bool:
        """
        Send alert when device storage is running low.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            storage_percent: Percentage of storage used
            available_space: Amount of available space remaining
            
        Returns:
            True if alert sent successfully
        """
        if not self._should_send_alert(device_id, 'storage_warning'):
            return False
        
        try:
            message_parts = [
                f"⚠️ **Storage Warning: {device_name}**",
                f"",
                f"**Device:** {device_name} ({device_id})",
                f"**Storage Used:** {storage_percent:.1f}%",
                f"**Available Space:** {available_space}",
                f"",
                f"Please free up space or backup data to avoid experiment interruption."
            ]
            
            message = "\n".join(message_parts)
            return self._send_message(message)
            
        except Exception as e:
            self.logger.error(f"Error sending storage warning alert: {e}")
            return False
    
    def send_device_unreachable_alert(self, device_id: str, device_name: str, 
                                     last_seen: datetime.datetime) -> bool:
        """
        Send alert when device becomes unreachable.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            last_seen: Last time device was reachable
            
        Returns:
            True if alert sent successfully
        """
        if not self._should_send_alert(device_id, 'device_unreachable'):
            return False
        
        try:
            # Calculate how long device has been unreachable
            time_offline = datetime.datetime.now() - last_seen
            offline_str = self._format_duration(time_offline.total_seconds())
            
            message_parts = [
                f"📵 **Device Unreachable: {device_name}**",
                f"",
                f"**Device:** {device_name} ({device_id})",
                f"**Last Seen:** {last_seen.strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Offline Duration:** {offline_str}",
                f"",
                f"Device may have network issues or be powered off."
            ]
            
            message = "\n".join(message_parts)
            return self._send_message(message)
            
        except Exception as e:
            self.logger.error(f"Error sending device unreachable alert: {e}")
            return False
    
    def test_mattermost_configuration(self) -> Dict[str, Any]:
        """
        Test Mattermost configuration by sending a test message.
        
        Returns:
            Dictionary with test results
        """
        try:
            config = self._get_mattermost_config()
            
            if not config.get('enabled', False):
                return {
                    'success': False,
                    'error': 'Mattermost notifications are disabled in configuration'
                }
            
            # Check required configuration
            server_url = config.get('server_url')
            bot_token = config.get('bot_token')
            channel_id = config.get('channel_id')
            
            if not all([server_url, bot_token, channel_id]):
                return {
                    'success': False,
                    'error': 'Mattermost configuration incomplete - missing server_url, bot_token, or channel_id'
                }
            
            # Send test message
            test_message = f"🧪 **Ethoscope Test Message**\n\nMattermost notifications are working correctly!\n\nTimestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            success = self._send_message(test_message)
            
            if success:
                return {
                    'success': True,
                    'server_url': server_url,
                    'channel_id': channel_id,
                    'message': 'Test message sent successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to send test message (check logs for details)'
                }
                
        except Exception as e:
            self.logger.error(f"Error testing Mattermost configuration: {e}")
            return {
                'success': False,
                'error': f'Exception during test: {str(e)}'
            }