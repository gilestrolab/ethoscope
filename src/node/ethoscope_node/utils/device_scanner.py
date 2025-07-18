import urllib.request
import urllib.error
import urllib.parse
import os
import csv
import datetime
import json
import time
import logging
import traceback
import pickle
import socket
import struct
import subprocess
from threading import Thread, RLock, Event
from functools import wraps
from contextlib import contextmanager
from typing import Dict, List, Optional, Any, Iterator, Union
from dataclasses import dataclass
from zeroconf import ServiceBrowser, Zeroconf, IPVersion

from ethoscope_node.utils.etho_db import ExperimentalDB
from ethoscope_node.utils.configuration import ensure_ssh_keys, EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import get_sqlite_table_counts, calculate_backup_percentage_from_table_counts
from ethoscope_node.utils.notification import EmailNotificationService

# Constants
STREAMING_PORT = 8887
ETHOSCOPE_PORT = 9000
DB_UPDATE_INTERVAL = 30  # seconds
DEFAULT_TIMEOUT = 5
MAX_RETRIES = 2
INITIAL_RETRY_DELAY = 1
MAX_RETRY_DELAY = 5

@dataclass
class DeviceInfo:
    """Data class for device information."""
    ip: str
    port: int = 80
    status: str = "offline"
    name: str = ""
    id: str = ""
    last_seen: Optional[float] = None


