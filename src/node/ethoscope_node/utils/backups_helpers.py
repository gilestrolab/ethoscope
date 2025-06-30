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
from ethoscope.utils.io import get_and_hash, list_local_video_files
import os
import logging
import time
import datetime
import traceback
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
    
    def __post_init__(self):
        if self.synced is None:
            self.synced = {}
        if self.progress is None:
            self.progress = {}


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
    """Optimized video backup class with better error handling and performance."""
    
    DEFAULT_PORT = 9000
    STATIC_DIR = "static"
    REQUEST_TIMEOUT = 30
    
    def __init__(self, device_info: Dict, results_dir: str, port: int = None, static_dir: str = None):
        super().__init__(device_info, results_dir)
        self._port = port or self.DEFAULT_PORT
        self._static_dir = static_dir or self.STATIC_DIR
        self._device_url = f"http://{self._ip}:{self._port}"
        self._static_url = f"{self._device_url}/{self._static_dir}"
    
    def backup(self) -> Iterator[str]:
        """
        Performs video backup with improved status reporting and error handling.
        
        Yields:
            str: JSON-encoded status messages with detailed progress updates
        """
        start_time = time.time()
        try:
            self._logger.info(f"[{self._device_id}] === VIDEO BACKUP STARTING ===")
            self._logger.info(f"[{self._device_id}] Device URL: {self._device_url}")
            yield self._yield_status("info", f"Video backup initiated for device {self._device_id}")
            
            # Get video list
            self._logger.info(f"[{self._device_id}] Retrieving video list...")
            video_list = self._get_video_list()
            if not video_list:
                self._logger.info(f"[{self._device_id}] No videos found for download")
                yield self._yield_status("warning", f"No videos to download for device {self._device_id}")
                return True
            
            self._logger.info(f"[{self._device_id}] Found {len(video_list)} videos to download")
            
            # Download videos
            success_count = 0
            total_videos = len(video_list)
            
            for count, video_path in enumerate(video_list, start=1):
                video_start_time = time.time()
                try:
                    self._logger.info(f"[{self._device_id}] Starting download {count}/{total_videos}: {video_path}")
                    yield self._yield_status(
                        "info", 
                        f"Downloading video {os.path.basename(video_path)} ({count}/{total_videos})"
                    )
                    
                    self._download_video(video_path)
                    success_count += 1
                    
                    video_elapsed = time.time() - video_start_time
                    self._logger.info(f"[{self._device_id}] Completed download {count}/{total_videos} in {video_elapsed:.1f}s: {video_path}")
                    
                except Exception as e:
                    video_elapsed = time.time() - video_start_time
                    error_msg = f"Error downloading video {video_path} after {video_elapsed:.1f}s: {e}"
                    self._logger.warning(f"[{self._device_id}] {error_msg}")
                    self._logger.warning(f"[{self._device_id}] Video download traceback:", exc_info=True)
                    yield self._yield_status("error", error_msg)
            
            elapsed_time = time.time() - start_time
            
            # Report final status
            if success_count == total_videos:
                self._logger.info(f"[{self._device_id}] === VIDEO BACKUP COMPLETED SUCCESSFULLY: {total_videos}/{total_videos} videos in {elapsed_time:.1f}s ===")
                yield self._yield_status("success", f"All {total_videos} videos downloaded successfully in {elapsed_time:.1f}s")
            else:
                self._logger.warning(f"[{self._device_id}] === VIDEO BACKUP PARTIALLY COMPLETED: {success_count}/{total_videos} videos in {elapsed_time:.1f}s ===")
                yield self._yield_status(
                    "warning", 
                    f"Downloaded {success_count}/{total_videos} videos successfully in {elapsed_time:.1f}s"
                )
            
            return success_count > 0
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            error_msg = f"Unexpected error during video backup for device {self._device_id} after {elapsed_time:.1f}s: {e}"
            self._logger.error(f"[{self._device_id}] {error_msg}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            yield self._yield_status("error", error_msg)
            return False
    
    def _get_video_list(self) -> List[str]:
        """Get list of videos to download, trying JSON first, then HTML."""
        try:
            # Try JSON method first (newer, more reliable)
            video_dict = self._get_video_list_json()
            if video_dict:
                return list(video_dict.keys())
        except Exception as e:
            self._logger.debug(f"JSON video list failed: {e}")
        
        try:
            # Fallback to HTML method
            return self._get_video_list_html()
        except Exception as e:
            self._logger.warning(f"HTML video list failed: {e}")
            return []
    
    def _download_video(self, video_path: str):
        """Download a single video file."""
        try:
            self._logger.info(f"[{self._device_id}] Starting download of video: {video_path}")
            self._logger.info(f"[{self._device_id}] Target URL: {self._static_url}, Output dir: {self._results_dir}")
            
            get_and_hash(video_path, target_prefix=self._static_url, output_dir=self._results_dir)
            
            self._logger.info(f"[{self._device_id}] Successfully downloaded video: {video_path}")
        except Exception as e:
            self._logger.error(f"[{self._device_id}] Failed to download video {video_path}: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            raise BackupError(f"Failed to download video {video_path}: {e}")
    
    def get_video_list_json(self) -> Optional[Dict[str, Dict[str, str]]]:
        """
        Get video list in JSON format with metadata.
        
        Returns:
            dict: Video files with their metadata (path, hash)
        """
        video_list_url = f"{self._device_url}/list_video_files"
        
        try:
            self._logger.info(f"[{self._device_id}] Requesting video list from: {video_list_url}")
            self._logger.info(f"[{self._device_id}] Request timeout: {self.REQUEST_TIMEOUT}s")
            
            with urllib.request.urlopen(video_list_url, timeout=self.REQUEST_TIMEOUT) as response:
                self._logger.info(f"[{self._device_id}] Received response from video list API")
                video_data = json.load(response)
                self._logger.info(f"[{self._device_id}] Parsed JSON response with {len(video_data) if video_data else 0} videos")
                return video_data
                
        except urllib.error.HTTPError as e:
            self._logger.warning(f"[{self._device_id}] HTTP error getting JSON video list from {video_list_url}: {e}")
            return None
            
        except json.JSONDecodeError as e:
            self._logger.warning(f"[{self._device_id}] JSON decode error from {video_list_url}: {e}")
            return None
            
        except Exception as e:
            self._logger.error(f"[{self._device_id}] Unexpected error getting JSON video list from {video_list_url}: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            return None
    
    # Make this an alias for external compatibility
    _get_video_list_json = get_video_list_json
    
    def check_sync_status(self) -> Optional[Dict[str, Dict[str, int]]]:
        """
        Compare sync status between remote and local video files.
        
        Returns:
            dict: Sync status with matching and total file counts
        """
        try:
            remote_videos = self.get_video_list_json()
            if not remote_videos:
                return None
            
            local_videos = list_local_video_files(self._results_dir)
            
            matching_files = 0
            total_files = len(remote_videos)
            
            for filename, remote_info in remote_videos.items():
                remote_hash = remote_info.get('hash', '')
                
                if filename in local_videos:
                    local_hash = local_videos[filename].get('hash', '')
                    if remote_hash == local_hash:
                        matching_files += 1
                    else:
                        self._logger.debug(f"Hash mismatch for {filename}")
                else:
                    self._logger.debug(f"File missing locally: {filename}")
            
            return {
                'video_files': {
                    'matching': matching_files,
                    'total': total_files
                }
            }
            
        except Exception as e:
            self._logger.error(f"Error checking sync status: {e}")
            return None
    
    def get_video_list_html(self, index_file: str = "ethoscope_data/results/index.html", 
                           generate_first: bool = True) -> Optional[List[str]]:
        """
        Get video list from HTML index file (fallback method).
        
        Args:
            index_file: Path to index file
            generate_first: Whether to generate index first
            
        Returns:
            list: Video file names or None if failed
        """
        try:
            if generate_first:
                self._logger.info(f"[{self._device_id}] Generating remote index HTML first...")
                if not self._generate_remote_index_html():
                    self._logger.warning(f"[{self._device_id}] Failed to generate remote index, continuing anyway...")
            
            video_list_url = f"{self._static_url}/{index_file}"
            self._logger.info(f"[{self._device_id}] Requesting HTML video list from: {video_list_url}")
            
            with urllib.request.urlopen(video_list_url, timeout=self.REQUEST_TIMEOUT) as response:
                video_lines = [line.decode('utf-8').strip() for line in response]
                self._logger.info(f"[{self._device_id}] Retrieved {len(video_lines)} video entries from HTML")
                return video_lines
                
        except urllib.error.HTTPError as e:
            self._logger.warning(f"[{self._device_id}] Could not get HTML video list from {video_list_url}: {e}")
            return None
        except Exception as e:
            self._logger.error(f"[{self._device_id}] Unexpected error getting HTML video list from {video_list_url}: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            return None
    
    # Make this an alias for external compatibility  
    _get_video_list_html = get_video_list_html
    
    def _generate_remote_index_html(self) -> bool:
        """Ask the remote ethoscope to generate an index file."""
        try:
            index_url = f"{self._device_url}/make_index"
            self._logger.info(f"[{self._device_id}] Requesting index generation from: {index_url}")
            
            with urllib.request.urlopen(index_url, timeout=self.REQUEST_TIMEOUT) as response:
                self._logger.info(f"[{self._device_id}] Index generation request successful")
                return True
        except Exception as e:
            self._logger.warning(f"[{self._device_id}] Could not generate remote index from {index_url}: {e}")
            return False
    
    def remove_remote_video(self, target: str) -> bool:
        """
        Remove remote video file (currently disabled for safety).
        
        Args:
            target: Path to video file to remove
            
        Returns:
            bool: Always False (feature disabled)
        """
        # Disabled for safety - uncomment and modify if needed
        return False
        
        # Commented out implementation:
        # try:
        #     request_url = f"{self._device_url}/rm_static_file/{self._device_id}"
        #     data = json.dumps({"file": target})
        #     req = urllib.request.Request(
        #         url=request_url, 
        #         data=data.encode('utf-8'),
        #         headers={'Content-Type': 'application/json'}
        #     )
        #     with urllib.request.urlopen(req, timeout=5):
        #         return True
        # except Exception as e:
        #     self._logger.error(f"Error removing remote video {target}: {e}")
        #     return False


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
                    self.backup_status[device_id].progress = json.loads(message)
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
        Main backup loop with improved error handling and resource management.
        """
        # Log thread startup with multiple loggers to ensure visibility
        logging.info("=== BACKUP WRAPPER THREAD STARTING ===")
        self._logger.info(f"=== BACKUP WRAPPER THREAD STARTING ===")
        self._logger.info(f"Configuration: max_threads={self._max_threads}, interval={self._backup_interval}s, video_backup={self._is_video_backup}")
        logging.info(f"Configuration: max_threads={self._max_threads}, interval={self._backup_interval}s, video_backup={self._is_video_backup}")
        
        try:
            with ThreadPoolExecutor(max_workers=self._max_threads, 
                                  thread_name_prefix="BackupWorker") as executor:
                
                while not self._stop_event.is_set():
                    self._cycle_count += 1
                    self._last_cycle_start = time.time()
                    logging.info(f"=== Starting backup cycle #{self._cycle_count} ===")
                    self._logger.info(f"=== Starting backup cycle #{self._cycle_count} ===")
                    
                    try:
                        self._execute_backup_cycle(executor)
                        logging.info(f"=== Backup cycle #{self._cycle_count} completed successfully ===")
                        self._logger.info(f"=== Backup cycle #{self._cycle_count} completed successfully ===")
                    except Exception as e:
                        logging.error(f"=== ERROR in backup cycle #{self._cycle_count}: {e} ===")
                        self._logger.error(f"=== ERROR in backup cycle #{self._cycle_count}: {e} ===")
                        self._logger.error("Full traceback:", exc_info=True)
                    
                    if not self._stop_event.is_set():
                        self._logger.info(f"Waiting {self._backup_interval} seconds until next cycle...")
                        # Wait for next cycle or stop event
                        self._stop_event.wait(self._backup_interval)
                    
        except Exception as e:
            self._logger.error(f"=== BACKUP WRAPPER THREAD CRASHED: {e} ===")
            self._logger.error("Full traceback:", exc_info=True)
        finally:
            self._logger.info("=== BACKUP WRAPPER THREAD ENDING ===")
    
    def _execute_backup_cycle(self, executor: ThreadPoolExecutor):
        """Execute a single backup cycle."""
        self._logger.info("=== Starting backup cycle ====")
        
        try:
            self._logger.info("Discovering active devices...")
            active_devices = self.find_devices()
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
            self._logger.error(f"Could not get device list: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            return
        
        # Submit backup jobs
        self._logger.info("Submitting backup jobs to thread pool...")
        futures = []
        for device in active_devices:
            try:
                device_id = device.get('id', 'unknown')
                device_name = device.get('name', 'unknown')
                self._logger.info(f"Submitting backup job for device {device_name} (ID: {device_id})")
                
                future = executor.submit(self.initiate_backup_job, device)
                futures.append((future, device_id, device_name))
                
            except Exception as e:
                self._logger.error(f"Failed to submit backup job for {device}: {e}")
                self._logger.error("Full traceback:", exc_info=True)
        
        self._logger.info(f"Submitted {len(futures)} backup jobs to thread pool")
        
        # Wait for completion with timeout handling
        self._logger.info("Waiting for backup jobs to complete...")
        for future, device_id, device_name in futures:
            try:
                self._logger.info(f"Waiting for backup completion: {device_name} (ID: {device_id})")
                # Wait for completion with a timeout
                future.result(timeout=600)  # 10 minute timeout per job
                self._logger.info(f"Backup completed successfully: {device_name} (ID: {device_id})")
                
            except concurrent.futures.TimeoutError:
                self._logger.error(f"Backup job timed out (600s) for device {device_name} (ID: {device_id})")
            except Exception as e:
                self._logger.error(f"Backup job failed for device {device_name} (ID: {device_id}): {e}")
                self._logger.error("Full traceback:", exc_info=True)
        
        self._logger.info("All backup jobs completed or timed out")
        self._update_last_backup_time()
        self._logger.info("=== Backup cycle completed ====")
    
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
        return not self._stop_event.is_set()
    
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