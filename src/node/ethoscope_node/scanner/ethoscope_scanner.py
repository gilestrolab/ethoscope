import urllib.request
import urllib.error
import urllib.parse
import os
import datetime
import json
import time
import logging
import struct
import subprocess
from threading import Thread, Event
from typing import Dict, List, Optional, Any, Iterator, Union
from dataclasses import dataclass
from zeroconf import Zeroconf

from ethoscope_node.scanner.base_scanner import BaseDevice, DeviceScanner, DeviceStatus, ScanException
from ethoscope_node.scanner.ethoscope_streaming import EthoscopeStreamManager

from ethoscope_node.utils.etho_db import ExperimentalDB
from ethoscope_node.utils.configuration import ensure_ssh_keys, EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import get_sqlite_table_counts, calculate_backup_percentage_from_table_counts
from ethoscope_node.notifications.email import EmailNotificationService

# Constants
STREAMING_PORT = 8887
ETHOSCOPE_PORT = 9000
DB_UPDATE_INTERVAL = 30  # seconds


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
        
        # Streaming manager
        self._stream_manager = None
        
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
        current_status = self._device_status.status_name
        
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
                raise DeviceError(f"Cannot send '{{instruction}}' to device in status '{{current_status}}'")
       
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
        """Relay video stream from ethoscope using shared connection."""
        # Lazy import to avoid circular dependencies
        #from .streaming import EthoscopeStreamManager
        
        # Create stream manager if it doesn't exist
        if self._stream_manager is None:
            self._stream_manager = EthoscopeStreamManager(self._ip, self._id)
        
        # Delegate to stream manager
        return self._stream_manager.get_stream_for_client()
    
    def stop(self):
        """Stop the ethoscope device and cleanup streaming connections."""
        # Stop stream manager if it exists
        if self._stream_manager is not None:
            self._stream_manager.stop()
            self._stream_manager = None
        
        # Call parent stop method
        super().stop()
    
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
                did = self._get_json(self._id_url, timeout=5)
                if did:
                    with self._lock:
                        self._info['last_seen'] = time.time()
                        self._update_device_status("busy", trigger_source="network")

                self._logger.warning(f"The device is online and responding but cannot communicate its status. Flagged as busy. {e}")
                return False
            
            except ScanException as inner_e:
                # Device doesn't respond to either /data/<id> or /id - mark for offline transition
                current_status = self.get_device_status()
                if current_status and current_status.status_name == 'busy':
                    # If previously busy, transition to unreached to start timeout countdown
                    self._logger.warning(f"Busy device {self._id} no longer responding to any endpoint. Starting offline transition. {inner_e}")
                    self._handle_unreachable_state('busy')
                else:
                    self._logger.warning(f"Error fetching device info: {inner_e}")
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
                # Ensure updated logger inherits proper level
                if self._logger.level == logging.NOTSET:
                    self._logger.setLevel(logging.getLogger().level or logging.INFO)
                self._logger.debug(f"Updated logger name from {current_logger_name} to {new_logger_name}")
    
    def _handle_unreachable_state(self, previous_status: str):
        """Handle unreachable device state with timeout logic."""
        # Check if device is already unreachable and if timeout has been exceeded
        current_status = self.get_device_status()
        
        # Get timeout from configuration
        alert_config = self._config.get_custom('alerts') or {}
        unreachable_timeout = alert_config.get('unreachable_timeout_minutes', 20)
        
        if current_status.status_name == 'busy':
            # Check if busy device has exceeded timeout - if so, transition to offline
            busy_timeout = alert_config.get('busy_timeout_minutes', 10)  # Shorter timeout for busy devices
            if current_status.is_timeout_exceeded(busy_timeout):
                self._logger.info(f"Device {self._id} busy timeout exceeded ({busy_timeout}m), marking as offline")
                self._update_device_status("offline", trigger_source="system", metadata={"reason": "busy_timeout"})
                self._edb.updateEthoscopes(ethoscope_id=self._id, status="offline")
                return
            else:
                self._logger.info(f"Device {self._id} has been busy for {current_status.get_age_minutes():.1f}m (timeout: {busy_timeout}m)")
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
                # Skip devices with empty or invalid IDs
                if not device_id or device_id.strip() == '':
                    self._logger.debug(f"Skipping device with empty ID from database")
                    continue
                
                # Skip devices with no name or empty names unless they have valid IPs
                device_name = device_data.get('ethoscope_name', '').strip()
                device_ip = device_data.get('last_ip', '').strip()
                
                # Skip devices that have no meaningful identifying information
                if (not device_name or device_name.lower() in ['none', '']) and (not device_ip or device_ip.lower() in ['none', '']):
                    self._logger.debug(f"Skipping device {device_id} with no name and no IP from database")
                    continue
                
                # Include device if it's active, or if include_inactive is True
                if device_data.get('active') == 1 or include_inactive:
                    devices_info[device_id] = {
                        'name': device_name,
                        'id': device_id,
                        'status': device_data.get('status', 'offline'),  # Default to offline for database-only devices
                        'ip': device_ip,
                        'last_ip': device_ip,
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
                
                # Skip devices with empty or invalid IDs from scanner
                if not device_id or device_id.strip() == '':
                    self._logger.debug(f"Skipping scanner device with empty ID")
                    continue
                
                if device_name != "ETHOSCOPE_000":
                    info = device.info()
                    info.update({
                        "time_since_backup": self._get_last_backup_time(device),
                        "backup_size": self._get_backup_size(device)
                    })
                    
                    # Skip devices with no meaningful identifying information
                    scanner_name = info.get('name', '').strip()
                    scanner_ip = info.get('ip', '').strip()
                    
                    if (not scanner_name or scanner_name.lower() in ['none', '', 'n/a', 'unknown_name']) and (not scanner_ip or scanner_ip.lower() in ['none', '']):
                        self._logger.debug(f"Skipping scanner device {device_id} with no name and no IP")
                        continue
                    
                    # Preserve name from database if device doesn't have a proper name
                    if device_id in devices_info:
                        db_name = devices_info[device_id].get('name', '')
                        
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
                        
                        # Force ID update to handle device renaming (ETHOSCOPE_000 -> new name)
                        # This is critical when devices are renamed via webUI
                        try:
                            old_id = existing_device.id()
                            existing_device._update_id()
                            new_id = existing_device.id()
                            
                            if old_id != new_id:
                                self._logger.info(f"Device at {ip} ID changed from '{old_id}' to '{new_id}' (device was renamed)")
                                # Update database entry for the new device ID
                                self._handle_device_id_change(existing_device, old_id, new_id)
                            else:
                                self._logger.debug(f"Device at {ip} ID unchanged: {new_id}")
                                
                        except Exception as e:
                            self._logger.warning(f"Failed to update ID for device at {ip}: {e}")
                        
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
    
    def _handle_device_id_change(self, device: 'Ethoscope', old_id: str, new_id: str):
        """Handle database updates when a device ID changes (e.g., ETHOSCOPE_000 -> new name)."""
        try:
            device_name = device.info().get('name', '')
            device_ip = device.ip()
            
            # Log the device renaming
            self._logger.info(f"Handling device ID change: {old_id} -> {new_id} (name: {device_name}, IP: {device_ip})")
            
            # If old device was ETHOSCOPE_000, it might not be in database yet
            if old_id == 'ETHOSCOPE_000' or not old_id:
                self._logger.info(f"Device {new_id} was previously ETHOSCOPE_000 or had empty ID, creating new database entry")
                # Just update/create entry for new ID
                self._edb.updateEthoscopes(
                    ethoscope_id=new_id,
                    ethoscope_name=device_name,
                    last_ip=device_ip,
                    status="offline"  # Will be updated by normal scanning
                )
            else:
                # Handle actual ID change from one real ID to another
                try:
                    # Check if old device exists in database
                    old_device_data = self._edb.getEthoscope(old_id, asdict=True)
                    if old_device_data and old_id in old_device_data:
                        self._logger.info(f"Retiring old device entry {old_id} and creating new entry {new_id}")
                        # Retire old device
                        self._edb.updateEthoscopes(ethoscope_id=old_id, active=0)
                        
                        # Create new device entry, preserving relevant info from old entry
                        old_info = old_device_data[old_id]
                        self._edb.updateEthoscopes(
                            ethoscope_id=new_id,
                            ethoscope_name=device_name,
                            last_ip=device_ip,
                            status="offline",
                            comments=f"Renamed from {old_id}"
                        )
                    else:
                        # Old device not in database, just create new entry
                        self._logger.info(f"Old device {old_id} not found in database, creating new entry for {new_id}")
                        self._edb.updateEthoscopes(
                            ethoscope_id=new_id,
                            ethoscope_name=device_name,
                            last_ip=device_ip,
                            status="offline"
                        )
                except Exception as db_error:
                    self._logger.warning(f"Error handling old device {old_id} in database: {db_error}")
                    # Still create entry for new device
                    self._edb.updateEthoscopes(
                        ethoscope_id=new_id,
                        ethoscope_name=device_name,
                        last_ip=device_ip,
                        status="offline"
                    )
            
        except Exception as e:
            self._logger.error(f"Error handling device ID change from {old_id} to {new_id}: {e}")
    
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