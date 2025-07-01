"""
Backup Helpers Module - High-level Backup Orchestration & Management

This module provides the high-level backup orchestration layer that coordinates database and 
video backups across multiple ethoscope devices. It handles device discovery, backup scheduling,
progress tracking, and provides a web API for backup status monitoring.

Key Responsibilities:
====================

1. BACKUP ORCHESTRATION & COORDINATION:
   - Manages parallel backup operations across multiple ethoscope devices
   - Coordinates between database backups (via mysql_backup.py) and video file downloads
   - Implements backup scheduling with configurable intervals (default: 5 minutes)
   - Handles backup prioritization and resource allocation

2. DEVICE DISCOVERY & MANAGEMENT:
   - Discovers active ethoscope devices via node server API or direct scanning
   - Filters devices based on status (active, stopped, running) for backup eligibility
   - Maintains device state and handles device offline/online transitions
   - Manages backup path validation and creation

3. BACKUP EXECUTION CLASSES:
   - BackupClass: Handles database backup operations using MySQLdbToSQLite
   - VideoBackupClass: Manages video file downloads from ethoscope devices
   - BaseBackupClass: Common functionality and status reporting for both backup types

4. PROGRESS TRACKING & STATUS REPORTING:
   - Tracks backup progress, success/failure rates, and timing information
   - Provides real-time status updates during backup operations
   - Implements backup completion markers and validation
   - Detects data duplication issues in METADATA and VAR_MAP tables

5. FILE SYSTEM MANAGEMENT:
   - Manages backup file locking to prevent concurrent operations
   - Creates and maintains backup directory structures
   - Handles backup completion markers and status files
   - Provides file integrity checking and validation

6. WEB API & MONITORING:
   - GenericBackupWrapper: Main threading class that runs continuous backup operations
   - Provides status API endpoints for external monitoring
   - Handles backup job initiation and progress tracking
   - Supports both continuous and on-demand backup modes

Classes:
========
- BackupStatus: Data class for tracking backup state and progress
- BaseBackupClass: Common backup functionality and status reporting
- BackupClass: Database backup operations (uses mysql_backup.py)
- VideoBackupClass: Video file download and synchronization
- GenericBackupWrapper: Main backup coordinator and threading manager

This module uses mysql_backup.py for low-level database operations and is used by
backup_tool.py for the actual backup service implementation.
"""

from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.mysql_backup import MySQLdbToSQLite, DBNotReadyError
from ethoscope_node.utils.configuration import ensure_ssh_keys
from ethoscope.utils.video_utils import list_local_video_files
import os
import logging
import time
import datetime
import traceback
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import json
import threading
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Union, Iterator, Tuple
import hashlib
import fcntl
import tempfile
import sqlite3


@dataclass
class BackupStatus:
    """Data class for backup status tracking."""
    name: str = ""
    status: str = ""
    started: int = 0
    ended: int = 0
    processing: bool = False
    count: int = 0
    synced: Dict = None
    progress: Dict = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.synced is None:
            self.synced = {}
        if self.progress is None:
            self.progress = {}
        if self.metadata is None:
            self.metadata = {}


class BackupError(Exception):
    """Custom exception for backup operations."""
    pass


class BackupLockError(Exception):
    """Exception raised when backup file is locked by another process."""
    pass


@contextmanager
def backup_file_lock(backup_path: str):
    """
    File locking context manager to prevent concurrent backup operations
    on the same SQLite database file.
    """
    lock_file_path = f"{backup_path}.lock"
    lock_file = None
    
    try:
        # Create lock file directory if it doesn't exist
        os.makedirs(os.path.dirname(lock_file_path), exist_ok=True)
        
        # Open lock file for writing
        lock_file = open(lock_file_path, 'w')
        
        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError) as e:
            raise BackupLockError(f"Cannot acquire lock for {backup_path}: {e}")
        
        # Write process info to lock file
        lock_file.write(f"PID: {os.getpid()}\nTimestamp: {datetime.datetime.now()}\n")
        lock_file.flush()
        
        yield lock_file
        
    finally:
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                # Remove lock file
                if os.path.exists(lock_file_path):
                    os.unlink(lock_file_path)
            except (IOError, OSError):
                pass  # Ignore cleanup errors


def get_backup_completion_file(backup_path: str) -> str:
    """Get the path to the backup completion marker file."""
    return f"{backup_path}.completed"


def is_backup_recent(backup_path: str, max_age_hours: int = 1) -> bool:
    """
    Check if a successful backup was completed recently.
    
    Args:
        backup_path: Path to the backup file
        max_age_hours: Maximum age in hours to consider backup recent
        
    Returns:
        bool: True if recent successful backup exists
    """
    completion_file = get_backup_completion_file(backup_path)
    
    if not os.path.exists(completion_file):
        return False
    
    try:
        completion_time = os.path.getmtime(completion_file)
        age_hours = (time.time() - completion_time) / 3600
        return age_hours < max_age_hours
    except (OSError, IOError):
        return False


def mark_backup_completed(backup_path: str, stats: dict = None):
    """
    Mark a backup as successfully completed.
    
    Args:
        backup_path: Path to the backup file
        stats: Optional backup statistics to store
    """
    completion_file = get_backup_completion_file(backup_path)
    
    try:
        completion_data = {
            'completed_at': datetime.datetime.now().isoformat(),
            'backup_file': backup_path,
            'file_size': os.path.getsize(backup_path) if os.path.exists(backup_path) else 0,
            'stats': stats or {}
        }
        
        with open(completion_file, 'w') as f:
            json.dump(completion_data, f, indent=2)
            
    except (OSError, IOError) as e:
        logging.warning(f"Could not create completion marker for {backup_path}: {e}")


class BaseBackupClass:
    """Base class for backup operations with common functionality."""
    
    def __init__(self, device_info: Dict, results_dir: str):
        self._device_info = device_info
        self._device_id = device_info.get("id", "unknown")
        self._device_name = device_info.get("name", "unknown")
        self._ip = device_info.get("ip", "")
        self._results_dir = results_dir
        self._logger = logging.getLogger(f"{self.__class__.__name__}_{self._device_id}")
    
    def _yield_status(self, status: str, message: str) -> str:
        """Helper method to yield consistent status messages."""
        status_msg = json.dumps({"status": status, "message": message})
        self._logger.info(f"[{self._device_id}] {message}")
        return status_msg
    
    def backup(self) -> Iterator[str]:
        """Abstract method to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement backup method")
    
    def check_sync_status(self) -> Dict:
        """Abstract method to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement check_sync_status method")


