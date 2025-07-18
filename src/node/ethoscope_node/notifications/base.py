#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import datetime
import time
import os
import requests
from typing import Dict, Any, Optional, List
from ..utils.configuration import EthoscopeConfiguration
from ..utils.etho_db import ExperimentalDB


class NotificationAnalyzer:
    """
    Base class for analyzing device failures and gathering notification data.
    
    Provides common functionality for all notification services including:
    - Device failure analysis
    - Activity information gathering
    - Log file collection
    - Experiment duration calculation
    """
    
    def __init__(self, config: Optional[EthoscopeConfiguration] = None, 
                 db: Optional[ExperimentalDB] = None):
        """
        Initialize notification analyzer.
        
        Args:
            config: Configuration instance, will create new one if None
            db: Database instance, will create new one if None
        """
        self.config = config or EthoscopeConfiguration()
        self.db = db or ExperimentalDB()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def analyze_device_failure(self, device_id: str) -> Dict[str, Any]:
        """
        Analyze a device failure and gather comprehensive information.
        
        Args:
            device_id: Device identifier
            
        Returns:
            Dictionary with device failure analysis
        """
        try:
            # Get device information
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                self.logger.warning(f"No device info found for {device_id}")
                return {
                    'device_id': device_id,
                    'device_name': f"Unknown device {device_id}",
                    'error': 'Device not found in database'
                }
            
            # Get all runs for this device
            all_runs = self.db.getRun('all', asdict=True)
            device_runs = [run for run in all_runs.values() 
                          if run.get('ethoscope_id') == device_id]
            
            if not device_runs:
                return {
                    'device_id': device_id,
                    'device_name': device_info.get('ethoscope_name', f"Device {device_id}"),
                    'last_seen': device_info.get('last_seen'),
                    'error': 'No runs found for device'
                }
            
            # Find last run
            last_run = max(device_runs, key=lambda x: x.get('start_time', 0))
            
            # Determine failure type and duration
            current_time = time.time()
            start_time = last_run.get('start_time', 0)
            end_time = last_run.get('end_time')
            
            if end_time is None:
                failure_type = "crashed_during_tracking"
                duration = current_time - start_time
                status = "Failed while running"
            else:
                # Check if ended recently (within last hour)
                if current_time - end_time < 3600:
                    failure_type = "stopped_recently"
                    status = "Stopped recently"
                else:
                    failure_type = "completed_normally"
                    status = "Completed normally"
                duration = end_time - start_time
            
            # Get experiment type from experimental_data
            experimental_data = last_run.get('experimental_data', {})
            if isinstance(experimental_data, str):
                try:
                    import json
                    experimental_data = json.loads(experimental_data)
                except:
                    experimental_data = {}
            
            return {
                'device_id': device_id,
                'device_name': device_info.get('ethoscope_name', f"Device {device_id}"),
                'last_seen': device_info.get('last_seen'),
                'failure_type': failure_type,
                'status': status,
                'experiment_duration': duration,
                'experiment_duration_str': self._format_duration(duration),
                'user': last_run.get('user_name', 'Unknown'),
                'location': last_run.get('location', 'Unknown'),
                'run_id': last_run.get('run_id'),
                'problems': last_run.get('problems', ''),
                'experimental_data': experimental_data,
                'experiment_type': experimental_data.get('type', 'tracking'),
                'start_time': datetime.datetime.fromtimestamp(start_time) if start_time else None,
                'end_time': datetime.datetime.fromtimestamp(end_time) if end_time else None,
                'device_problems': device_info.get('problems', ''),
                'device_active': device_info.get('active', False)
            }
            
        except Exception as e:
            self.logger.error(f"Error analyzing device failure for {device_id}: {e}")
            return {
                'device_id': device_id,
                'device_name': f"Device {device_id}",
                'error': str(e)
            }
    
    def get_device_logs(self, device_id: str, max_lines: int = 1000) -> Optional[str]:
        """
        Get log content from a device.
        
        Args:
            device_id: Device identifier
            max_lines: Maximum number of log lines to retrieve
            
        Returns:
            Log content as string, or None if not available
        """
        try:
            # Try to get logs from device via API
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                return None
                
            # Get device IP/hostname
            ip = device_info.get('ip', device_info.get('ethoscope_name', device_id))
            
            # Try to fetch logs from device
            log_url = f"http://{ip}:9000/data/log/{device_id}"
            
            try:
                response = requests.get(log_url, timeout=10)
                if response.status_code == 200:
                    log_content = response.text
                    
                    # Limit to max_lines if specified
                    if max_lines and max_lines > 0:
                        lines = log_content.split('\n')
                        if len(lines) > max_lines:
                            lines = lines[-max_lines:]  # Get last N lines
                        log_content = '\n'.join(lines)
                    
                    return log_content
                    
            except requests.RequestException as e:
                self.logger.warning(f"Could not fetch logs from device {device_id}: {e}")
                
            # If device API fails, try to get from local cache/backup
            # (This would be implemented based on backup system)
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting device logs for {device_id}: {e}")
            return None
    
    def get_device_status_info(self, device_id: str) -> Dict[str, Any]:
        """
        Get current device status information.
        
        Args:
            device_id: Device identifier
            
        Returns:
            Dictionary with device status information
        """
        try:
            device_info = self.db.getEthoscope(device_id, asdict=True)
            if not device_info:
                return {'error': 'Device not found'}
            
            # Try to get real-time status from device
            ip = device_info.get('ip', device_info.get('ethoscope_name', device_id))
            
            try:
                status_url = f"http://{ip}:9000/data/{device_id}"
                response = requests.get(status_url, timeout=5)
                
                if response.status_code == 200:
                    status_data = response.json()
                    return {
                        'device_id': device_id,
                        'device_name': device_info.get('ethoscope_name'),
                        'online': True,
                        'status': status_data.get('status', 'unknown'),
                        'last_frame_time': status_data.get('monitor_info', {}).get('last_time_stamp'),
                        'fps': status_data.get('monitor_info', {}).get('fps'),
                        'experimental_info': status_data.get('experimental_info', {}),
                        'database_info': status_data.get('database_info', {}),
                        'machine_info': status_data.get('machine_info', {})
                    }
                    
            except requests.RequestException:
                pass
            
            # Device is offline, return database info
            return {
                'device_id': device_id,
                'device_name': device_info.get('ethoscope_name'),
                'online': False,
                'last_seen': device_info.get('last_seen'),
                'active': device_info.get('active', False),
                'problems': device_info.get('problems', ''),
                'status': 'offline'
            }
            
        except Exception as e:
            self.logger.error(f"Error getting device status for {device_id}: {e}")
            return {
                'device_id': device_id,
                'error': str(e)
            }
    
    def _format_duration(self, seconds: float) -> str:
        """
        Format duration in seconds to human-readable string.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted duration string
        """
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} minutes"
        elif seconds < 86400:
            hours = seconds / 3600
            return f"{hours:.1f} hours"
        else:
            days = seconds / 86400
            return f"{days:.1f} days"
    
    def get_device_users(self, device_id: str) -> List[str]:
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
    
    def get_admin_emails(self) -> List[str]:
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