class DeviceStatus:
    """
    Sophisticated device status management class that tracks status changes,
    user interactions, and provides intelligent alerting logic.
    """
    
    # Valid status types
    VALID_STATUSES = {
        'online', 'offline', 'running', 'stopped', 'unreached', 
        'initialising', 'stopping', 'recording', 'streaming', 'busy'
    }
    
    # Graceful operation types
    GRACEFUL_OPERATIONS = {'poweroff', 'reboot', 'restart'}
    
    def __init__(self, status_name: str, is_user_triggered: bool = False, 
                 trigger_source: str = "system", metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize device status.
        
        Args:
            status_name: Name of the status (must be in VALID_STATUSES)
            is_user_triggered: Whether this status change was triggered by user action
            trigger_source: Source of the trigger ("user", "system", "network", "graceful")
            metadata: Additional metadata about the status change
        """
        if status_name not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status_name}. Must be one of: {self.VALID_STATUSES}")
        
        self._status_name = status_name
        self._is_user_triggered = is_user_triggered
        self._trigger_source = trigger_source
        self._timestamp = time.time()
        self._previous_status = None
        self._metadata = metadata or {}
        self._unreachable_start_time = None
        self._consecutive_errors = 0
        
        # Set unreachable start time if this is an unreached status
        if status_name == 'unreached':
            self._unreachable_start_time = self._timestamp
    
    @property
    def status_name(self) -> str:
        """Get the status name."""
        return self._status_name
    
    @property
    def is_user_triggered(self) -> bool:
        """Check if this status change was triggered by user action."""
        return self._is_user_triggered
    
    @property
    def trigger_source(self) -> str:
        """Get the trigger source."""
        return self._trigger_source
    
    @property
    def timestamp(self) -> float:
        """Get the timestamp when this status was set."""
        return self._timestamp
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """Get status metadata."""
        return self._metadata.copy()
    
    @property
    def consecutive_errors(self) -> int:
        """Get the number of consecutive errors."""
        return self._consecutive_errors
    
    def set_previous_status(self, previous_status: Optional['DeviceStatus']):
        """Set the previous status for transition tracking."""
        self._previous_status = previous_status
    
    def get_previous_status(self) -> Optional['DeviceStatus']:
        """Get the previous status."""
        return self._previous_status
    
    def increment_errors(self):
        """Increment the consecutive error count."""
        self._consecutive_errors += 1
    
    def reset_errors(self):
        """Reset the consecutive error count."""
        self._consecutive_errors = 0
    
    def should_send_alert(self, unreachable_timeout_minutes: int = 20) -> bool:
        """
        Determine if an alert should be sent for this status.
        
        Args:
            unreachable_timeout_minutes: Minutes to wait before alerting for unreachable devices
        
        Returns:
            True if an alert should be sent
        """
        # No alerts for user-triggered actions
        if self._is_user_triggered:
            return False
        
        # No alerts for graceful operations within grace period
        if self.is_graceful_operation():
            return False
        
        # For unreachable/busy status, only alert after timeout
        if self._status_name in ['unreached', 'busy']:
            return self.is_timeout_exceeded(unreachable_timeout_minutes)
        
        # Alert for autonomous stops and other system issues
        if self._status_name in ['stopped', 'offline'] and self._trigger_source == 'system':
            return True
        
        return False
    
    def is_timeout_exceeded(self, timeout_minutes: int) -> bool:
        """
        Check if the timeout has been exceeded for unreachable devices.
        
        Args:
            timeout_minutes: Timeout in minutes
            
        Returns:
            True if timeout has been exceeded
        """
        if not self._unreachable_start_time:
            return False
        
        elapsed_minutes = (time.time() - self._unreachable_start_time) / 60
        return elapsed_minutes > timeout_minutes
    
    def is_graceful_operation(self) -> bool:
        """
        Check if this status resulted from a graceful operation.
        
        Returns:
            True if this is a graceful operation
        """
        return self._trigger_source == 'graceful'
    
    def get_age_seconds(self) -> float:
        """
        Get the age of this status in seconds.
        
        Returns:
            Age in seconds
        """
        return time.time() - self._timestamp
    
    def get_age_minutes(self) -> float:
        """
        Get the age of this status in minutes.
        
        Returns:
            Age in minutes
        """
        return self.get_age_seconds() / 60
    
    def update_metadata(self, key: str, value: Any):
        """
        Update metadata for this status.
        
        Args:
            key: Metadata key
            value: Metadata value
        """
        self._metadata[key] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert status to dictionary for serialization.
        
        Returns:
            Dictionary representation of the status
        """
        return {
            'status_name': self._status_name,
            'is_user_triggered': self._is_user_triggered,
            'trigger_source': self._trigger_source,
            'timestamp': self._timestamp,
            'metadata': self._metadata,
            'unreachable_start_time': self._unreachable_start_time,
            'consecutive_errors': self._consecutive_errors
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeviceStatus':
        """
        Create DeviceStatus from dictionary.
        
        Args:
            data: Dictionary representation
            
        Returns:
            DeviceStatus instance
        """
        status = cls(
            status_name=data['status_name'],
            is_user_triggered=data.get('is_user_triggered', False),
            trigger_source=data.get('trigger_source', 'system'),
            metadata=data.get('metadata', {})
        )
        
        status._timestamp = data.get('timestamp', time.time())
        status._unreachable_start_time = data.get('unreachable_start_time')
        status._consecutive_errors = data.get('consecutive_errors', 0)
        
        return status
    
    def __str__(self) -> str:
        """String representation of the status."""
        age_minutes = self.get_age_minutes()
        return f"DeviceStatus({self._status_name}, {self._trigger_source}, {age_minutes:.1f}m ago)"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return (f"DeviceStatus(status_name='{self._status_name}', "
                f"is_user_triggered={self._is_user_triggered}, "
                f"trigger_source='{self._trigger_source}', "
                f"age_minutes={self.get_age_minutes():.1f})")


class ScanException(Exception):
    """Custom exception for scanning operations."""
    pass


class NetworkError(ScanException):
    """Network-related scanning error."""
    pass


class DeviceError(ScanException):
    """Device-specific error."""
    pass


def retry(exception_to_check, tries: int = MAX_RETRIES, delay: float = INITIAL_RETRY_DELAY, 
         backoff: float = 1.5, max_delay: float = MAX_RETRY_DELAY, logger=None):
    """
    Retry decorator with exponential backoff and maximum delay cap.
    
    Args:
        exception_to_check: Exception type to catch and retry on
        tries: Maximum number of attempts
        delay: Initial delay between attempts
        backoff: Multiplier for delay increase
        max_delay: Maximum delay between attempts
        logger: Optional logger for retry attempts
    """
    def deco_retry(func):
        @wraps(func)
        def func_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return func(*args, **kwargs)
                except exception_to_check as e:
                    if logger:
                        logger.debug(f"Retry {tries - mtries + 1}/{tries} for {func.__name__}: {e}")
                    time.sleep(min(mdelay, max_delay))
                    mtries -= 1
                    mdelay *= backoff
            return func(*args, **kwargs)
        return func_retry
    return deco_retry


class BaseDevice(Thread):
    """Base class for all devices with common functionality."""
    
    def __init__(self, ip: str, port: int = 80, refresh_period: float = 5, 
                 results_dir: str = "", timeout: float = DEFAULT_TIMEOUT):
        super().__init__(daemon=True)
        
        self._ip = ip
        self._port = port
        self._refresh_period = refresh_period
        self._results_dir = results_dir
        self._timeout = timeout
        
        # Device state with DeviceStatus
        self._device_status = DeviceStatus("offline", trigger_source="system")
        self._info = {"ip": ip}
        self._id = ""
        self._is_online = True
        self._skip_scanning = False
        
        # Synchronization and error tracking
        self._lock = RLock()
        self._last_refresh = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10 
        self._last_successful_contact = time.time()
        
        # Logging
        self._logger = logging.getLogger(f"{self.__class__.__name__}_{ip}")
        
        # URLs
        self._setup_urls()
        
        # Initialize device info
        self._reset_info()
    
    def _setup_urls(self):
        """Setup device-specific URLs. Override in subclasses."""
        self._id_url = f"http://{self._ip}:{self._port}/id"
        self._data_url = f"http://{self._ip}:{self._port}/"
    
    @retry(ScanException, tries=MAX_RETRIES, delay=INITIAL_RETRY_DELAY, backoff=1.5)
    def _get_json(self, url: str, timeout: Optional[float] = None, 
                  post_data: Optional[bytes] = None) -> Dict[str, Any]:
        """
        Fetch JSON data from URL with retry logic and improved error handling.
        """
        timeout = timeout or self._timeout
        
        try:
            headers = {'Content-Type': 'application/json', 'User-Agent': 'EthoscopeNode/1.0'}
            req = urllib.request.Request(url, data=post_data, headers=headers)
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                message = response.read()
                
                if not message:
                    raise ScanException(f"Empty response from {url}")
                
                try:
                    return json.loads(message)
                except json.JSONDecodeError as e:
                    raise ScanException(f"Invalid JSON from {url}: {e}")
                    
        except urllib.error.HTTPError as e:
            raise NetworkError(f"HTTP {e.code} error from {url}")
        except urllib.error.URLError as e:
            raise NetworkError(f"URL error from {url}: {e.reason}")
        except socket.timeout:
            raise NetworkError(f"Timeout connecting to {url}")
        except Exception as e:
            raise ScanException(f"Unexpected error from {url}: {e}")
    
    def run(self):
        """Main device monitoring loop"""
        while self._is_online:
            time.sleep(0.2)
            
            current_time = time.time()
            
            # Check if it's time for regular refresh (use dynamic refresh period)
            effective_refresh_period = self._get_effective_refresh_period()
            if current_time - self._last_refresh > effective_refresh_period:
                if not self._skip_scanning:
                    try:
                        self._update_info()
                        # Reset error counter on successful update
                        if self._consecutive_errors > 0:
                            self._logger.info(f"Device {self._ip} recovered after {self._consecutive_errors} errors")
                            self._consecutive_errors = 0
                        self._last_successful_contact = current_time
                    except Exception as e:
                        # Only handle error if not already marked for skipping
                        if not self._skip_scanning:
                            self._handle_device_error(e)
                else:
                    # Device is marked for skipping - just update status to offline
                    self._reset_info()
                    
                self._last_refresh = current_time
    
    def _handle_device_error(self, error):
        """Handle device errors. Stop interrogating devices that appear to have shut down ungracefully."""
        with self._lock:
            self._consecutive_errors += 1
            
            # Always reset device info to offline
            self._reset_info()
            
            error_str = str(error).lower()
            
            # Check if this is a "connection refused" error - indicates potential shutdown
            if 'connection refused' in error_str or 'actively refused' in error_str:
                # After 3 consecutive connection refused errors, determine if this is graceful or ungraceful
                if self._consecutive_errors >= 3:
                    # Check if this might be a graceful shutdown
                    is_graceful = self._is_graceful_shutdown()
                    
                    if is_graceful:
                        self._logger.info(f"Device {self._ip} appears to have been shut down gracefully (recent user action). Stopping interrogation.")
                        self._skip_scanning = True
                        self._update_device_status("offline", trigger_source="graceful", metadata={"reason": "graceful_shutdown"})
                    else:
                        self._logger.info(f"Device {self._ip} has {self._consecutive_errors} consecutive connection refused errors - appears shut down ungracefully. Stopping interrogation.")
                        self._skip_scanning = True
                        self._update_device_status("offline", trigger_source="system", metadata={"reason": "ungraceful_shutdown"})
                    
                    self._info.update({
                        'last_seen': time.time()
                    })
                    return
                else:
                    self._logger.info(f"Device {self._ip} connection refused (attempt {self._consecutive_errors}/3)")
                    return
            
            if self._consecutive_errors >= self._max_consecutive_errors:
                # Device seems to have gone offline normally, stop interrogating
                self._logger.info(f"Device {self._ip} appears offline after {self._consecutive_errors} errors, stopping interrogation")
                self._skip_scanning = True
                self._update_device_status("offline", trigger_source="system", metadata={"reason": "max_errors_reached"})
                self._info.update({
                    'last_seen': time.time()
                })
            else:
                # Log errors less frequently to reduce noise
                if self._consecutive_errors == 1:
                    self._logger.info(f"Device {self._ip} connection failed: {str(error)}")
                elif self._consecutive_errors == 5:
                    self._logger.warning(f"Device {self._ip} has 5 consecutive errors, will stop interrogating at 10")
                else:
                    self._logger.debug(f"Device {self._ip} error #{self._consecutive_errors}: {str(error)}")
    
    def _update_id(self):
        """Update device ID with proper error handling."""
        if self._skip_scanning:
            raise ScanException(f"Not scanning IP {self._ip}")
        
        try:
            # Try data URL first, then ID URL
            try:
                resp = self._get_json(self._data_url)
            except ScanException:
                resp = self._get_json(self._id_url)
            
            old_id = self._id
            new_id = resp.get('id', '')
            
            if new_id != old_id:
                if old_id:
                    self._logger.info(f"Device ID changed: {old_id} -> {new_id}")
                self._reset_info()
            
            self._id = new_id
            self._info["ip"] = self._ip
            self._info["id"] = new_id
            
        except ScanException:
            raise
        except Exception as e:
            raise ScanException(f"Failed to update device ID: {e}")
    
    def _update_device_status(self, status_name: str, is_user_triggered: bool = False,
                             trigger_source: str = "system", metadata: Optional[Dict[str, Any]] = None):
        """
        Update device status using DeviceStatus object.
        
        Args:
            status_name: New status name
            is_user_triggered: Whether this was triggered by user action
            trigger_source: Source of the trigger
            metadata: Additional metadata
        """
        with self._lock:
            # Create new status object
            previous_status = self._device_status
            new_status = DeviceStatus(
                status_name=status_name,
                is_user_triggered=is_user_triggered,
                trigger_source=trigger_source,
                metadata=metadata or {}
            )
            
            # Set previous status for transition tracking
            new_status.set_previous_status(previous_status)
            
            # Update consecutive errors from previous status
            if previous_status:
                new_status._consecutive_errors = previous_status.consecutive_errors
            
            # Update device status
            self._device_status = new_status
            
            # Update info dict (no longer storing status directly)
            self._info['last_seen'] = time.time()
            self._info['consecutive_errors'] = new_status.consecutive_errors
            
            # Log status change
            if previous_status and previous_status.status_name != status_name:
                self._logger.info(f"Status changed: {previous_status.status_name} -> {status_name} "
                                f"(trigger: {trigger_source}, user: {is_user_triggered})")
    
    def _reset_info(self):
        """Reset device info to offline state."""
        with self._lock:
            # Preserve important identifying information
            preserved_name = self._info.get('name', '')
            preserved_id = self._info.get('id', self._id)
            
            # Update status using DeviceStatus
            self._update_device_status("offline", trigger_source="system")
            
            base_info = {
                'ip': self._ip,
                'last_seen': time.time(),
                'consecutive_errors': self._consecutive_errors
            }
            
            # Preserve name and id if they exist
            if preserved_name:
                base_info['name'] = preserved_name
            if preserved_id:
                base_info['id'] = preserved_id
                
            self._info.update(base_info)
    
    def _update_info(self):
        """Update device information. Override in subclasses."""
        self._update_id()
        with self._lock:
            self._update_device_status("online", trigger_source="system")
            self._info['last_seen'] = time.time()
    
    def stop(self):
        """Stop the device monitoring thread."""
        self._is_online = False
        
    def skip_scanning(self, value: bool):
        """Enable/disable scanning for this device."""
        self._skip_scanning = value
        if not value:
            # Re-enabling scanning - reset error state
            self._consecutive_errors = 0
    
    def reset_error_state(self):
        """Reset error state for this device."""
        self._consecutive_errors = 0
        self._error_backoff_time = 0
    
    def _is_graceful_shutdown(self) -> bool:
        """
        Check if a connection refused error is likely due to graceful shutdown.
        
        Returns:
            True if this appears to be a graceful shutdown
        """
        # The DeviceStatus class already handles graceful operation detection
        current_status = self.get_device_status()
        return current_status and current_status.is_graceful_operation()
    
    def _get_effective_refresh_period(self) -> float:
        """
        Get the effective refresh period based on device status.
        
        Returns:
            Refresh period in seconds (60s for busy devices, normal for others)
        """
        current_status = self.get_device_status()
        if current_status and current_status.status_name == 'busy':
            return 60.0  # Busy devices refresh every 60 seconds
        return self._refresh_period  # Normal refresh period
    
    # Public interface methods
    def ip(self) -> str:
        """Get device IP address."""
        return self._ip
        
    def id(self) -> str:
        """Get device ID."""
        with self._lock:
            return self._id
    
    def get_device_status(self) -> DeviceStatus:
        """Get the current DeviceStatus object."""
        with self._lock:
            return self._device_status
        
    def info(self) -> Dict[str, Any]:
        """Get device information dictionary."""
        with self._lock:
            info_copy = self._info.copy()
            
            # Add enhanced status information from DeviceStatus
            if self._device_status:
                # Get timeout from configuration if available (for Ethoscope devices)
                unreachable_timeout = 20  # Default
                if hasattr(self, '_config'):
                    alert_config = self._config.get_custom('alerts') or {}
                    unreachable_timeout = alert_config.get('unreachable_timeout_minutes', 20)
                
                # Add status at root level for backward compatibility
                info_copy['status'] = self._device_status.status_name
                
                # Add detailed status information
                info_copy['status_details'] = {
                    'status': self._device_status.status_name,
                    'is_user_triggered': self._device_status.is_user_triggered,
                    'trigger_source': self._device_status.trigger_source,
                    'age_minutes': self._device_status.get_age_minutes(),
                    'consecutive_errors': self._device_status.consecutive_errors,
                    'should_alert': self._device_status.should_send_alert(unreachable_timeout)
                }
            
            # Add skip_scanning status for debugging
            info_copy['skip_scanning'] = self._skip_scanning
            
            # Expose backup status at root level for frontend compatibility
            progress_info = info_copy.get('progress', {})
            if progress_info:
                # Extract backup status from progress and expose at root level
                backup_status = progress_info.get('status')
                if backup_status:
                    info_copy['backup_status'] = backup_status
                
                # Also expose backup_size and time_since_backup if available
                backup_size = progress_info.get('backup_size')
                if backup_size is not None:
                    info_copy['backup_size'] = backup_size
                    
                time_since_backup = progress_info.get('time_since_backup')
                if time_since_backup is not None:
                    info_copy['time_since_backup'] = time_since_backup
            
            return info_copy
class Ethoscope(BaseDevice):
    """Enhanced Ethoscope device class with improved state management."""
    
    REMOTE_PAGES = {
        'id': "id",
        'data' : "data",
        'videofiles': "data/listfiles/video",
        'stream': "stream.mjpg",
        'user_options': "user_options",
        'log': "data/log",
        'static': "static",
        'controls': "controls",
        'machine_info': "machine",
        'connected_module': "module",
        'update': "update",
        'dumpdb': "dumpSQLdb"
    }
    
    ALLOWED_INSTRUCTIONS = {
        "stream": ["stopped"],
        "start": ["stopped"], 
        "start_record": ["stopped"],
        "stop": ["streaming", "running", "recording"],
        "poweroff": ["stopped"],
        "reboot": ["stopped"],
        "restart": ["stopped"],
        "dumpdb": ["stopped"],
        "offline": [],
        "convertvideos": ["stopped"],
        "test_module": ["stopped"]
    }
    
    def __init__(self, ip: str, port: int = ETHOSCOPE_PORT, refresh_period: float = 5,
                 results_dir: str = "/ethoscope_data/results", config_dir: str = "/etc/ethoscope",
                 config: Optional[EthoscopeConfiguration] = None):
        # Initialize ethoscope-specific attributes BEFORE calling parent
        self._results_dir = results_dir
        self._config_dir = config_dir
        self._edb = ExperimentalDB(config_dir)
        self._last_db_info = 0
        self._device_controller_created = time.time()
        self._ping_count = 0  # Initialize ping counter
        
        # User action tracking for enhanced status management
        self._last_user_action = None
        self._last_user_instruction = None
        
        # Use provided configuration or create new one
        self._config = config or EthoscopeConfiguration()
        self._notification_service = EmailNotificationService(self._config, self._edb)
        
        # Call parent initialization
        super().__init__(ip, port, refresh_period, results_dir)
    
    def _setup_urls(self):
        """Setup ethoscope-specific URLs."""
        self._id_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['id']}"
        self._data_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['data']}/{self._id}"

    def _reset_info(self):
        """Reset device info to offline state."""
        with self._lock:
            # Preserve important identifying information
            preserved_name = self._info.get('name', '')
            preserved_id = self._info.get('id', self._id)
            
            base_info = {
                'ip': self._ip,
                'last_ip' : self._ip,
                'last_seen': time.time(),
                'ping': self._ping_count,
                'consecutive_errors': self._consecutive_errors
            }
            
            # Preserve name and id if they exist
            if preserved_name:
                base_info['name'] = preserved_name
            if preserved_id:
                base_info['id'] = preserved_id
            
            self._info.update(base_info)
    
    def send_instruction(self, instruction: str, post_data: Optional[Union[Dict, bytes]] = None):
        """
        Send instruction to ethoscope with validation and user action tracking.
        
        Args:
            instruction: Instruction to send
            post_data: Optional data to send with instruction (can be Dict or bytes)
        """
        self._check_instruction_status(instruction)
        
        # Determine trigger source and type
        is_user_triggered = True
        trigger_source = "user"
        
        # Check if this is a graceful operation
        if instruction in DeviceStatus.GRACEFUL_OPERATIONS:
            trigger_source = "graceful"
            
        # Track user action timestamp for later status updates
        self._last_user_action = time.time()
        self._last_user_instruction = instruction
        
        # Handle post_data properly - it might already be bytes or need conversion
        json_data = None
        if post_data is not None:
            if isinstance(post_data, bytes):
                # Already bytes, use as-is
                json_data = post_data
            elif isinstance(post_data, (dict, list, str, int, float, bool)):
                # JSON serializable data, convert to bytes
                json_data = json.dumps(post_data).encode('utf-8')
            else:
                # Unknown type, try to convert to string then encode
                json_data = str(post_data).encode('utf-8')
        

        post_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['controls']}/{self._id}/{instruction}"
        try:
            self._get_json(post_url, timeout=3, post_data=json_data)
        except ScanException:
            if instruction in ["poweroff", "reboot", "restart"]:
                pass  # Expected for power operations
            else:
                raise DeviceError(f"Cannot send '{instruction}' to device in status '{current_status}'")
       
        self._update_info()
    
    def send_settings(self, post_data: Union[Dict, bytes]) -> Any:
        """Send settings update to ethoscope."""

        # Handle post_data properly
        if isinstance(post_data, bytes):
            json_data = post_data
        else:
            json_data = json.dumps(post_data).encode('utf-8')

        update_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['update']}/{self._id}"
        result = self._get_json(update_url, timeout=3, post_data=json_data)
        self._update_info()
        return result
    
    def _check_instruction_status(self, instruction: str):
        """Validate that instruction is allowed for current status."""
        self._update_info()
        
        current_status = self._device_status.status_name
        allowed_statuses = self.ALLOWED_INSTRUCTIONS.get(instruction)
        
        if allowed_statuses is None:
            raise ValueError(f"Unknown instruction: {instruction}")
        
        if current_status not in allowed_statuses:
            raise DeviceError(f"Cannot send '{instruction}' to device in status '{current_status}'")
    
    def machine_info(self) -> Dict[str, Any]:
        """Get machine information from ethoscope."""
        if not self._id:
            return {}
        
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['machine_info']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return {}
    
    def connected_module(self) -> Dict[str, Any]:
        """Get connected module information."""
        if not self._id:
            return {}
        
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['connected_module']}/{self._id}"
            return self._get_json(url, timeout=12)
        except ScanException:
            return {}
    
    def videofiles(self) -> List[str]:
        """Get list of available video files."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['videofiles']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return []
    
    def user_options(self) -> Optional[Dict[str, Any]]:
        """Get user options from ethoscope."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['user_options']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return None
    
    def get_log(self) -> Optional[Dict[str, Any]]:
        """Get log from ethoscope."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['log']}/{self._id}"
            return self._get_json(url)
        except ScanException:
            return None
    
    def dump_sql_db(self) -> Optional[Dict[str, Any]]:
        """Trigger SQL database dump on ethoscope."""
        try:
            url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['dumpdb']}/{self._id}"
            return self._get_json(url, timeout=3)
        except ScanException:
            return None
    
    def dumpSQLdb(self):
        """Legacy method name for compatibility."""
        return self.dump_sql_db()
    
    def last_image(self):
        """Get the last drawn image from ethoscope."""
        if self._device_status.status_name not in self.ALLOWED_INSTRUCTIONS["stop"]:
            return None
        
        try:
            img_path = self._info["last_drawn_img"]
            img_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['static']}/{img_path}"
            return urllib.request.urlopen(img_url, timeout=10)
        except (KeyError, urllib.error.HTTPError) as e:
            self._logger.error(f"Could not get image for {self._id}: {e}")
            raise
    
    def dbg_img(self):
        """Get debug image from ethoscope."""
        try:
            img_path = self._info["dbg_img"]
            img_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['static']}/{img_path}"
            return urllib.request.urlopen(img_url, timeout=10)
        except Exception as e:
            self._logger.warning(f"Could not get debug image: {e}")
            return None
    
    def relay_stream(self) -> Iterator[bytes]:
        """Relay video stream from ethoscope."""
        client_socket = None
        try:
            # Establish connection
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.connect((self._ip, STREAMING_PORT))
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
            
            data = b""
            payload_size = struct.calcsize("Q")
            
            while True:
                # Get message size
                while len(data) < payload_size:
                    packet = client_socket.recv(4096)
                    if not packet:
                        break
                    data += packet
                
                if len(data) < payload_size:
                    break
                
                # Unpack message size
                packed_msg_size = data[:payload_size]
                data = data[payload_size:]
                msg_size = struct.unpack("Q", packed_msg_size)[0]
                
                # Get frame data
                while len(data) < msg_size:
                    packet = client_socket.recv(4096)
                    if not packet:
                        break
                    data += packet
                
                if len(data) < msg_size:
                    break
                
                # Extract frame
                frame_data = data[:msg_size]
                data = data[msg_size:]
                
                try:
                    frame = pickle.loads(frame_data)
                    yield (b'--frame\r\nContent-Type:image/jpeg\r\n\r\n' + 
                           frame.tobytes() + b'\r\n')
                except Exception as e:
                    self._logger.warning(f"Error processing frame: {e}")
                    break
                    
        except Exception as e:
            self._logger.error(f"Error in relay_stream: {e}")
        finally:
            if client_socket:
                client_socket.close()
    
    def _update_info(self):
        """Enhanced info update with state management."""
        previous_status_obj = self.get_device_status()
        previous_status = previous_status_obj.status_name if previous_status_obj else "offline"
        
        # Safely increment ping counter
        self._ping_count += 1
        self._info['ping'] = self._ping_count
        
        # Fetch device info
        if not self._fetch_device_info():
            self._handle_unreachable_state(previous_status)
            raise ScanException(f"Failed to fetch device info from {self._ip}")
        
        new_status = self._info.get('status', 'offline')
        
        # Update device status using DeviceStatus system
        is_user_triggered = self._is_user_initiated_stop()
        trigger_source = "user" if is_user_triggered else "system"
        
        # Special case: If device is found in an active tracking state, it must be user-initiated
        # Tracking cannot start without user intervention
        if new_status in ['running', 'recording', 'streaming'] and previous_status == 'offline':
            is_user_triggered = True
            trigger_source = "user"
            self._logger.info(f"Device {self._id} found in tracking state {new_status} - marking as user-initiated")
        
        # Check if this is a graceful operation
        alert_config = self._config.get_custom('alerts') or {}
        graceful_grace_minutes = alert_config.get('graceful_shutdown_grace_minutes', 5)
        graceful_grace_seconds = graceful_grace_minutes * 60
        
        if (self._last_user_instruction in DeviceStatus.GRACEFUL_OPERATIONS and 
            self._last_user_action and (time.time() - self._last_user_action) < graceful_grace_seconds):
            trigger_source = "graceful"
        
        # Update status if it changed
        if previous_status != new_status:
            self._update_device_status(new_status, is_user_triggered, trigger_source,
                                     metadata={"previous_status": previous_status})
        
        # Handle device states
        if previous_status == "offline" and new_status != "offline":
            self._handle_device_coming_online()
        
        # Check if backup_filename from API response has changed
        current_backup_filename = self._info.get("backup_filename")
        previous_backup_filename = getattr(self, '_last_backup_filename', None)
        backup_filename_changed = (current_backup_filename != previous_backup_filename and current_backup_filename is not None)

        # Update backup path if status changed, backup_path is None, or backup_filename changed
        if (previous_status != new_status or self._info.get("backup_path") is None or backup_filename_changed):
            # Force recalculation if backup filename changed
            self._make_backup_path(force_recalculate=backup_filename_changed)
            # Track the backup_filename used for this backup_path
            self._last_backup_filename = current_backup_filename
        
        self._handle_state_transition(previous_status, new_status)
        self._update_backup_status_from_database_info()
        
        # Check for storage warnings
        self._check_storage_warnings()
    
    def _fetch_device_info(self) -> bool:
        """Fetch latest device information."""
        try:
            if not self._id:
                self._update_id()
            
            _data_url = f"http://{self._ip}:{self._port}/{self.REMOTE_PAGES['data']}/{self._id}"
            new_info = self._get_json(_data_url)
           
            with self._lock:
                self._info.update(new_info)
                self._info['last_seen'] = time.time()
                
                # Update logger name if we have a valid device name
                self._update_logger_name()
            
            return True

        except ScanException as e:
            try:
                did = self._get_json(self._id_url)
                if did:
                    with self._lock:
                        self._info['last_seen'] = time.time()
                        self._update_device_status("busy", trigger_source="network")

                self._logger.warning(f"The device is online and responding but cannot communicate its status. Flagged as busy. {e}")
                return False
            
            except ScanException as e:

                self._logger.warning(f"Error fetching device info: {e}")
                return False
    
    def _update_logger_name(self):
        """Update logger name to use proper device name if available."""
        device_name = self._info.get('name', '')
        
        # Only update if we have a valid device name and it's different from current
        if device_name and device_name != 'unknown_name':
            new_logger_name = f"{device_name}"
            current_logger_name = self._logger.name
            
            # Only update if the name has changed
            if new_logger_name != current_logger_name:
                self._logger = logging.getLogger(new_logger_name)
                self._logger.debug(f"Updated logger name from {current_logger_name} to {new_logger_name}")
    
    def _handle_unreachable_state(self, previous_status: str):
        """Handle unreachable device state with timeout logic."""
        # Check if device is already unreachable and if timeout has been exceeded
        current_status = self.get_device_status()
        
        # Get timeout from configuration
        alert_config = self._config.get_custom('alerts') or {}
        unreachable_timeout = alert_config.get('unreachable_timeout_minutes', 20)
        
        if current_status.status_name == 'busy':
                self._logger.info(f"Device {self._id} has been busy for longer than timeout allowed ({unreachable_timeout}m), but it's still online.")
                self._update_device_status("busy", trigger_source="system", metadata={"reason": "unreachable_timeout"})
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="busy")
                return

        elif current_status.status_name == 'unreached':
            # Device is already unreachable, check for timeout
            if current_status.is_timeout_exceeded(unreachable_timeout):
                self._logger.info(f"Device {self._id} unreachable timeout exceeded ({unreachable_timeout}m), marking as offline")
                self._update_device_status("offline", trigger_source="system", metadata={"reason": "unreachable_timeout"})
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="offline")
                return
        else:
            # Device is becoming unreachable for the first time
            self._logger.info(f"Device {self._id} becoming unreachable (was {previous_status})")
            self._update_device_status("unreached", trigger_source="network", metadata={"previous_status": previous_status})
        
        # Handle running experiments
        if 'experimental_info' in self._info and 'run_id' in self._info['experimental_info']:
            run_id = self._info['experimental_info']['run_id']
            self._edb.flagProblem(run_id=run_id, message="unreached")
            
            if previous_status == 'running':
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="unreached")
        elif previous_status == 'stopped':
            self._edb.updateEthoscopes(ethoscope_id=self._id, status="offline")
        
        self._reset_info()
    
    def _handle_device_coming_online(self):
        """Handle device coming online."""
        device_name = self._info.get('name', '')
        if "ETHOSCOPE_OOO" in device_name.upper():
            return
        
        try:
            machine_info_dict = self.machine_info()
            machine_info = ""
            
            if 'kernel' in machine_info_dict and 'pi_version' in machine_info_dict:
                machine_info = f"{machine_info_dict['kernel']} on pi{machine_info_dict['pi_version']}"
            
            self._edb.updateEthoscopes(
                ethoscope_id=self._id,
                ethoscope_name=device_name,
                last_ip=self._ip,
                machineinfo=machine_info
            )
        except Exception as e:
            self._logger.error(f"Error updating device info: {e}")
    
    def _is_user_initiated_stop(self) -> bool:
        """
        Check if a recent status change was user-initiated.
        
        Returns:
            True if the status change was likely user-initiated
        """
        if not self._last_user_action:
            return False
        
        # Get timeout from configuration
        alert_config = self._config.get_custom('alerts') or {}
        timeout_seconds = alert_config.get('user_action_timeout_seconds', 30)
        
        # Check if user action was recent
        time_since_action = time.time() - self._last_user_action
        if time_since_action > timeout_seconds:
            return False
        
        # Check if the last instruction was a stop command
        if self._last_user_instruction in ['stop', 'poweroff', 'reboot', 'restart']:
            return True
        
        return False
    
    def _handle_state_transition(self, previous_status: str, new_status: str):
        """Handle state transitions for experiment tracking."""
        try:
            experimental_info = self._info.get('experimental_info', {})
            if not experimental_info:
                return
            
            user_name = experimental_info.get('name', '')
            location = experimental_info.get('location', '')
            run_id = experimental_info.get('run_id')
            
            if not run_id:
                return
            
            # State transition handlers
            transitions = {
                ('initialising', 'running'): lambda: self._edb.addRun(
                    run_id=run_id, experiment_type="tracking",
                    ethoscope_name=self._info.get('name', ''), ethoscope_id=self._id,
                    username=user_name, user_id="", location=location,
                    alert=True, comments="", 
                    experimental_data=self._info.get('backup_path', '')
                ),
                ('initialising', 'stopping'): lambda: self._edb.flagProblem(
                    run_id=run_id, message="self-stopped"
                ),
                ('running', 'stopped'): lambda: self._edb.stopRun(run_id=run_id),
                ('running', 'unreached'): lambda: self._edb.updateEthoscopes(
                    ethoscope_id=self._id, status="unreached"
                ),
                ('stopped', 'unreached'): lambda: self._edb.updateEthoscopes(
                    ethoscope_id=self._id, status="offline"
                )
            }
            
            transition_key = (previous_status, new_status)
            if transition_key in transitions:
                transitions[transition_key]()
                
            # Send alerts for specific state transitions
            self._send_state_transition_alerts(previous_status, new_status, run_id)
                
        except Exception as e:
            self._logger.error(f"Error handling state transition: {e}")
    
    def _send_state_transition_alerts(self, previous_status: str, new_status: str, run_id: str):
        """Send email alerts for state transitions using DeviceStatus logic."""
        try:
            device_name = self._info.get('name', self._id)
            current_status = self.get_device_status()
            
            # Get timeout from configuration
            alert_config = self._config.get_custom('alerts') or {}
            unreachable_timeout = alert_config.get('unreachable_timeout_minutes', 20)
            
            # Use DeviceStatus logic to determine if alert should be sent
            if not current_status.should_send_alert(unreachable_timeout):
                self._logger.debug(f"Alert suppressed for status change {previous_status} -> {new_status} "
                                 f"(user_triggered: {current_status.is_user_triggered}, "
                                 f"graceful: {current_status.is_graceful_operation()})")
                return
            
            # Send appropriate alerts based on status transition
            last_seen = datetime.datetime.fromtimestamp(self._info.get('last_seen', time.time()))
            
            if new_status == 'stopped':
                # Send stopped alert (DeviceStatus already filtered out tracking->stopped transitions)
                self._notification_service.send_device_stopped_alert(
                    device_id=self._id,
                    device_name=device_name,
                    run_id=run_id,
                    last_seen=last_seen
                )
            elif new_status == 'unreached':
                # Send unreachable alert (DeviceStatus already checked timeout)
                self._notification_service.send_device_unreachable_alert(
                    device_id=self._id,
                    device_name=device_name,
                    last_seen=last_seen
                )
                
        except Exception as e:
            self._logger.error(f"Error sending state transition alerts: {e}")
    
    def _check_storage_warnings(self):
        """Check for storage warnings and send alerts if necessary."""
        try:
            # Get storage information from device
            machine_info = self._info.get('machine_info', {})
            
            # Check for disk usage information
            disk_usage = machine_info.get('disk_usage', {})
            if not disk_usage:
                return
            
            # Get alert threshold from configuration
            alert_config = self._config.get_custom('alerts') or {}
            threshold = alert_config.get('storage_warning_threshold', 80)
            
            # Check each mounted filesystem
            for mount_point, usage_info in disk_usage.items():
                if isinstance(usage_info, dict):
                    used_percent = usage_info.get('used_percent', 0)
                    available_space = usage_info.get('available', 'unknown')
                    
                    if used_percent >= threshold:
                        device_name = self._info.get('name', self._id)
                        
                        # Format available space for display
                        if isinstance(available_space, (int, float)):
                            available_space = f"{available_space / (1024**3):.1f} GB"
                        
                        self._notification_service.send_storage_warning_alert(
                            device_id=self._id,
                            device_name=device_name,
                            storage_percent=used_percent,
                            available_space=str(available_space)
                        )
                        
        except Exception as e:
            self._logger.error(f"Error checking storage warnings: {e}")
    

    def _update_backup_status_from_database_info(self):
        """Update backup status using new comprehensive device data format."""
        if time.time() - self._last_db_info < DB_UPDATE_INTERVAL:
            return
        
        try:
            # Check if device provides backup status directly (new format)
            if 'backup_status' in self._info:
                # Use the backup status provided directly by the device
                backup_status = self._info['backup_status']
                backup_size = self._info.get('backup_size', 0)
                time_since_backup = self._info.get('time_since_backup', 0)
                
                # Store additional backup info
                self._info['backup_size'] = backup_size
                self._info['time_since_backup'] = time_since_backup
                
                self._logger.debug(f"Device {self._ip}: Using device-provided backup status: {backup_status}")
                self._last_db_info = time.time()
                return
            
            # Fall back to legacy method for backward compatibility
            # Get database_info from the ethoscope's response
            database_info = self._info.get("database_info", {})
            backup_path = self._info.get("backup_path")
            
            if not backup_path:
                self._logger.debug(f"Device {self._ip}: No backup_path available, attempting to create one")
                self._make_backup_path(force_recalculate=True)
                backup_path = self._info.get("backup_path")
                if not backup_path:
                    self._logger.debug(f"Device {self._ip}: Still no backup_path after creation attempt")
                    self._info['backup_status'] = "No Backup"
                    return
                else:
                    self._logger.debug(f"Device {self._ip}: Created backup_path: {backup_path}")
                
            # Check if backup file exists
            if not os.path.exists(backup_path):
                self._logger.debug(f"Device {self._ip}: Backup file does not exist: {backup_path}")
                self._info['backup_status'] = "File Missing"
                return
            
            # Check if we have new nested databases structure
            databases = self._info.get("databases", {})
            if databases:
                # Use new database structure to determine backup status
                self._update_backup_status_from_databases(databases, backup_path)
                return
            
            # Check database_info status (old structure)
            db_status = database_info.get("db_status", "unknown")
            if db_status == "error":
                self._logger.debug(f"Device {self._ip}: Database info shows error status")
                self._info['backup_status'] = "DB Error"
                return
            
            # Determine database type from metadata or experimental_info
            result_writer_type = None
            
            # Try to get result writer type from experimental_info (which contains selected_options)
            experimental_info = self._info.get("experimental_info", {})
            if "selected_options" in experimental_info:
                try:
                    # selected_options is stored as a string representation, parse it carefully
                    selected_options_str = experimental_info["selected_options"]
                    if "SQLiteResultWriter" in selected_options_str:
                        result_writer_type = "SQLiteResultWriter"
                    elif "ResultWriter" in selected_options_str:
                        result_writer_type = "ResultWriter"
                except (KeyError, TypeError):
                    pass
            
            # Fallback: check backup path extension if metadata not available
            if not result_writer_type:
                result_writer_type = "SQLiteResultWriter" if backup_path.endswith('.db') else "ResultWriter"
                self._logger.debug(f"Device {self._ip}: Using fallback database type detection: {result_writer_type}")
            
            # Store result writer type for backup system reference
            self._info['result_writer_type'] = result_writer_type
            
            if result_writer_type == "SQLiteResultWriter":
                # Use file-based backup status for SQLite (rsync-compatible)
                self._update_sqlite_backup_status(database_info, backup_path)
            else:
                # Use table count-based backup status for MySQL
                self._update_mysql_backup_status(database_info, backup_path)
        except Exception as e:
            self._logger.warning(f"Device {self._ip}: Failed to update backup status from database_info: {e}")
            self._info['backup_status'] = "Error"
        
        self._last_db_info = time.time()
    
    def _update_backup_status_from_databases(self, databases: dict, backup_path: str):
        """Update backup status using new nested databases structure."""
        try:
            # Check MariaDB databases first
            mariadb_databases = databases.get("MariaDB", {})
            if mariadb_databases:
                # Use the first MariaDB database (typically there's only one)
                db_name = list(mariadb_databases.keys())[0]
                db_info = mariadb_databases[db_name]
                
                # Check if we have table counts for backup percentage calculation
                if 'table_counts' in db_info:
                    from ethoscope_node.utils.backups_helpers import get_sqlite_table_counts, calculate_backup_percentage_from_table_counts
                    
                    remote_table_counts = db_info['table_counts']
                    backup_table_counts = get_sqlite_table_counts(backup_path)
                    
                    backup_percentage = calculate_backup_percentage_from_table_counts(
                        remote_table_counts, backup_table_counts)
                    
                    # Store backup status info
                    self._info['backup_status'] = backup_percentage
                    self._info['backup_size'] = db_info.get('filesize', 0)
                    self._info['time_since_backup'] = time.time() - db_info.get('date', time.time())
                    
                    self._logger.debug(f"Device {self._ip}: MariaDB backup status: {backup_percentage}%")
                    return
            
            # Check SQLite databases
            sqlite_databases = databases.get("SQLite", {})
            if sqlite_databases:
                # Use the first SQLite database (typically there's only one) 
                db_name = list(sqlite_databases.keys())[0]
                db_info = sqlite_databases[db_name]
                
                # For SQLite, use file size comparison
                local_backup_size = os.path.getsize(backup_path)
                remote_db_size = db_info.get("filesize", 0)
                
                if remote_db_size > 0:
                    backup_percentage = min(100.0, (local_backup_size / remote_db_size) * 100)
                else:
                    backup_percentage = 0.0
                
                # Store backup status info
                self._info['backup_status'] = backup_percentage
                self._info['backup_size'] = local_backup_size
                self._info['time_since_backup'] = time.time() - db_info.get('date', time.time())
                
                self._logger.debug(f"Device {self._ip}: SQLite backup status: {backup_percentage}%")
                return
            
            # No databases found
            self._logger.debug(f"Device {self._ip}: No databases found in nested structure")
            self._info['backup_status'] = "No Database"
            
        except Exception as e:
            self._logger.error(f"Device {self._ip}: Failed to update backup status from databases: {e}")
            self._info['backup_status'] = "Error"
    
    def _update_sqlite_backup_status(self, database_info, backup_path):
        """Update backup status for SQLite databases using file-based comparison."""
        try:
            # Get file sizes
            local_backup_size = os.path.getsize(backup_path)
            remote_db_size = database_info.get("db_size_bytes", 0)
            
            # Calculate backup percentage based on file size
            if remote_db_size > 0:
                backup_percentage = min(100.0, (local_backup_size / remote_db_size) * 100)
            else:
                # If no remote size info, assume 100% if file exists
                backup_percentage = 100.0 if local_backup_size > 0 else 0.0
            
            # Calculate time since last backup update
            backup_mtime = os.path.getmtime(backup_path)
            time_since_backup = time.time() - backup_mtime
            
            self._info['backup_status'] = backup_percentage
            self._info['backup_size'] = local_backup_size
            self._info['time_since_backup'] = time_since_backup
            self._info['backup_type'] = 'sqlite_file'
            self._info['backup_method'] = 'rsync'  # Indicate rsync-based backup
            
            self._logger.debug(f"Device {self._ip}: SQLite backup status {backup_percentage:.1f}% "
                             f"(size: {local_backup_size}/{remote_db_size} bytes, "
                             f"age: {time_since_backup/3600:.1f}h)")
                             
        except Exception as e:
            self._logger.warning(f"Device {self._ip}: Failed to update SQLite backup status: {e}")
            self._info['backup_status'] = "SQLite Error"
    
    def _update_mysql_backup_status(self, database_info, backup_path):
        """Update backup status for MySQL databases using table count comparison."""
        try:
            # Get table counts from ethoscope
            remote_table_counts = database_info.get("table_counts", {})
            if not remote_table_counts:
                self._logger.debug(f"Device {self._ip}: No table counts available from ethoscope")
                self._info['backup_status'] = "No Table Data"
                return
            
            # Get table counts from backup database
            backup_table_counts = get_sqlite_table_counts(backup_path)
            if not backup_table_counts:
                self._logger.debug(f"Device {self._ip}: Could not read backup database")
                self._info['backup_status'] = "Backup Read Error"
                return
            
            # Calculate backup percentage based on table counts
            backup_percentage = calculate_backup_percentage_from_table_counts(
                remote_table_counts, backup_table_counts)
            
            # Get file sizes for additional info
            local_backup_size = os.path.getsize(backup_path)
            remote_db_size = database_info.get("db_size_bytes", 0)
            
            # Calculate time since last backup update
            backup_mtime = os.path.getmtime(backup_path)
            time_since_backup = time.time() - backup_mtime
            
            self._info['backup_status'] = backup_percentage
            self._info['backup_size'] = local_backup_size
            self._info['remote_table_counts'] = remote_table_counts
            self._info['backup_table_counts'] = backup_table_counts
            self._info['time_since_backup'] = time_since_backup
            self._info['backup_type'] = 'mysql_table'
            self._info['backup_method'] = 'incremental'  # Indicate table-based incremental backup
            
            # Create detailed logging with table comparison
            total_remote = sum(remote_table_counts.values())
            total_backup = sum(backup_table_counts.values())
            
            self._logger.debug(f"Device {self._ip}: MySQL backup status {backup_percentage:.1f}% "
                             f"(rows: {total_backup}/{total_remote}, "
                             f"size: {local_backup_size}/{remote_db_size} bytes)")
                             
        except Exception as e:
            self._logger.warning(f"Device {self._ip}: Failed to update MySQL backup status: {e}")
            self._info['backup_status'] = "MySQL Error"
    
    def _make_backup_path(self, force_recalculate: bool = False, service_type: str = "auto"):
        """
        Creates the full path for the backup file, gathering info from the ethoscope.
        Now supports service-type awareness to prevent backup collisions.
        
        Args:
            timeout: Request timeout
            force_recalculate: Force recalculation of backup path
            service_type: Type of backup service ('mariadb', 'sqlite', 'auto')
        
        The full backup_path will look something like:
        /ethoscope_data/results/0256424ac3f545b6b3c687723085ffcb/ETHOSCOPE_025/2025-06-13_16-05-37/2025-06-13_16-05-37_0256424ac3f545b6b3c687723085ffcb.db
        """
        try:
            # Skip if backup path is already set and valid (unless forced)
            if self._info.get("backup_path") is not None and not force_recalculate:
                return
            
            output_db_file = None
            backup_filename = None
            
            # Determine which backup filename to use based on service type
            if service_type == "mariadb":
                backup_filename = self._get_backup_filename_for_db_type("MariaDB")
            elif service_type == "sqlite":
                backup_filename = self._get_backup_filename_for_db_type("SQLite")
            else:
                # Auto mode: use the appropriate backup filename based on database type
                backup_filename = self._get_appropriate_backup_filename()
            
            if backup_filename:
                try:
                    fname, _ = os.path.splitext(backup_filename)
                    parts = fname.split("_")
                    if len(parts) >= 3:
                        backup_date = parts[0]
                        backup_time = parts[1] 
                        etho_id = "_".join(parts[2:])
                        
                        output_db_file = os.path.join(self._results_dir,
                                                    etho_id,
                                                    self._info["name"],
                                                    f"{backup_date}_{backup_time}",
                                                    backup_filename)
                        self._logger.info(f"Created {service_type} backup path: {output_db_file}")
                    else:
                        self._logger.error(f"Invalid backup filename format: {backup_filename}")
                        output_db_file = None
                except Exception as e:
                    self._logger.error(f"Error parsing backup filename '{backup_filename}': {e}")
                    output_db_file = None
            else:
                #self._logger.warning(f"No backup filename available for {service_type} backup")
                output_db_file = None
            
            self._info["backup_path"] = output_db_file
            
        except Exception as e:
            self._logger.error(f"Error creating backup path: {e}")
            self._info["backup_path"] = None
    
    def _get_backup_filename_for_db_type(self, db_type: str) -> str:
        """Get backup filename for a specific database type.
        
        Args:
            db_type: Database type ("MariaDB" or "SQLite")
            
        Returns:
            str: Backup filename or None if not found
        """
        try:
            # Check new nested databases structure first
            databases = self._info.get("databases", {})
            db_type_databases = databases.get(db_type, {})
            
            if db_type_databases:
                # For now, take the first database (typically there's only one)
                db_name = list(db_type_databases.keys())[0]
                db_info = db_type_databases[db_name]
                backup_filename = db_info.get("backup_filename")
                if backup_filename:
                    return backup_filename
            
            # Fallback to old structure for backward compatibility
            database_info = self._info.get("database_info", {})
            db_type_key = db_type.lower()  # Convert to lowercase for old structure
            db_type_info = database_info.get(db_type_key, {})
            if db_type_info.get("exists", False):
                db_type_current = db_type_info.get("current", {})
                return db_type_current.get("backup_filename")
            
            return None
        except Exception as e:
            self._logger.error(f"Error getting {db_type} backup filename: {e}")
            return None
    
    def _get_appropriate_backup_filename(self) -> str:
        """Get the appropriate backup filename based on the active database type."""
        try:
            # Check new nested databases structure first
            databases = self._info.get("databases", {})
            
            # Try MariaDB first
            if databases.get("MariaDB"):
                mariadb_filename = self._get_backup_filename_for_db_type("MariaDB")
                if mariadb_filename:
                    return mariadb_filename
            
            # Try SQLite next
            if databases.get("SQLite"):
                sqlite_filename = self._get_backup_filename_for_db_type("SQLite")
                if sqlite_filename:
                    return sqlite_filename
            
            # Fallback to old structure for backward compatibility
            database_info = self._info.get("database_info", {})
            active_type = database_info.get("active_type", "none")
            
            if active_type == "mariadb":
                return self._get_backup_filename_for_db_type("MariaDB")
            elif active_type == "sqlite":
                return self._get_backup_filename_for_db_type("SQLite")
            else:
                # Fallback to legacy behavior
                if "backup_filename" in self._info and self._info["backup_filename"]:
                    return self._info["backup_filename"]
                elif (self._device_status.status_name == 'stopped' and 
                      "previous_backup_filename" in self._info and 
                      self._info["previous_backup_filename"]):
                    return self._info["previous_backup_filename"]
                return None
        except Exception as e:
            self._logger.error(f"Error getting appropriate backup filename: {e}")
            return None
    
    def setup_ssh_authentication(self) -> bool:
        """
        Setup SSH key authentication for passwordless connection to ethoscope.
        
        Uses sshpass to copy the node's SSH public key to the ethoscope device
        using the ethoscope user with password 'ethoscope'.
        
        Returns:
            bool: True if SSH key setup was successful, False otherwise
        """
        try:
            # Get SSH key paths
            keys_dir = os.path.join(self._config_dir, 'keys')
            private_key_path, public_key_path = ensure_ssh_keys(keys_dir)
            
            # Use sshpass with ssh-copy-id to setup passwordless authentication
            cmd = [
                'sshpass', '-p', 'ethoscope',
                'ssh-copy-id', 
                '-i', public_key_path,
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'ConnectTimeout=10',
                f'ethoscope@{self._ip}'
            ]
            
            self._logger.info(f"Setting up SSH key authentication for ethoscope@{self._ip}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                self._logger.info(f"SSH key authentication setup successful for {self._ip}")
                return True
            else:
                self._logger.warning(f"SSH key setup failed for {self._ip}: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self._logger.error(f"SSH key setup timed out for {self._ip}")
            return False
        except FileNotFoundError:
            self._logger.error("sshpass command not found. Please install sshpass package")
            return False
        except Exception as e:
            self._logger.error(f"Failed to setup SSH key authentication for {self._ip}: {e}")
            return False


class DeviceScanner:
    """Base scanner class for discovering devices via Zeroconf."""
    
    SUFFIX = ".local"
    SERVICE_TYPE = "_device._tcp.local."
    DEVICE_TYPE = "device"
    
    def __init__(self, device_refresh_period: float = 5, device_class=BaseDevice):
        self._zeroconf = None
        self.devices: List[BaseDevice] = []
        self.device_refresh_period = device_refresh_period
        self._device_class = device_class
        self._browser = None
        self._lock = RLock()
        self._logger = logging.getLogger(self.__class__.__name__)
        self.results_dir = ""  # Default, override in subclasses
        self._is_running = False
    
    def start(self):
        """Start the Zeroconf service browser."""
        if self._is_running:
            self._logger.warning("Scanner already running")
            return
            
        try:
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._browser = ServiceBrowser(self._zeroconf, self.SERVICE_TYPE, self)
            self._is_running = True
            self._logger.info(f"Started {self.DEVICE_TYPE} scanner")
        except Exception as e:
            self._logger.error(f"Error starting scanner: {e}")
            self._cleanup_zeroconf()
            raise
    
    def stop(self):
        """Stop the scanner and cleanup."""
        if not self._is_running:
            return
            
        self._is_running = False
        
        try:
            # Stop all devices first
            with self._lock:
                for device in self.devices:
                    try:
                        device.stop()
                    except Exception as e:
                        self._logger.warning(f"Error stopping device {device.ip()}: {e}")
            
            # Clean up zeroconf resources
            self._cleanup_zeroconf()
            
            self._logger.info(f"Stopped {self.DEVICE_TYPE} scanner")
            
        except Exception as e:
            self._logger.error(f"Error stopping scanner: {e}")
    
    def _cleanup_zeroconf(self):
        """Clean up zeroconf resources properly."""
        try:
            if self._browser:
                self._browser.cancel()
                self._browser = None
                
            if self._zeroconf:
                self._zeroconf.close()
                self._zeroconf = None
                
        except Exception as e:
            self._logger.warning(f"Error during zeroconf cleanup: {e}")
    
    def __del__(self):
        """Destructor to ensure cleanup."""
        try:
            self.stop()
        except Exception:
            pass
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
    
    @property
    def current_devices_id(self) -> List[str]:
        """Get list of current device IDs."""
        with self._lock:
            return [device.id() for device in self.devices if device.id()]
    
    def get_all_devices_info(self) -> Dict[str, Dict[str, Any]]:
        """Get information for all devices."""
        with self._lock:
            return {device.id(): device.info() for device in self.devices if device.id()}
    
    def get_device(self, device_id: str) -> Optional[BaseDevice]:
        """Get device by ID."""
        with self._lock:
            for device in self.devices:
                if device.id() == device_id:
                    return device
        return None
    
    def add(self, ip: str, port: int, name: Optional[str] = None, 
           device_id: Optional[str] = None, zcinfo: Optional[Dict] = None):
        """Add a device to the scanner."""
        if not self._is_running:
            self._logger.warning(f"Cannot add device {ip}:{port} - scanner not running")
            return
            
        try:
            with self._lock:
                # Check if device already exists by IP (more immediate than waiting for ID)
                for existing_device in self.devices:
                    if existing_device.ip() == ip:
                        was_skipping = existing_device._skip_scanning
                        device_status = existing_device._device_status.status_name
                        
                        self._logger.info(f"Device at {ip} already exists (was skipping: {was_skipping}, status: {device_status}), updating zeroconf info")
                        
                        if hasattr(existing_device, 'zeroconf_name'):
                            existing_device.zeroconf_name = name
                        
                        # Reset error state and re-enable scanning in case it was offline
                        existing_device.reset_error_state()
                        existing_device.skip_scanning(False)
                        
                        # Explicitly reset status to allow device info to be updated
                        with existing_device._lock:
                            existing_device._update_device_status("offline", trigger_source="system")
                            existing_device._info.update({
                                'last_seen': time.time()
                            })
                        
                        self._logger.info(f"Re-enabled scanning for {self.DEVICE_TYPE} at {ip} (was skipping: {was_skipping})")
                        return
                
                # Create and start device
                device_kwargs = {
                    'ip': ip,
                    'port': port,
                    'refresh_period': self.device_refresh_period,
                    'results_dir': getattr(self, 'results_dir', '')
                }
                
                # Only add config_dir if the device class supports it (for Ethoscope)
                if hasattr(self, 'config_dir'):
                    import inspect
                    sig = inspect.signature(self._device_class.__init__)
                    if 'config_dir' in sig.parameters:
                        device_kwargs['config_dir'] = self.config_dir
                
                device = self._device_class(**device_kwargs)
                
                if hasattr(device, 'zeroconf_name'):
                    device.zeroconf_name = name
                
                device.start()
                
                # Check for duplicates
                device_id = device_id or device.id()
                if device_id in self.current_devices_id:
                    self._logger.info(f"Device {device_id} already exists, skipping")
                    device.stop()
                    return
                
                self.devices.append(device)
                self._logger.info(f"Added {self.DEVICE_TYPE} {name} (ID: {device_id}) at {ip}:{port}")
                
        except Exception as e:
            self._logger.error(f"Error adding device at {ip}:{port}: {e}")
    
    def add_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for new services."""
        if not self._is_running:
            return
            
        try:
            info = zeroconf.get_service_info(service_type, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                port = info.port
                self.add(ip, port, name, zcinfo=info.properties)
                
        except Exception as e:
            self._logger.error(f"Error adding zeroconf service {name}: {e}")
    
    def remove_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for removed services - mark devices as offline."""
        if not self._is_running:
            return

        info = zeroconf.get_service_info(service_type, name)
        if not info or not info.addresses:
            return

        ip = socket.inet_ntoa(info.addresses[0])
        with self._lock:
            for device in self.devices:
                if device.ip() == ip:
                    device_id = device.id()
                    self._logger.info(f"{self.DEVICE_TYPE} {device_id or 'unknown'} at {ip} went offline via zeroconf removal")
                    
                    # Stop interrogating the device but keep it in the list
                    device.skip_scanning(True)
                    
                    # Explicitly set status to offline
                    with device._lock:
                        device._update_device_status("offline", trigger_source="system")
                        device._info.update({
                            'last_seen': time.time()
                        })
                    
                    break
    
    def update_service(self, zeroconf, service_type: str, name: str):
        """Zeroconf callback for service updates."""
        pass


class EthoscopeScanner(DeviceScanner):
    """Ethoscope-specific scanner with database integration."""
    
    SERVICE_TYPE = "_ethoscope._tcp.local."
    DEVICE_TYPE = "ethoscope"
    
    def __init__(self, device_refresh_period: float = 5, 
                 results_dir: str = "/ethoscope_data/results", device_class=Ethoscope,
                 config_dir: str = "/etc/ethoscope", 
                 config: Optional[EthoscopeConfiguration] = None):
        super().__init__(device_refresh_period, device_class)
        self.results_dir = results_dir
        self.config_dir = config_dir
        self.config = config  # Store config to pass to devices
        self._edb = ExperimentalDB(config_dir)
        self.timestarted = datetime.datetime.now()  # Keep original name for compatibility
    
    def get_all_devices_info(self, include_inactive: bool = False) -> Dict[str, Dict[str, Any]]:
        """Get device info including offline devices from database."""
        # Start with database devices
        try:
            db_devices = self._edb.getEthoscope('all', asdict=True)
            devices_info = {}
            
            for device_id, device_data in db_devices.items():
                # Include device if it's active, or if include_inactive is True
                if device_data.get('active') == 1 or include_inactive:
                    devices_info[device_id] = {
                        'name': device_data.get('ethoscope_name', ''),
                        'id': device_id,
                        'status': device_data.get('status', 'offline'),  # Default to offline for database-only devices
                        'ip': device_data.get('last_ip', ''),
                        'last_ip': device_data.get('last_ip', ''),
                        'time': device_data.get('last_seen', 0),
                        'active': device_data.get('active', 1)
                    }
        except Exception as e:
            self._logger.error(f"Error getting devices from database: {e}")
            devices_info = {}
        
        # Update with devices from scanner (includes offline)
        with self._lock:
            for device in self.devices:
                device_id = device.id()
                device_name = getattr(device, 'name', 'N/A')
                
                if device_name != "ETHOSCOPE_000":
                    info = device.info()
                    info.update({
                        "time_since_backup": self._get_last_backup_time(device),
                        "backup_size": self._get_backup_size(device)
                    })
                    
                    # Preserve name from database if device doesn't have a proper name
                    if device_id in devices_info:
                        db_name = devices_info[device_id].get('name', '')
                        scanner_name = info.get('name', '')
                        
                        # If scanner has no name or unknown name, preserve database name
                        if not scanner_name or scanner_name in ['', 'unknown_name', 'N/A']:
                            if db_name:
                                info['name'] = db_name
                        
                        # Merge with existing database info, scanner info takes precedence except for name preservation above
                        devices_info[device_id].update(info)
                    else:
                        devices_info[device_id] = info
                else:
                    # Special case for ETHOSCOPE_000
                    devices_info[device_name] = device.info()
        
        return devices_info
    
    def _get_backup_size(self, device: Ethoscope) -> int:
        """Get backup file size."""
        try:
            backup_path = device.info().get("backup_path")
            if backup_path and os.path.exists(backup_path):
                return os.path.getsize(backup_path)
        except Exception:
            pass
        return 0
    
    def _get_last_backup_time(self, device: Ethoscope) -> Optional[float]:
        """Get time since last backup."""
        try:
            backup_path = device.info().get("backup_path")
            if backup_path and os.path.exists(backup_path):
                return time.time() - os.path.getmtime(backup_path)
        except Exception:
            pass
        return None
    
    def add(self, ip: str, port: int = ETHOSCOPE_PORT, name: Optional[str] = None,
           device_id: Optional[str] = None, zcinfo: Optional[Dict] = None):
        """Add ethoscope with enhanced error handling and non-blocking initialization."""
        if not self._is_running:
            self._logger.warning(f"Cannot add device {ip}:{port} - scanner not running")
            return
            
        try:
            # Extract name and ID from zeroconf info
            if zcinfo:
                try:
                    name = zcinfo.get(b'MACHINE_NAME', b'').decode('utf-8') or name
                    device_id = zcinfo.get(b'MACHINE_ID', b'').decode('utf-8') or device_id
                except (AttributeError, UnicodeDecodeError):
                    if name:
                        try:
                            name_parts = name.split(".")[0].split("-")
                            if len(name_parts) == 2:
                                name, device_id = name_parts
                        except (IndexError, ValueError):
                            pass
            
            # Check if device already exists by IP (more immediate than waiting for ID)
            with self._lock:
                for existing_device in self.devices:
                    if existing_device.ip() == ip:
                        was_skipping = existing_device._skip_scanning
                        device_status = existing_device._device_status.status_name
                        
                        self._logger.info(f"Ethoscope at {ip} already exists (was skipping: {was_skipping}, status: {device_status}), updating zeroconf info")
                        
                        if hasattr(existing_device, 'zeroconf_name'):
                            existing_device.zeroconf_name = name
                        
                        # Reset error state and re-enable scanning in case it was offline
                        existing_device.reset_error_state()
                        existing_device.skip_scanning(False)
                        
                        # Explicitly reset status to allow device info to be updated
                        with existing_device._lock:
                            existing_device._update_device_status("offline", trigger_source="system")
                            existing_device._info.update({
                                'last_seen': time.time()
                            })
                        
                        self._logger.info(f"Re-enabled scanning for ethoscope at {ip} (was skipping: {was_skipping})")
                        return
            
            # Create device with minimal blocking
            with self._lock:
                try:
                    device_kwargs = {
                        'ip': ip,
                        'port': port,
                        'refresh_period': self.device_refresh_period,
                        'results_dir': self.results_dir
                    }
                    
                    # Only add config_dir if the device class supports it
                    if hasattr(self, 'config_dir'):
                        import inspect
                        sig = inspect.signature(self._device_class.__init__)
                        if 'config_dir' in sig.parameters:
                            device_kwargs['config_dir'] = self.config_dir
                    
                    # Add config parameter if supported to avoid duplicate configuration loading
                    if hasattr(self, 'config') and self.config is not None:
                        import inspect
                        sig = inspect.signature(self._device_class.__init__)
                        if 'config' in sig.parameters:
                            device_kwargs['config'] = self.config
                    
                    device = self._device_class(**device_kwargs)
                    
                    if hasattr(device, 'zeroconf_name'):
                        device.zeroconf_name = name
                    
                    # Start the device thread immediately (don't wait for ID)
                    device.start()
                    self.devices.append(device)
                    
                    # Log with available information
                    display_id = device_id or "pending"
                    self._logger.info(f"Added ethoscope {name} (ID: {display_id}) at {ip}:{port}")
                    
                except Exception as e:
                    self._logger.error(f"Error creating ethoscope device at {ip}:{port}: {e}")
                    # Don't re-raise, just log the error to avoid blocking other discoveries
                    
        except Exception as e:
            self._logger.error(f"Error in add method for {ip}:{port}: {e}")
    
    def retire_device(self, device_id: str, active: int = 0) -> Dict[str, Any]:
        """Retire device by updating database status."""
        try:
            self._edb.updateEthoscopes(ethoscope_id=device_id, active=active)
            updated_data = self._edb.getEthoscope(device_id, asdict=True)[device_id]
            return {
                'id': updated_data['ethoscope_id'],
                'active': updated_data['active']
            }
        except Exception as e:
            self._logger.error(f"Error retiring device {device_id}: {e}")
            raise