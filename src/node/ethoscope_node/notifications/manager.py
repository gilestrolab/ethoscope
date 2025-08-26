#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Unified notification manager for Ethoscope system alerts.

This manager handles all notification services (email, Mattermost, etc.) internally,
providing a simple interface for the scanner to send notifications without caring
about which specific services are configured or enabled.
"""

import logging
import datetime
from typing import Dict, Any, Optional, List
from .base import NotificationAnalyzer
from .email import EmailNotificationService
from .mattermost import MattermostNotificationService
from .slack import SlackNotificationService
from ..utils.configuration import EthoscopeConfiguration
from ..utils.etho_db import ExperimentalDB


class NotificationManager(NotificationAnalyzer):
    """
    Unified notification manager that handles all notification services.
    
    The scanner only needs to call methods on this class, and it will automatically
    send notifications through all enabled services (email, Mattermost, etc.).
    """
    
    def __init__(self, config: Optional[EthoscopeConfiguration] = None, 
                 db: Optional[ExperimentalDB] = None):
        """
        Initialize notification manager.
        
        Args:
            config: Configuration instance, will create new one if None
            db: Database instance, will create new one if None
        """
        super().__init__(config, db)
        
        # Initialize all notification services
        self._services = []
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize all available notification services based on configuration."""
        try:
            # Initialize email service
            email_config = self.config.content.get('smtp', {})
            if email_config.get('enabled', False):
                try:
                    email_service = EmailNotificationService(self.config, self.db)
                    self._services.append(('email', email_service))
                    self.logger.info("Email notification service initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize email service: {e}")
            else:
                self.logger.debug("Email notifications are disabled")
            
            # Initialize Mattermost service
            mattermost_config = self.config.content.get('mattermost', {})
            if mattermost_config.get('enabled', False):
                try:
                    mattermost_service = MattermostNotificationService(self.config, self.db)
                    self._services.append(('mattermost', mattermost_service))
                    self.logger.info("Mattermost notification service initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize Mattermost service: {e}")
            else:
                self.logger.debug("Mattermost notifications are disabled")
            
            # Initialize Slack service
            slack_config = self.config.content.get('slack', {})
            if slack_config.get('enabled', False):
                try:
                    slack_service = SlackNotificationService(self.config, self.db)
                    self._services.append(('slack', slack_service))
                    self.logger.info("Slack notification service initialized")
                except Exception as e:
                    self.logger.error(f"Failed to initialize Slack service: {e}")
            else:
                self.logger.debug("Slack notifications are disabled")
            
            # Future services can be added here (Telegram, etc.)
            
            self.logger.info(f"Notification manager initialized with {len(self._services)} active services")
            
        except Exception as e:
            self.logger.error(f"Error initializing notification services: {e}")
    
    def send_device_stopped_alert(self, device_id: str, device_name: str, 
                                 run_id: str, last_seen: datetime.datetime) -> bool:
        """
        Send device stopped alert through all enabled services.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            run_id: Run identifier
            last_seen: Last time device was seen
            
        Returns:
            True if at least one service sent the alert successfully
        """
        if not self._services:
            self.logger.warning("No notification services enabled")
            return False
        
        success_count = 0
        
        for service_name, service in self._services:
            try:
                result = service.send_device_stopped_alert(
                    device_id=device_id,
                    device_name=device_name,
                    run_id=run_id,
                    last_seen=last_seen
                )
                if result:
                    success_count += 1
                    self.logger.debug(f"Device stopped alert sent successfully via {service_name}")
                else:
                    self.logger.warning(f"Device stopped alert failed via {service_name}")
            except Exception as e:
                self.logger.error(f"Error sending device stopped alert via {service_name}: {e}")
        
        total_services = len(self._services)
        if success_count > 0:
            self.logger.info(f"Device stopped alert sent via {success_count}/{total_services} services")
            return True
        else:
            self.logger.error(f"Device stopped alert failed in all {total_services} services")
            return False
    
    def send_storage_warning_alert(self, device_id: str, device_name: str, 
                                  storage_percent: float, available_space: str) -> bool:
        """
        Send storage warning alert through all enabled services.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            storage_percent: Percentage of storage used
            available_space: Amount of available space remaining
            
        Returns:
            True if at least one service sent the alert successfully
        """
        if not self._services:
            self.logger.warning("No notification services enabled")
            return False
        
        success_count = 0
        
        for service_name, service in self._services:
            try:
                result = service.send_storage_warning_alert(
                    device_id=device_id,
                    device_name=device_name,
                    storage_percent=storage_percent,
                    available_space=available_space
                )
                if result:
                    success_count += 1
                    self.logger.debug(f"Storage warning sent successfully via {service_name}")
                else:
                    self.logger.warning(f"Storage warning failed via {service_name}")
            except Exception as e:
                self.logger.error(f"Error sending storage warning via {service_name}: {e}")
        
        total_services = len(self._services)
        if success_count > 0:
            self.logger.info(f"Storage warning sent via {success_count}/{total_services} services")
            return True
        else:
            self.logger.error(f"Storage warning failed in all {total_services} services")
            return False
    
    def send_device_unreachable_alert(self, device_id: str, device_name: str, 
                                     last_seen: datetime.datetime) -> bool:
        """
        Send device unreachable alert through all enabled services.
        
        Args:
            device_id: Device identifier
            device_name: Human-readable device name
            last_seen: Last time device was reachable
            
        Returns:
            True if at least one service sent the alert successfully
        """
        if not self._services:
            self.logger.warning("No notification services enabled")
            return False
        
        success_count = 0
        
        for service_name, service in self._services:
            try:
                result = service.send_device_unreachable_alert(
                    device_id=device_id,
                    device_name=device_name,
                    last_seen=last_seen
                )
                if result:
                    success_count += 1
                    self.logger.debug(f"Device unreachable alert sent successfully via {service_name}")
                else:
                    self.logger.warning(f"Device unreachable alert failed via {service_name}")
            except Exception as e:
                self.logger.error(f"Error sending device unreachable alert via {service_name}: {e}")
        
        total_services = len(self._services)
        if success_count > 0:
            self.logger.info(f"Device unreachable alert sent via {success_count}/{total_services} services")
            return True
        else:
            self.logger.error(f"Device unreachable alert failed in all {total_services} services")
            return False
    
    def test_all_configurations(self) -> Dict[str, Any]:
        """
        Test all notification service configurations.
        
        Returns:
            Dictionary with test results for each service
        """
        results = {}
        
        for service_name, service in self._services:
            try:
                if hasattr(service, 'test_email_configuration') and service_name == 'email':
                    result = service.test_email_configuration()
                elif hasattr(service, 'test_mattermost_configuration') and service_name == 'mattermost':
                    result = service.test_mattermost_configuration()
                elif hasattr(service, 'test_slack_configuration') and service_name == 'slack':
                    result = service.test_slack_configuration()
                else:
                    result = {'success': False, 'error': 'No test method available'}
                
                results[service_name] = result
            except Exception as e:
                results[service_name] = {'success': False, 'error': str(e)}
        
        return results
    
    def get_active_services(self) -> List[str]:
        """
        Get list of active notification services.
        
        Returns:
            List of active service names
        """
        return [service_name for service_name, _ in self._services]
    
    def reload_configuration(self):
        """
        Reload configuration and reinitialize services.
        
        This is useful if configuration changes at runtime.
        """
        self.logger.info("Reloading notification configuration...")
        self._services.clear()
        self.config.load()  # Reload configuration from file
        self._initialize_services()
        self.logger.info(f"Configuration reloaded with {len(self._services)} active services")