class BackupClass(BaseBackupClass):
    """Optimized database backup class."""
    
    DB_CREDENTIALS = {
        "name": "ethoscope_db",
        "user": "ethoscope", 
        "password": "ethoscope"
    }
    
    # Database connection timeout (seconds)
    DB_CONNECTION_TIMEOUT = 30
    DB_OPERATION_TIMEOUT = 120
    
    def __init__(self, device_info: Dict, results_dir: str):
        super().__init__(device_info, results_dir)
        self._database_ip = os.path.basename(self._ip)
    
    def backup(self) -> Iterator[str]:
        """
        Performs database backup with improved error handling and status reporting.
        Uses MySQLdbToSQLite's built-in max(id) incremental backup approach.
        
        Yields:
            str: JSON-encoded status messages with progress updates
        """
        start_time = time.time()
        
        try:
            self._logger.info(f"[{self._device_id}] === DATABASE BACKUP STARTING ===")
            yield self._yield_status("info", f"Backup initiated for device {self._device_id}")
            
            # Validate backup path
            self._logger.info(f"[{self._device_id}] Validating backup path...")
            backup_path = self._get_backup_path()
            db_name = f"{self._device_name}_db"
            
            self._logger.info(f"[{self._device_id}] Backup path validated: {backup_path}")
            yield self._yield_status(
                "info", 
                f"Preparing to back up database '{db_name}' to {backup_path}"
            )
            
            # Perform incremental backup using MySQLdbToSQLite's built-in max(id) logic
            self._logger.info(f"[{self._device_id}] Starting incremental database backup (max ID approach)...")
            success, backup_stats = self._perform_database_backup(backup_path, db_name)
            
            elapsed_time = time.time() - start_time
            
            if success:
                self._logger.info(f"[{self._device_id}] === DATABASE BACKUP COMPLETED SUCCESSFULLY in {elapsed_time:.1f}s ===")
                yield self._yield_status("success", f"Backup completed successfully for device {self._device_id} in {elapsed_time:.1f}s")
                return True
            else:
                self._logger.error(f"[{self._device_id}] === DATABASE BACKUP FAILED after {elapsed_time:.1f}s ===")
                yield self._yield_status("error", f"Backup failed for device {self._device_id} after {elapsed_time:.1f}s")
                return False
                
        except DBNotReadyError as e:
            elapsed_time = time.time() - start_time
            warning_msg = f"Database not ready for device {self._device_id}, will retry later (after {elapsed_time:.1f}s)"
            self._logger.warning(f"[{self._device_id}] {warning_msg}: {e}")
            yield self._yield_status("warning", warning_msg)
            return False
            
        except BackupError as e:
            elapsed_time = time.time() - start_time
            self._logger.error(f"[{self._device_id}] BackupError after {elapsed_time:.1f}s: {e}")
            yield self._yield_status("error", f"Backup error after {elapsed_time:.1f}s: {str(e)}")
            return False
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            error_msg = f"Unexpected error during backup for device {self._device_id} after {elapsed_time:.1f}s: {str(e)}"
            self._logger.error(f"[{self._device_id}] {error_msg}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            yield self._yield_status("error", error_msg)
            return False
    
    def _get_backup_path(self) -> str:
        """Get and validate backup path."""
        if "backup_path" not in self._device_info:
            raise BackupError(f"Could not obtain backup path for device {self._device_id}")
        
        backup_path = self._device_info["backup_path"]
        if not backup_path:
            raise BackupError(f"Backup path is None for device {self._device_id}")
        
        full_backup_path = os.path.join(self._results_dir, backup_path)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(full_backup_path), exist_ok=True)
        
        return full_backup_path
    
    def _perform_database_backup(self, backup_path: str, db_name: str) -> Tuple[bool, dict]:
        """
        Perform the actual database backup operation using MySQLdbToSQLite's 
        built-in incremental max(id) approach to prevent duplicates.
        """
        backup_stats = {}
        
        try:
            self._logger.info(f"[{self._device_id}] Initializing MySQL to SQLite mirror connection...")
            self._logger.info(f"[{self._device_id}] Target: {backup_path}, DB: {db_name}, Host: {self._database_ip}")
            
            # Initialize MySQL to SQLite mirror (handles incremental updates automatically)
            mirror = MySQLdbToSQLite(
                backup_path,
                db_name,
                remote_host=self._database_ip,
                remote_user=self.DB_CREDENTIALS["user"],
                remote_pass=self.DB_CREDENTIALS["password"]
            )
            self._logger.info(f"[{self._device_id}] MySQL mirror initialized successfully")
            
            # Update ROI tables using built-in max(id) incremental logic
            self._logger.info(f"[{self._device_id}] Starting incremental ROI tables update (max ID approach)...")
            mirror.update_roi_tables()
            self._logger.info(f"[{self._device_id}] Incremental ROI tables update completed")
            
            # Verify backup integrity
            self._logger.info(f"[{self._device_id}] Starting database comparison...")
            comparison_status = mirror.compare_databases()
            self._logger.info(f"[{self._device_id}] Database comparison: {comparison_status:.2f}% match")
            
            backup_stats['comparison_percentage'] = comparison_status
            backup_stats['backup_success'] = comparison_status > 0
            
            # Check for data duplication
            self._logger.info(f"[{self._device_id}] Checking for data duplication...")
            duplication_found = self._check_data_duplication(backup_path)
            backup_stats['data_duplication'] = duplication_found
            
            if comparison_status > 0:
                self._logger.info(f"[{self._device_id}] Incremental database backup successful (match: {comparison_status:.2f}%)")
            else:
                self._logger.warning(f"[{self._device_id}] Database backup may have issues (match: {comparison_status:.2f}%)")
            
            return comparison_status > 0, backup_stats
            
        except Exception as e:
            backup_stats['error'] = str(e)
            self._logger.error(f"[{self._device_id}] Database backup failed: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            raise BackupError(f"Database backup failed: {e}")
    
    def _check_data_duplication(self, backup_path: str) -> bool:
        """
        Check for data duplication in METADATA and VAR_MAP tables.
        
        Args:
            backup_path: Path to the SQLite backup file
            
        Returns:
            bool: True if duplicates found in either table, False otherwise
        """
        try:
            self._logger.info(f"[{self._device_id}] Checking for data duplication in backup database...")
            
            with sqlite3.connect(backup_path) as conn:
                cursor = conn.cursor()
                
                # Check METADATA table for duplicates
                metadata_duplicates = False
                try:
                    cursor.execute("SELECT COUNT(*) FROM METADATA")
                    total_metadata = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT field, value FROM METADATA)")
                    distinct_metadata = cursor.fetchone()[0]
                    
                    metadata_duplicates = total_metadata > distinct_metadata
                    self._logger.debug(f"[{self._device_id}] METADATA table: {total_metadata} total, {distinct_metadata} distinct")
                    
                except sqlite3.OperationalError as e:
                    self._logger.warning(f"[{self._device_id}] Could not check METADATA table: {e}")
                
                # Check VAR_MAP table for duplicates
                varmap_duplicates = False
                try:
                    cursor.execute("SELECT COUNT(*) FROM VAR_MAP")
                    total_varmap = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM (SELECT DISTINCT var_name, sql_type, functional_type FROM VAR_MAP)")
                    distinct_varmap = cursor.fetchone()[0]
                    
                    varmap_duplicates = total_varmap > distinct_varmap
                    self._logger.debug(f"[{self._device_id}] VAR_MAP table: {total_varmap} total, {distinct_varmap} distinct")
                    
                except sqlite3.OperationalError as e:
                    self._logger.warning(f"[{self._device_id}] Could not check VAR_MAP table: {e}")
                
                duplicates_found = metadata_duplicates or varmap_duplicates
                
                if duplicates_found:
                    self._logger.warning(f"[{self._device_id}] Data duplication detected - METADATA: {metadata_duplicates}, VAR_MAP: {varmap_duplicates}")
                else:
                    self._logger.info(f"[{self._device_id}] No data duplication detected")
                
                return duplicates_found
                
        except Exception as e:
            self._logger.error(f"[{self._device_id}] Error checking data duplication: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            return False  # Return False on error to avoid false positives
    
    def check_sync_status(self) -> Dict:
        """Check synchronization status of the database backup."""
        # TODO: Implement database sync status checking
        return {'tracking_db': {}}


class VideoBackupClass(BaseBackupClass):
    """Rsync-based video backup class with real-time progress reporting."""
    
    DEFAULT_PORT = 9000
    REQUEST_TIMEOUT = 30
    
    def __init__(self, device_info: Dict, results_dir: str, port: int = None):
        super().__init__(device_info, results_dir)
        self._port = port or self.DEFAULT_PORT
        self._device_url = f"http://{self._ip}:{self._port}"
    
    def backup(self) -> Iterator[str]:
        """
        Performs rsync-based video backup with real-time progress reporting.
        
        Yields:
            str: JSON-encoded status messages with detailed progress updates
        """
        import subprocess
        import re
        
        start_time = time.time()
        try:
            self._logger.info(f"[{self._device_id}] === RSYNC VIDEO BACKUP STARTING ===")
            yield self._yield_status("info", f"Rsync video backup initiated for device {self._device_id}")
            
            # Step 1: Get video information from ethoscope
            self._logger.info(f"[{self._device_id}] Retrieving video metadata...")
            video_info = self.get_video_list_json()
            if not video_info:
                self._logger.warning(f"[{self._device_id}] Failed to retrieve video information")
                yield self._yield_status("error", f"Failed to retrieve video information from device {self._device_id}")
                return False
            
            metadata = video_info.get('metadata', {})
            video_files = video_info.get('video_files', {})
            
            if not video_files:
                self._logger.info(f"[{self._device_id}] No videos found for backup")
                yield self._yield_status("warning", f"No videos to backup for device {self._device_id}")
                return True
            
            # Extract key information
            source_dir = metadata.get('videos_directory', '/ethoscope_data/videos')
            device_ip = metadata.get('device_ip', self._ip)
            total_files = metadata.get('total_files', len(video_files))
            disk_usage = metadata.get('disk_usage_bytes', 0)
            
            self._logger.info(f"[{self._device_id}] Found {total_files} videos ({disk_usage} bytes) in {source_dir}")
            yield self._yield_status("info", f"Found {total_files} videos to backup from {source_dir}")
            
            # Store device metadata for status reporting
            device_metadata = {
                'total_files': total_files,
                'disk_usage_bytes': disk_usage,
                'videos_directory': source_dir,
                'device_ip': device_ip
            }
            yield self._yield_status("metadata", json.dumps(device_metadata))
            
            # Step 2: Prepare rsync command
            destination_dir = self._results_dir
            os.makedirs(destination_dir, exist_ok=True)
            
            # Get SSH key path for authentication
            private_key_path, _ = ensure_ssh_keys()
            
            rsync_source = f"ethoscope@{device_ip}:{source_dir}/"
            rsync_command = [
                'rsync', 
                '-avz',           # archive, verbose, compress
                '--progress',     # show progress
                '--partial',      # keep partial files
                '--timeout=300',  # 5 minute timeout
                '-e', f'ssh -i {private_key_path} -o StrictHostKeyChecking=no',  # SSH key authentication
                rsync_source, 
                destination_dir
            ]
            
            self._logger.info(f"[{self._device_id}] Starting rsync: {' '.join(rsync_command)}")
            yield self._yield_status("info", f"Starting rsync from {rsync_source} to {destination_dir}")
            
            # Step 3: Execute rsync with progress monitoring
            process = subprocess.Popen(
                rsync_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            files_transferred = 0
            bytes_transferred = 0
            current_file = ""
            
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if not line:
                    continue
                    
                self._logger.debug(f"[{self._device_id}] rsync: {line}")
                
                # Parse progress information
                if line.endswith('bytes/sec'):
                    # Progress line format: "1,234,567  67%   123.45kB/s    0:00:12"
                    match = re.search(r'(\d{1,3}(?:,\d{3})*)\s+(\d+)%\s+(.+?/s)', line)
                    if match:
                        bytes_so_far = int(match.group(1).replace(',', ''))
                        percentage = int(match.group(2))
                        speed = match.group(3)
                        
                        yield self._yield_status(
                            "info", 
                            f"Transferring {current_file}: {percentage}% complete ({speed})"
                        )
                        
                elif line.startswith('./') or '/' in line:
                    # File being transferred
                    if not line.startswith('rsync:') and not line.startswith('total size'):
                        current_file = os.path.basename(line)
                        files_transferred += 1
                        yield self._yield_status(
                            "info", 
                            f"Transferring file {files_transferred}/{total_files}: {current_file}"
                        )
                        
            # Wait for rsync to complete
            return_code = process.wait()
            elapsed_time = time.time() - start_time
            
            if return_code == 0:
                self._logger.info(f"[{self._device_id}] === RSYNC VIDEO BACKUP COMPLETED SUCCESSFULLY in {elapsed_time:.1f}s ===")
                yield self._yield_status("success", f"Rsync backup completed successfully in {elapsed_time:.1f}s")
                return True
            else:
                error_msg = f"Rsync failed with return code {return_code} after {elapsed_time:.1f}s"
                self._logger.error(f"[{self._device_id}] {error_msg}")
                yield self._yield_status("error", error_msg)
                return False
                
        except Exception as e:
            elapsed_time = time.time() - start_time
            error_msg = f"Unexpected error during rsync backup for device {self._device_id} after {elapsed_time:.1f}s: {e}"
            self._logger.error(f"[{self._device_id}] {error_msg}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            yield self._yield_status("error", error_msg)
            return False

    
    
    def get_video_list_json(self) -> Optional[Dict]:
        """
        Get video list in JSON format with metadata from ethoscope device.
        
        This method calls the enhanced /list_video_files API endpoint that returns
        both video file information and device metadata (IP, disk usage, etc.)
        
        Returns:
            dict: Enhanced video information with structure:
                {
                    'video_files': {filename: {path, hash, ...}},
                    'metadata': {
                        'videos_directory': str,
                        'total_files': int,
                        'disk_usage_bytes': int,
                        'device_ip': str,
                        'machine_id': str,
                        'machine_name': str
                    }
                }
        """
        video_list_url = f"{self._device_url}/list_video_files"
        
        try:
            self._logger.info(f"[{self._device_id}] Requesting video list from: {video_list_url}")
            
            with urllib.request.urlopen(video_list_url, timeout=self.REQUEST_TIMEOUT) as response:
                video_data = json.load(response)
                
                # Validate response structure
                if not isinstance(video_data, dict):
                    self._logger.warning(f"[{self._device_id}] Invalid response format from enhanced video API")
                    return None
                
                # Extract video files and metadata
                video_files = video_data.get('video_files', {})
                metadata = video_data.get('metadata', {})
                
                self._logger.info(f"[{self._device_id}] Retrieved video list: {len(video_files)} videos, metadata: {list(metadata.keys())}")
                
                return {
                    'video_files': video_files,
                    'metadata': metadata
                }
                
        except urllib.error.HTTPError as e:
            self._logger.warning(f"[{self._device_id}] HTTP error getting video list from {video_list_url}: {e}")
            return None
            
        except json.JSONDecodeError as e:
            self._logger.warning(f"[{self._device_id}] JSON decode error from video list API {video_list_url}: {e}")
            return None
            
        except Exception as e:
            self._logger.error(f"[{self._device_id}] Unexpected error getting video list from {video_list_url}: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            return None
    
    def check_sync_status(self) -> Optional[Dict[str, Dict[str, int]]]:
        """
        Compare sync status between remote and local video files (simple file presence check).
        With rsync, detailed integrity checking is handled by rsync itself.
        
        Returns:
            dict: Sync status with present and total file counts
        """
        try:
            video_info = self.get_video_list_json()
            if not video_info:
                return None
            
            remote_videos = video_info.get('video_files', {})
            local_videos = list_local_video_files(self._results_dir, createMD5=False)
            
            present_files = 0
            total_files = len(remote_videos)
            
            for filename in remote_videos.keys():
                if filename in local_videos:
                    present_files += 1
                else:
                    self._logger.debug(f"File missing locally: {filename}")
            
            return {
                'video_files': {
                    'present': present_files,
                    'total': total_files
                }
            }
            
        except Exception as e:
            self._logger.error(f"Error checking sync status: {e}")
            return None



class GenericBackupWrapper(threading.Thread):
    """
    Optimized backup wrapper with better resource management and error handling.
    """
    
    DEFAULT_BACKUP_INTERVAL = 5 * 60  # 5 minutes
    DEFAULT_MAX_THREADS = 4
    DEFAULT_DEVICE_SCAN_TIMEOUT = 10
    
    def __init__(self, results_dir: str, node_address: str, video: bool = False, 
                 max_threads: int = None):
        super().__init__(daemon=True)
        
        self._results_dir = results_dir
        self._node_address = node_address
        self._is_video_backup = video
        self._max_threads = max_threads or self.DEFAULT_MAX_THREADS
        
        # Thread synchronization
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        
        # Status tracking
        self.backup_status: Dict[str, BackupStatus] = {}
        self.last_backup = ""
        
        # Device discovery tracking
        self._last_device_count = 0
        self._last_discovery_source = 'unknown'
        self._last_discovery_time = None
        
        # Backup cycle tracking
        self._cycle_count = 0
        self._last_cycle_start = None
        
        # Remove retry throttling - incremental backups are safe to run frequently
        
        # Configuration
        self._backup_interval = self.DEFAULT_BACKUP_INTERVAL
        
        self._logger = logging.getLogger(f"BackupWrapper.{self.__class__.__name__}")
        # Ensure logs go to root logger as well
        self._logger.propagate = True
    
    def find_devices(self, only_active: bool = True) -> List[Dict]:
        """
        Find available ethoscope devices.
        
        Args:
            only_active: Whether to return only active devices
            
        Returns:
            list: Available device information
        """
        self._logger.info("Starting device discovery...")
        devices = {}
        
        try:
            self._logger.info(f"Attempting to get devices from node at {self._node_address}")
            devices = self._get_devices_from_node()
            self._logger.info(f"Successfully retrieved {len(devices)} devices from node")
            self._last_discovery_source = 'node'
        except Exception as e:
            self._logger.warning(f"Could not get devices from node: {e}")
            self._logger.info("Falling back to direct device scanning...")
            try:
                devices = self._get_devices_via_scanner()
                self._logger.info(f"Scanner found {len(devices)} devices")
                self._last_discovery_source = 'scanner'
            except Exception as scanner_error:
                self._logger.error(f"Scanner also failed: {scanner_error}")
                self._last_discovery_source = 'failed'
                # Still update discovery tracking even on failure
                import time
                self._last_device_count = 0
                self._last_discovery_time = time.time()
                return []
        
        # Update discovery tracking
        import time
        self._last_device_count = len(devices)
        self._last_discovery_time = time.time()
        
        self._logger.debug(f"Updated device discovery tracking: count={self._last_device_count}, source={self._last_discovery_source}, time={self._last_discovery_time}")
        
        if only_active:
            active_devices = [
                device for device in devices.values() 
                if (device.get("status") not in ["not_in_use", "offline"] and 
                    device.get("name") != "ETHOSCOPE_000")
            ]
            self._logger.info(f"Filtered to {len(active_devices)} active devices")
            return active_devices
        
        all_devices = list(devices.values())
        self._logger.info(f"Returning all {len(all_devices)} devices")
        return all_devices
    
    def _get_devices_from_node(self) -> Dict:
        """Get devices from node server."""
        url = f"http://{self._node_address}/devices"
        
        try:
            self._logger.info(f"Making request to node server: {url}")
            self._logger.info(f"Request timeout: {self.DEFAULT_DEVICE_SCAN_TIMEOUT}s")
            
            req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=self.DEFAULT_DEVICE_SCAN_TIMEOUT) as response:
                self._logger.info(f"Received response from node server (status: {response.status})")
                devices = json.load(response)
                self._logger.info(f"Successfully parsed JSON response with {len(devices)} devices")
                return devices
        except urllib.error.HTTPError as e:
            self._logger.error(f"HTTP error from node {self._node_address}: {e.code} {e.reason}")
            raise
        except urllib.error.URLError as e:
            self._logger.error(f"URL error connecting to node {self._node_address}: {e.reason}")
            raise
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON decode error from node {self._node_address}: {e}")
            raise
        except Exception as e:
            self._logger.error(f"Unexpected error getting devices from node {self._node_address}: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            raise
    
    def _get_devices_via_scanner(self) -> Dict:
        """Get devices via direct scanning as fallback."""
        self._logger.info("Using EthoscopeScanner as fallback")
        
        try:
            self._logger.info("Creating EthoscopeScanner instance...")
            scanner = EthoscopeScanner()
            
            self._logger.info("Starting EthoscopeScanner...")
            scanner.start()
            
            self._logger.info(f"Waiting {self.DEFAULT_DEVICE_SCAN_TIMEOUT} seconds for device discovery...")
            time.sleep(self.DEFAULT_DEVICE_SCAN_TIMEOUT)
            
            self._logger.info("Retrieving discovered devices...")
            devices = scanner.get_all_devices_info()
            self._logger.info(f"Scanner discovered {len(devices)} devices")
            
            return devices
            
        except Exception as e:
            self._logger.error(f"EthoscopeScanner failed: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            raise
        finally:
            try:
                self._logger.info("Stopping EthoscopeScanner...")
                if hasattr(scanner, 'stop'):
                    scanner.stop()
                    self._logger.info("EthoscopeScanner stopped successfully")
                else:
                    self._logger.warning("EthoscopeScanner does not have stop method")
                del scanner
            except Exception as cleanup_error:
                self._logger.error(f"Error during scanner cleanup: {cleanup_error}")
    
    def initiate_backup_job(self, device_info: Dict) -> bool:
        """
        Initiate backup job for a specific device with improved error handling.
        
        Args:
            device_info: Device information dictionary
            
        Returns:
            bool: True if backup completed successfully
        """
        device_id = device_info.get('id', 'unknown')
        device_name = device_info.get('name', 'unknown')
        device_ip = device_info.get('ip', 'unknown')
        device_status = device_info.get('status', 'unknown')
        
        job_start_time = time.time()
        
        try:
            self._logger.info(f"=== INITIATING BACKUP JOB for {device_name} (ID: {device_id}) ===")
            self._logger.info(f"Device details: IP={device_ip}, Status={device_status}, Video={self._is_video_backup}")
            
            # Incremental backups are safe - no need to throttle retry attempts
            
            # Create appropriate backup job
            if self._is_video_backup:
                self._logger.info(f"Creating VideoBackupClass for device {device_id}")
                backup_job = VideoBackupClass(device_info, self._results_dir)
            else:
                self._logger.info(f"Creating BackupClass (database) for device {device_id}")
                backup_job = BackupClass(device_info, self._results_dir)
            
            self._logger.info(f"Backup job object created successfully for device {device_id}")
            
            # Initialize backup status
            self._logger.info(f"Initializing backup status for device {device_id}")
            self._initialize_backup_status(device_id, device_info)
            
            # Perform backup with real-time status updates
            self._logger.info(f"Starting backup execution for device {device_id}")
            success = self._execute_backup_job(device_id, backup_job)
            
            job_elapsed_time = time.time() - job_start_time
            
            # Update final status
            self._logger.info(f"Finalizing backup status for device {device_id} (success={success}, elapsed={job_elapsed_time:.1f}s)")
            self._finalize_backup_status(device_id, backup_job, success)
            
            if success:
                self._logger.info(f"=== BACKUP JOB COMPLETED SUCCESSFULLY for {device_name} in {job_elapsed_time:.1f}s ===")
            else:
                self._logger.error(f"=== BACKUP JOB FAILED for {device_name} after {job_elapsed_time:.1f}s ===")
            
            return success
            
        except Exception as e:
            job_elapsed_time = time.time() - job_start_time
            self._logger.error(f"=== BACKUP JOB CRASHED for {device_name} after {job_elapsed_time:.1f}s ===")
            self._logger.error(f"Backup job failed for device {device_id}: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            self._handle_backup_failure(device_id, str(e))
            return False
    
    def _initialize_backup_status(self, device_id: str, device_info: Dict):
        """Initialize backup status for a device."""
        with self._lock:
            if device_id not in self.backup_status:
                self.backup_status[device_id] = BackupStatus(
                    name=device_info.get('name', ''),
                    status=device_info.get('status', ''),
                    count=0
                )
            
            status = self.backup_status[device_id]
            status.started = int(time.time())
            status.ended = 0
            status.processing = True
            status.progress = {}
            status.count += 1
    
    def _execute_backup_job(self, device_id: str, backup_job) -> bool:
        """Execute backup job and track progress."""
        try:
            for message in backup_job.backup():
                with self._lock:
                    progress_data = json.loads(message)
                    
                    # Check if this is a metadata message
                    if progress_data.get('status') == 'metadata':
                        # Extract and store device metadata
                        try:
                            device_metadata = json.loads(progress_data.get('message', '{}'))
                            self.backup_status[device_id].metadata = device_metadata
                            self._logger.debug(f"Stored device metadata for {device_id}: {device_metadata}")
                        except json.JSONDecodeError:
                            self._logger.warning(f"Could not parse metadata for device {device_id}")
                    else:
                        # Store regular progress information
                        self.backup_status[device_id].progress = progress_data
            return True
            
        except Exception as e:
            self._logger.error(f"Backup execution failed for device {device_id}: {e}")
            return False
    
    def _finalize_backup_status(self, device_id: str, backup_job, success: bool):
        """Finalize backup status after completion."""
        with self._lock:
            status = self.backup_status[device_id]
            
            try:
                status.synced = backup_job.check_sync_status() or {}
            except Exception as e:
                self._logger.warning(f"Could not check sync status for {device_id}: {e}")
                status.synced = {}
            
            status.processing = False
            status.ended = int(time.time())
            
            if not success:
                status.progress = {"status": "error", "message": "Backup failed"}
    
    def _handle_backup_failure(self, device_id: str, error_message: str):
        """Handle backup failure by updating status."""
        with self._lock:
            if device_id in self.backup_status:
                status = self.backup_status[device_id]
                status.processing = False
                status.ended = -1  # Indicates failure
                status.progress = {"status": "error", "message": error_message}
    
    def run(self):
        """
        Main backup loop with comprehensive fault tolerance and auto-recovery.
        """
        # Log thread startup with multiple loggers to ensure visibility
        logging.info("=== BACKUP WRAPPER THREAD STARTING ===")
        self._logger.info(f"=== BACKUP WRAPPER THREAD STARTING ===")
        self._logger.info(f"Configuration: max_threads={self._max_threads}, interval={self._backup_interval}s, video_backup={self._is_video_backup}")
        logging.info(f"Configuration: max_threads={self._max_threads}, interval={self._backup_interval}s, video_backup={self._is_video_backup}")
        
        # Thread health monitoring
        consecutive_failures = 0
        max_consecutive_failures = 5
        last_successful_cycle = time.time()
        
        try:
            with ThreadPoolExecutor(max_workers=self._max_threads, 
                                  thread_name_prefix="BackupWorker") as executor:
                
                while not self._stop_event.is_set():
                    cycle_start_time = time.time()
                    self._cycle_count += 1
                    self._last_cycle_start = cycle_start_time
                    
                    logging.info(f"=== Starting backup cycle #{self._cycle_count} ===")
                    self._logger.info(f"=== Starting backup cycle #{self._cycle_count} ===")
                    
                    cycle_success = False
                    try:
                        # Execute backup cycle with comprehensive fault tolerance
                        self._execute_backup_cycle_with_recovery(executor)
                        
                        cycle_success = True
                        consecutive_failures = 0
                        last_successful_cycle = time.time()
                        
                        cycle_duration = time.time() - cycle_start_time
                        logging.info(f"=== Backup cycle #{self._cycle_count} completed successfully in {cycle_duration:.1f}s ===")
                        self._logger.info(f"=== Backup cycle #{self._cycle_count} completed successfully in {cycle_duration:.1f}s ===")
                        
                    except Exception as e:
                        cycle_success = False
                        consecutive_failures += 1
                        cycle_duration = time.time() - cycle_start_time
                        
                        logging.error(f"=== ERROR in backup cycle #{self._cycle_count} after {cycle_duration:.1f}s: {e} ===")
                        self._logger.error(f"=== ERROR in backup cycle #{self._cycle_count} after {cycle_duration:.1f}s: {e} ===")
                        self._logger.error("Full traceback:", exc_info=True)
                        
                        # Check for critical failure conditions
                        if consecutive_failures >= max_consecutive_failures:
                            time_since_success = time.time() - last_successful_cycle
                            self._logger.error(f"CRITICAL: {consecutive_failures} consecutive backup cycle failures over {time_since_success:.1f}s")
                            self._logger.error("Attempting emergency recovery procedures...")
                            
                            # Emergency recovery
                            try:
                                self._perform_emergency_recovery()
                                consecutive_failures = 0  # Reset after recovery attempt
                            except Exception as recovery_error:
                                self._logger.error(f"Emergency recovery failed: {recovery_error}")
                    
                    # Health monitoring and adaptive behavior
                    if not self._stop_event.is_set():
                        # Adaptive wait time based on recent failures
                        wait_time = self._calculate_adaptive_wait_time(consecutive_failures)
                        
                        self._logger.info(f"Backup cycle #{self._cycle_count} complete. Waiting {wait_time}s until next cycle...")
                        self._logger.info(f"Health status: {consecutive_failures} consecutive failures")
                        
                        # Wait for next cycle or stop event
                        self._stop_event.wait(wait_time)
                    
        except KeyboardInterrupt:
            self._logger.info("=== BACKUP WRAPPER THREAD INTERRUPTED BY USER ===")
        except Exception as e:
            self._logger.error(f"=== BACKUP WRAPPER THREAD CRASHED: {e} ===")
            self._logger.error("Full traceback:", exc_info=True)
            
            # Attempt emergency state preservation
            try:
                self._preserve_emergency_state(str(e))
            except Exception as preserve_error:
                self._logger.error(f"Failed to preserve emergency state: {preserve_error}")
                
        finally:
            final_stats = {
                'total_cycles': self._cycle_count,
                'consecutive_failures': consecutive_failures,
                'last_successful_cycle': last_successful_cycle
            }
            self._logger.info(f"=== BACKUP WRAPPER THREAD ENDING === Final stats: {final_stats}")
    
    def _execute_backup_cycle_with_recovery(self, executor: ThreadPoolExecutor):
        """Execute backup cycle with additional recovery mechanisms."""
        try:
            self._execute_backup_cycle(executor)
        except Exception as e:
            self._logger.error(f"Backup cycle failed, attempting recovery: {e}")
            
            # Attempt to recover from common failure scenarios
            recovery_success = False
            
            # Recovery attempt 1: Clear problematic status entries
            try:
                self._clear_problematic_status_entries()
                recovery_success = True
                self._logger.info("Recovery attempt 1 successful: cleared problematic status entries")
            except Exception as recovery_error:
                self._logger.error(f"Recovery attempt 1 failed: {recovery_error}")
            
            # Recovery attempt 2: Reset device discovery state
            if not recovery_success:
                try:
                    self._reset_device_discovery_state()
                    recovery_success = True
                    self._logger.info("Recovery attempt 2 successful: reset device discovery state")
                except Exception as recovery_error:
                    self._logger.error(f"Recovery attempt 2 failed: {recovery_error}")
            
            # If recovery was successful, re-raise the original exception to be caught by the main loop
            # If recovery failed, the original exception will propagate
            if not recovery_success:
                self._logger.error("All recovery attempts failed")
            
            # Always re-raise to be handled by the main loop's error handling
            raise
    
    def _calculate_adaptive_wait_time(self, consecutive_failures: int) -> int:
        """Calculate adaptive wait time based on failure rate."""
        base_wait = self._backup_interval
        
        if consecutive_failures == 0:
            return base_wait
        elif consecutive_failures <= 2:
            return base_wait + 30  # Add 30 seconds for minor issues
        elif consecutive_failures <= 4:
            return base_wait + 120  # Add 2 minutes for moderate issues
        else:
            return base_wait + 300  # Add 5 minutes for severe issues
    
    def _perform_emergency_recovery(self):
        """Perform emergency recovery procedures."""
        self._logger.info("=== STARTING EMERGENCY RECOVERY ===")
        
        # Recovery step 1: Clear all backup status
        try:
            with self._lock:
                failed_devices = len(self.backup_status)
                self.backup_status.clear()
                self._logger.info(f"Cleared {failed_devices} problematic backup status entries")
        except Exception as e:
            self._logger.error(f"Emergency recovery step 1 failed: {e}")
        
        # Recovery step 2: Reset discovery state
        try:
            self._last_device_count = 0
            self._last_discovery_source = 'recovery_reset'
            self._last_discovery_time = time.time()
            self._logger.info("Reset device discovery state")
        except Exception as e:
            self._logger.error(f"Emergency recovery step 2 failed: {e}")
        
        # Recovery step 3: Force garbage collection
        try:
            import gc
            gc.collect()
            self._logger.info("Forced garbage collection")
        except Exception as e:
            self._logger.error(f"Emergency recovery step 3 failed: {e}")
        
        self._logger.info("=== EMERGENCY RECOVERY COMPLETED ===")
    
    def _clear_problematic_status_entries(self):
        """Clear backup status entries that might be causing issues."""
        with self._lock:
            problem_devices = []
            current_time = time.time()
            
            for device_id, status in list(self.backup_status.items()):
                # Remove devices that have been processing for too long
                if (hasattr(status, 'processing') and status.processing and 
                    hasattr(status, 'started') and status.started and 
                    current_time - status.started > 3600):  # 1 hour
                    problem_devices.append(device_id)
                
                # Remove devices with error status older than 24 hours
                elif (hasattr(status, 'status') and status.status == 'error' and
                      hasattr(status, 'ended') and status.ended and 
                      current_time - status.ended > 86400):  # 24 hours
                    problem_devices.append(device_id)
            
            for device_id in problem_devices:
                del self.backup_status[device_id]
                self._logger.info(f"Removed problematic status entry for device {device_id}")
            
            self._logger.info(f"Cleared {len(problem_devices)} problematic status entries")
    
    def _reset_device_discovery_state(self):
        """Reset device discovery state to recover from discovery issues."""
        self._last_device_count = 0
        self._last_discovery_source = 'reset'
        self._last_discovery_time = time.time()
        self._logger.info("Reset device discovery state for recovery")
    
    def _preserve_emergency_state(self, error_message: str):
        """Preserve critical state information before thread termination."""
        emergency_state = {
            'timestamp': time.time(),
            'cycle_count': self._cycle_count,
            'last_cycle_start': self._last_cycle_start,
            'device_count': self._last_device_count,
            'discovery_source': self._last_discovery_source,
            'error_message': error_message,
            'backup_status_count': len(self.backup_status) if hasattr(self, 'backup_status') else 0
        }
        
        self._logger.error(f"Emergency state preservation: {emergency_state}")
        
        # Could write to a file for debugging if needed
        # with open('/tmp/backup_emergency_state.json', 'w') as f:
        #     json.dump(emergency_state, f, indent=2)
    
    def _execute_backup_cycle(self, executor: ThreadPoolExecutor):
        """Execute a single backup cycle with comprehensive fault isolation."""
        self._logger.info("=== Starting backup cycle ====")
        
        # Device discovery with robust error handling
        active_devices = None
        try:
            self._logger.info("Discovering active devices...")
            active_devices = self._discover_devices_safely()
            if not active_devices:
                self._logger.info("No devices found for backup")
                self._update_last_backup_time()
                return
            
            self._logger.info(f"Found {len(active_devices)} devices for backup")
            for device in active_devices:
                device_name = device.get('name', 'unknown')
                device_status = device.get('status', 'unknown')
                self._logger.info(f"  - {device_name} (status: {device_status})")
            
        except Exception as e:
            self._logger.error(f"CRITICAL: Device discovery failed completely: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            self._logger.error("Backup cycle aborted due to device discovery failure")
            return
        
        # Submit backup jobs with fault isolation
        futures = self._submit_backup_jobs_safely(executor, active_devices)
        
        # Wait for completion with comprehensive error isolation
        self._wait_for_backup_completion_safely(futures)
        
        self._update_last_backup_time()
        self._logger.info("=== Backup cycle completed ====")
    
    def _discover_devices_safely(self) -> List[Dict]:
        """Discover devices with multiple fallback mechanisms and error isolation."""
        max_discovery_attempts = 3
        
        for attempt in range(1, max_discovery_attempts + 1):
            try:
                self._logger.info(f"Device discovery attempt {attempt}/{max_discovery_attempts}")
                active_devices = self.find_devices()
                
                if active_devices:
                    self._logger.info(f"Successfully discovered {len(active_devices)} devices on attempt {attempt}")
                    return active_devices
                else:
                    self._logger.warning(f"No active devices found on attempt {attempt}")
                    if attempt < max_discovery_attempts:
                        time.sleep(5)  # Wait before retry
                        continue
                    return []
                    
            except Exception as e:
                self._logger.error(f"Device discovery attempt {attempt} failed: {e}")
                if attempt == max_discovery_attempts:
                    self._logger.error("All device discovery attempts failed")
                    raise
                else:
                    self._logger.info(f"Retrying device discovery in 10 seconds...")
                    time.sleep(10)
        
        return []
    
    def _submit_backup_jobs_safely(self, executor: ThreadPoolExecutor, active_devices: List[Dict]) -> List[Tuple]:
        """Submit backup jobs with comprehensive error isolation."""
        self._logger.info("Submitting backup jobs to thread pool...")
        futures = []
        successful_submissions = 0
        failed_submissions = 0
        
        for device in active_devices:
            device_id = device.get('id', 'unknown')
            device_name = device.get('name', 'unknown')
            
            try:
                self._logger.info(f"Submitting backup job for device {device_name} (ID: {device_id})")
                
                # Validate device before submission
                if not self._validate_device_for_backup(device):
                    self._logger.warning(f"Device {device_name} failed validation, skipping")
                    failed_submissions += 1
                    continue
                
                # Create fault-isolated backup job wrapper
                future = executor.submit(self._execute_backup_job_safely, device)
                futures.append((future, device_id, device_name))
                successful_submissions += 1
                
            except Exception as e:
                self._logger.error(f"CRITICAL: Failed to submit backup job for {device_name} (ID: {device_id}): {e}")
                self._logger.error("Full traceback:", exc_info=True)
                failed_submissions += 1
                
                # Mark device as failed in status
                try:
                    self._handle_backup_failure(device_id, f"Job submission failed: {str(e)}")
                except Exception as status_error:
                    self._logger.error(f"Additional error updating status for {device_id}: {status_error}")
        
        self._logger.info(f"Job submission summary: {successful_submissions} successful, {failed_submissions} failed")
        return futures
    
    def _validate_device_for_backup(self, device: Dict) -> bool:
        """Validate that device has required information for backup."""
        required_fields = ['id', 'name', 'ip']
        
        for field in required_fields:
            if not device.get(field):
                self._logger.warning(f"Device missing required field '{field}': {device}")
                return False
        
        return True
    
    def _execute_backup_job_safely(self, device: Dict) -> bool:
        """Execute backup job with comprehensive fault isolation and error recovery."""
        device_id = device.get('id', 'unknown')
        device_name = device.get('name', 'unknown')
        
        try:
            # Use the existing initiate_backup_job method which already has error handling
            return self.initiate_backup_job(device)
            
        except DBNotReadyError as e:
            # Non-critical error - device database not ready
            self._logger.warning(f"Device {device_name} database not ready, will retry later: {e}")
            self._handle_backup_failure(device_id, f"Database not ready: {str(e)}")
            return False
            
        except Exception as e:
            # Critical error - comprehensive logging and recovery
            self._logger.error(f"CRITICAL: Backup job for {device_name} (ID: {device_id}) crashed with unexpected error: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            
            try:
                self._handle_backup_failure(device_id, f"Job crashed: {str(e)}")
            except Exception as status_error:
                self._logger.error(f"Additional error updating status for {device_id}: {status_error}")
            
            # Never let individual job failures propagate up
            return False
    
    def _wait_for_backup_completion_safely(self, futures: List[Tuple]):
        """Wait for backup job completion with comprehensive fault isolation."""
        if not futures:
            self._logger.info("No backup jobs to wait for")
            return
        
        self._logger.info(f"Waiting for {len(futures)} backup jobs to complete...")
        completed_jobs = 0
        successful_jobs = 0
        failed_jobs = 0
        timed_out_jobs = 0
        
        for future, device_id, device_name in futures:
            try:
                self._logger.info(f"Waiting for backup completion: {device_name} (ID: {device_id})")
                
                # Wait for completion with timeout
                result = future.result(timeout=600)  # 10 minute timeout per job
                completed_jobs += 1
                
                if result:
                    successful_jobs += 1
                    self._logger.info(f"✓ Backup SUCCESSFUL: {device_name} (ID: {device_id})")
                else:
                    failed_jobs += 1
                    self._logger.error(f"✗ Backup FAILED: {device_name} (ID: {device_id})")
                
            except concurrent.futures.TimeoutError:
                timed_out_jobs += 1
                self._logger.error(f"⏰ Backup TIMED OUT (600s): {device_name} (ID: {device_id})")
                
                # Cancel the timed out job to free resources
                try:
                    future.cancel()
                    self._handle_backup_failure(device_id, "Backup timed out after 600 seconds")
                except Exception as cancel_error:
                    self._logger.error(f"Error canceling timed out job for {device_id}: {cancel_error}")
                
            except Exception as e:
                failed_jobs += 1
                self._logger.error(f"✗ Backup job CRASHED: {device_name} (ID: {device_id}): {e}")
                self._logger.error("Full traceback:", exc_info=True)
                
                try:
                    self._handle_backup_failure(device_id, f"Job crashed during execution: {str(e)}")
                except Exception as status_error:
                    self._logger.error(f"Error updating status for crashed job {device_id}: {status_error}")
        
        # Log comprehensive backup cycle summary
        total_jobs = len(futures)
        self._logger.info(f"=== BACKUP CYCLE SUMMARY ===")
        self._logger.info(f"Total jobs: {total_jobs}")
        self._logger.info(f"Successful: {successful_jobs}")
        self._logger.info(f"Failed: {failed_jobs}")
        self._logger.info(f"Timed out: {timed_out_jobs}")
        self._logger.info(f"Success rate: {(successful_jobs/total_jobs*100):.1f}%" if total_jobs > 0 else "N/A")
        self._logger.info(f"=== END BACKUP CYCLE SUMMARY ===")
    
    def _update_last_backup_time(self):
        """Update last backup timestamp."""
        self.last_backup = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._logger.info(f"Backup cycle completed at {self.last_backup}")
    
    @contextmanager
    def _status_lock(self):
        """Context manager for backup status access."""
        with self._lock:
            yield
    
    def get_backup_status(self) -> str:
        """
        Get current backup status as JSON string.
        
        Returns:
            str: JSON-encoded backup status
        """
        with self._lock:
            # Convert BackupStatus objects to dictionaries for JSON serialization
            serializable_status = {}
            for device_id, status in self.backup_status.items():
                if hasattr(status, '__dict__'):
                    # Convert BackupStatus dataclass to dictionary
                    serializable_status[device_id] = {
                        'name': status.name,
                        'status': status.status,
                        'started': status.started,
                        'ended': status.ended,
                        'processing': status.processing,
                        'count': status.count,
                        'synced': status.synced,
                        'progress': status.progress
                    }
                else:
                    # Already a dictionary
                    serializable_status[device_id] = status
            
            return json.dumps(serializable_status, indent=2, default=str)
    
    def update_backup_status(self, device_id: str, key: str, value):
        """
        Update specific backup status field.
        
        Args:
            device_id: Device identifier
            key: Status field to update
            value: New value for the field
        """
        with self._lock:
            if device_id not in self.backup_status:
                self.backup_status[device_id] = BackupStatus()
            
            setattr(self.backup_status[device_id], key, value)
    
    def stop(self):
        """Stop the backup wrapper gracefully."""
        self._logger.info("Stopping backup wrapper...")
        self._stop_event.set()
    
    def is_running(self) -> bool:
        """Check if the backup wrapper is running."""
        return self.is_alive() and not self._stop_event.is_set()
    
    def get_health_status(self) -> Dict:
        """Get comprehensive health status of the backup wrapper."""
        with self._lock:
            current_time = time.time()
            
            # Count devices by status
            status_counts = {'processing': 0, 'success': 0, 'error': 0, 'warning': 0, 'unknown': 0}
            recent_errors = []
            
            for device_id, status in self.backup_status.items():
                if hasattr(status, 'processing') and status.processing:
                    status_counts['processing'] += 1
                elif hasattr(status, 'progress') and status.progress:
                    progress_status = status.progress.get('status', 'unknown')
                    if progress_status in status_counts:
                        status_counts[progress_status] += 1
                    else:
                        status_counts['unknown'] += 1
                        
                    # Collect recent errors
                    if (progress_status == 'error' and hasattr(status, 'ended') and status.ended and
                        current_time - status.ended < 3600):  # Last hour
                        recent_errors.append({
                            'device_id': device_id,
                            'device_name': getattr(status, 'name', 'unknown'),
                            'error_time': status.ended,
                            'error_message': status.progress.get('message', 'Unknown error')
                        })
                else:
                    status_counts['unknown'] += 1
            
            return {
                'thread_alive': self.is_alive(),
                'thread_running': not self._stop_event.is_set(),
                'cycle_count': self._cycle_count,
                'last_cycle_start': self._last_cycle_start,
                'device_discovery': {
                    'last_count': self._last_device_count,
                    'last_source': self._last_discovery_source,
                    'last_time': self._last_discovery_time
                },
                'device_status_counts': status_counts,
                'recent_errors': recent_errors,
                'total_tracked_devices': len(self.backup_status)
            }
    
    def get_statistics(self) -> Dict:
        """
        Get backup statistics.
        
        Returns:
            dict: Backup statistics
        """
        with self._lock:
            total_devices = len(self.backup_status)
            processing_devices = sum(1 for status in self.backup_status.values() if status.processing)
            
            return {
                'total_devices': total_devices,
                'processing_devices': processing_devices,
                'last_backup': self.last_backup,
                'backup_interval': self._backup_interval,
                'is_video_backup': self._is_video_backup,
                'max_threads': self._max_threads
            }