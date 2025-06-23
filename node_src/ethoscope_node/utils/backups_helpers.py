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
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Union, Iterator, Tuple
import hashlib


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
    
    def __init__(self, device_info: Dict, results_dir: str):
        super().__init__(device_info, results_dir)
        self._database_ip = os.path.basename(self._ip)
    
    def backup(self) -> Iterator[str]:
        """
        Performs database backup with improved error handling and status reporting.
        
        Yields:
            str: JSON-encoded status messages with progress updates
        """
        try:
            yield self._yield_status("info", f"Backup initiated for device {self._device_id}")
            
            # Validate backup path
            backup_path = self._get_backup_path()
            db_name = f"{self._device_name}_db"
            
            yield self._yield_status(
                "info", 
                f"Preparing to back up database '{db_name}' to {backup_path}"
            )
            
            # Perform backup
            success = self._perform_database_backup(backup_path, db_name)
            
            if success:
                yield self._yield_status("success", f"Backup completed successfully for device {self._device_id}")
                return True
            else:
                yield self._yield_status("error", f"Backup failed for device {self._device_id}")
                return False
                
        except DBNotReadyError as e:
            warning_msg = f"Database not ready for device {self._device_id}, will retry later"
            self._logger.warning(f"{warning_msg}: {e}")
            yield self._yield_status("warning", warning_msg)
            return False
            
        except BackupError as e:
            yield self._yield_status("error", str(e))
            return False
            
        except Exception as e:
            error_msg = f"Unexpected error during backup for device {self._device_id}: {str(e)}"
            self._logger.error(traceback.format_exc())
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
    
    def _perform_database_backup(self, backup_path: str, db_name: str) -> bool:
        """Perform the actual database backup operation."""
        try:
            # Initialize MySQL to SQLite mirror
            mirror = MySQLdbToSQLite(
                backup_path,
                db_name,
                remote_host=self._database_ip,
                remote_user=self.DB_CREDENTIALS["user"],
                remote_pass=self.DB_CREDENTIALS["password"]
            )
            
            # Update ROI tables
            mirror.update_roi_tables()
            
            # Verify backup integrity
            comparison_status = mirror.compare_databases()
            self._logger.info(f"Database comparison: {comparison_status:.2f}% match")
            
            return comparison_status > 0  # Consider any positive match as success
            
        except Exception as e:
            self._logger.error(f"Database backup failed: {e}")
            raise BackupError(f"Database backup failed: {e}")
    
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
        try:
            yield self._yield_status("info", f"Video backup initiated for device {self._device_id}")
            
            # Get video list
            video_list = self._get_video_list()
            if not video_list:
                yield self._yield_status("warning", f"No videos to download for device {self._device_id}")
                return True
            
            # Download videos
            success_count = 0
            total_videos = len(video_list)
            
            for count, video_path in enumerate(video_list, start=1):
                try:
                    yield self._yield_status(
                        "info", 
                        f"Downloading video {os.path.basename(video_path)} ({count}/{total_videos})"
                    )
                    
                    self._download_video(video_path)
                    success_count += 1
                    
                except Exception as e:
                    error_msg = f"Error downloading video {video_path}: {e}"
                    self._logger.warning(error_msg)
                    yield self._yield_status("error", error_msg)
            
            # Report final status
            if success_count == total_videos:
                yield self._yield_status("success", f"All {total_videos} videos downloaded successfully")
            else:
                yield self._yield_status(
                    "warning", 
                    f"Downloaded {success_count}/{total_videos} videos successfully"
                )
            
            return success_count > 0
            
        except Exception as e:
            error_msg = f"Unexpected error during video backup for device {self._device_id}: {e}"
            self._logger.error(traceback.format_exc())
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
            get_and_hash(video_path, target_prefix=self._static_url, output_dir=self._results_dir)
        except Exception as e:
            raise BackupError(f"Failed to download video {video_path}: {e}")
    
    def get_video_list_json(self) -> Optional[Dict[str, Dict[str, str]]]:
        """
        Get video list in JSON format with metadata.
        
        Returns:
            dict: Video files with their metadata (path, hash)
        """
        video_list_url = f"{self._device_url}/list_video_files"
        
        try:
            with urllib.request.urlopen(video_list_url, timeout=self.REQUEST_TIMEOUT) as response:
                return json.load(response)
                
        except urllib.error.HTTPError as e:
            self._logger.warning(f"HTTP error getting JSON video list: {e}")
            return None
            
        except json.JSONDecodeError as e:
            self._logger.warning(f"JSON decode error: {e}")
            return None
            
        except Exception as e:
            self._logger.error(f"Unexpected error getting JSON video list: {e}")
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
        if generate_first:
            self._generate_remote_index_html()
        
        video_list_url = f"{self._static_url}/{index_file}"
        
        try:
            with urllib.request.urlopen(video_list_url, timeout=self.REQUEST_TIMEOUT) as response:
                return [line.decode('utf-8').strip() for line in response]
                
        except urllib.error.HTTPError as e:
            self._logger.warning(f"Could not get HTML video list from {video_list_url}: {e}")
            return None
    
    # Make this an alias for external compatibility  
    _get_video_list_html = get_video_list_html
    
    def _generate_remote_index_html(self) -> bool:
        """Ask the remote ethoscope to generate an index file."""
        try:
            index_url = f"{self._device_url}/make_index"
            with urllib.request.urlopen(index_url, timeout=self.REQUEST_TIMEOUT):
                return True
        except Exception as e:
            self._logger.warning(f"Could not generate remote index: {e}")
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
        
        # Configuration
        self._backup_interval = self.DEFAULT_BACKUP_INTERVAL
        
        self._logger = logging.getLogger(self.__class__.__name__)
    
    def find_devices(self, only_active: bool = True) -> List[Dict]:
        """
        Find available ethoscope devices.
        
        Args:
            only_active: Whether to return only active devices
            
        Returns:
            list: Available device information
        """
        devices = {}
        
        try:
            devices = self._get_devices_from_node()
        except Exception as e:
            self._logger.warning(f"Could not get devices from node: {e}")
            devices = self._get_devices_via_scanner()
        
        if only_active:
            return [
                device for device in devices.values() 
                if (device.get("status") not in ["not_in_use", "offline"] and 
                    device.get("name") != "ETHOSCOPE_000")
            ]
        
        return list(devices.values())
    
    def _get_devices_from_node(self) -> Dict:
        """Get devices from node server."""
        url = f"http://{self._node_address}/devices"
        
        try:
            req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=self.DEFAULT_DEVICE_SCAN_TIMEOUT) as response:
                return json.load(response)
        except Exception as e:
            self._logger.error(f"Failed to get devices from node {self._node_address}: {e}")
            raise
    
    def _get_devices_via_scanner(self) -> Dict:
        """Get devices via direct scanning as fallback."""
        self._logger.info("Using EthoscopeScanner as fallback")
        
        scanner = EthoscopeScanner()
        scanner.start()
        
        try:
            time.sleep(self.DEFAULT_DEVICE_SCAN_TIMEOUT)
            return scanner.get_all_devices_info()
        finally:
            scanner.stop() if hasattr(scanner, 'stop') else None
            del scanner
    
    def initiate_backup_job(self, device_info: Dict) -> bool:
        """
        Initiate backup job for a specific device with improved error handling.
        
        Args:
            device_info: Device information dictionary
            
        Returns:
            bool: True if backup completed successfully
        """
        device_id = device_info.get('id', 'unknown')
        
        try:
            self._logger.info(f"Initiating backup for device {device_id}")
            
            # Create appropriate backup job
            if self._is_video_backup:
                backup_job = VideoBackupClass(device_info, self._results_dir)
            else:
                backup_job = BackupClass(device_info, self._results_dir)
            
            # Initialize backup status
            self._initialize_backup_status(device_id, device_info)
            
            # Perform backup with real-time status updates
            success = self._execute_backup_job(device_id, backup_job)
            
            # Update final status
            self._finalize_backup_status(device_id, backup_job, success)
            
            return success
            
        except Exception as e:
            self._logger.error(f"Backup job failed for device {device_id}: {e}")
            self._logger.error(traceback.format_exc())
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
        self._logger.info(f"Starting backup wrapper with {self._max_threads} max threads")
        
        with ThreadPoolExecutor(max_workers=self._max_threads, 
                              thread_name_prefix="BackupWorker") as executor:
            
            while not self._stop_event.is_set():
                try:
                    self._execute_backup_cycle(executor)
                except Exception as e:
                    self._logger.error(f"Error in backup cycle: {e}")
                    self._logger.error(traceback.format_exc())
                
                # Wait for next cycle or stop event
                self._stop_event.wait(self._backup_interval)
    
    def _execute_backup_cycle(self, executor: ThreadPoolExecutor):
        """Execute a single backup cycle."""
        self._logger.info("Starting backup cycle")
        
        try:
            active_devices = self.find_devices()
            if not active_devices:
                self._logger.info("No devices found for backup")
                self._update_last_backup_time()
                return
            
            self._logger.info(f"Found {len(active_devices)} devices for backup")
            
        except Exception as e:
            self._logger.error(f"Could not get device list: {e}")
            return
        
        # Submit backup jobs
        futures = []
        for device in active_devices:
            try:
                future = executor.submit(self.initiate_backup_job, device)
                futures.append((future, device.get('id', 'unknown')))
            except Exception as e:
                self._logger.error(f"Failed to submit backup job for {device}: {e}")
        
        # Wait for completion with timeout handling
        for future, device_id in futures:
            try:
                # Wait for completion with a timeout
                future.result(timeout=600)  # 10 minute timeout per job
            except Exception as e:
                self._logger.error(f"Backup job failed for device {device_id}: {e}")
        
        self._update_last_backup_time()
    
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