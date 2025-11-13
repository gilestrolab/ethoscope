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

import concurrent.futures
import datetime
import fcntl
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from ethoscope_node.backup.mysql import DBNotReadyError, MySQLdbToSQLite
from ethoscope_node.utils.configuration import ensure_ssh_keys
from ethoscope_node.utils.video_helpers import list_local_video_files


def get_sqlite_table_counts(backup_path: str) -> Dict[str, int]:
    """
    Utility function to get row counts for all tables in a SQLite database file.

    Args:
        backup_path: Path to the SQLite database file

    Returns:
        Dictionary mapping table names to row counts
    """
    table_counts = {}
    try:
        with sqlite3.connect(backup_path) as conn:
            cursor = conn.cursor()

            # Get all table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            # Get row count for each table
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    count = cursor.fetchone()[0]
                    table_counts[table] = count
                except sqlite3.Error as e:
                    logging.warning(f"Could not get count for table {table}: {e}")
                    table_counts[table] = 0

    except sqlite3.Error as e:
        logging.warning(f"Failed to read backup database {backup_path}: {e}")

    return table_counts


def calculate_backup_percentage_from_table_counts(
    remote_counts: Dict[str, int], backup_counts: Dict[str, int]
) -> float:
    """
    Calculate backup percentage based on table row counts.

    Args:
        remote_counts: Table counts from ethoscope database
        backup_counts: Table counts from backup database

    Returns:
        Backup percentage (0-100)
    """
    if not remote_counts:
        return 0.0

    total_remote_rows = 0
    total_backup_rows = 0

    # Calculate totals for tables that contain actual data (exclude metadata tables)
    data_tables = [
        table
        for table in remote_counts.keys()
        if table not in ["METADATA", "VAR_MAP", "ROI_MAP", "START_EVENTS"]
    ]

    for table in data_tables:
        remote_count = remote_counts.get(table, 0)
        backup_count = backup_counts.get(table, 0)

        total_remote_rows += remote_count
        # Don't let backup count exceed remote count for individual tables
        total_backup_rows += min(backup_count, remote_count)

    if total_remote_rows == 0:
        # If no data tables have rows, check if backup has the basic structure
        required_tables = {"METADATA", "VAR_MAP", "ROI_MAP"}
        backup_tables = set(backup_counts.keys())
        if required_tables.issubset(backup_tables):
            return 100.0  # Structure exists, no data to backup
        else:
            return 0.0

    percentage = (total_backup_rows * 100.0) / total_remote_rows
    return min(percentage, 100.0)  # Cap at 100%


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
        lock_file = open(lock_file_path, "w")

        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise BackupLockError(f"Cannot acquire lock for {backup_path}: {e}") from e

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
            except OSError:
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
    except OSError:
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
            "completed_at": datetime.datetime.now().isoformat(),
            "backup_file": backup_path,
            "file_size": (
                os.path.getsize(backup_path) if os.path.exists(backup_path) else 0
            ),
            "stats": stats or {},
        }

        with open(completion_file, "w") as f:
            json.dump(completion_data, f, indent=2)

    except OSError as e:
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
        "password": "ethoscope",
    }

    # Database connection timeout (seconds)
    DB_CONNECTION_TIMEOUT = 30
    DB_OPERATION_TIMEOUT = 120

    def __init__(self, device_info: Dict, results_dir: str):
        super().__init__(device_info, results_dir)
        self._database_ip = os.path.basename(self._ip)

    def backup(self) -> Iterator[str]:
        """
        Performs MariaDB database backup with improved error handling and status reporting.
        Uses MySQLdbToSQLite's built-in max(id) incremental backup approach.

        Yields:
            str: JSON-encoded status messages with progress updates
        """
        start_time = time.time()

        try:
            self._logger.info(f"[{self._device_id}] === MARIADB BACKUP STARTING ===")
            yield self._yield_status(
                "info", f"MariaDB backup initiated for device {self._device_id}"
            )

            # Validate device has MariaDB database
            if not self._validate_mariadb_database():
                error_msg = f"Device {self._device_id} does not have a MariaDB database - skipping MariaDB backup"
                self._logger.warning(f"[{self._device_id}] {error_msg}")
                yield self._yield_status("warning", error_msg)
                return False

            # Validate backup path using MariaDB metadata
            self._logger.info(f"[{self._device_id}] Validating MariaDB backup path...")
            backup_path = self._get_mariadb_backup_path()
            db_name = f"{self._device_name}_db"

            self._logger.info(
                f"[{self._device_id}] Backup path validated: {backup_path}"
            )
            yield self._yield_status(
                "info", f"Preparing to back up database '{db_name}' to {backup_path}"
            )

            # Perform incremental backup using MySQLdbToSQLite's built-in max(id) logic
            self._logger.info(
                f"[{self._device_id}] Starting incremental database backup (max ID approach)..."
            )
            success, backup_stats = self._perform_database_backup(backup_path, db_name)

            elapsed_time = time.time() - start_time

            if success:
                self._logger.info(
                    f"[{self._device_id}] === DATABASE BACKUP COMPLETED SUCCESSFULLY in {elapsed_time:.1f}s ==="
                )
                yield self._yield_status(
                    "success",
                    f"Backup completed successfully for device {self._device_id} in {elapsed_time:.1f}s",
                )
                return True
            else:
                self._logger.error(
                    f"[{self._device_id}] === DATABASE BACKUP FAILED after {elapsed_time:.1f}s ==="
                )
                yield self._yield_status(
                    "error",
                    f"Backup failed for device {self._device_id} after {elapsed_time:.1f}s",
                )
                return False

        except DBNotReadyError as e:
            elapsed_time = time.time() - start_time
            warning_msg = f"Database not ready for device {self._device_id}, will retry later (after {elapsed_time:.1f}s)"
            self._logger.warning(f"[{self._device_id}] {warning_msg}: {e}")
            yield self._yield_status("warning", warning_msg)
            return False

        except BackupError as e:
            elapsed_time = time.time() - start_time
            self._logger.error(
                f"[{self._device_id}] BackupError after {elapsed_time:.1f}s: {e}"
            )
            yield self._yield_status(
                "error", f"Backup error after {elapsed_time:.1f}s: {str(e)}"
            )
            return False

        except Exception as e:
            elapsed_time = time.time() - start_time
            error_msg = f"Unexpected error during backup for device {self._device_id} after {elapsed_time:.1f}s: {str(e)}"
            self._logger.error(f"[{self._device_id}] {error_msg}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            yield self._yield_status("error", error_msg)
            return False

    def _validate_mariadb_database(self) -> bool:
        """Validate that the device has a MariaDB database available for backup."""
        try:
            # Check the new nested databases structure
            databases = self._device_info.get("databases", {})
            mariadb_databases = databases.get("MariaDB", {})

            # Check if there are any MariaDB databases
            if len(mariadb_databases) > 0:
                self._logger.info(
                    f"[{self._device_id}] MariaDB database(s) validated for backup: {list(mariadb_databases.keys())}"
                )
                return True

            self._logger.info(
                f"[{self._device_id}] No MariaDB databases found in nested structure"
            )
            return False

        except Exception as e:
            self._logger.error(
                f"[{self._device_id}] Error validating MariaDB database: {e}"
            )
            return False

    def _get_mariadb_backup_path(self) -> str:
        """Get and validate backup path using MariaDB metadata from nested databases structure."""
        try:
            # Get MariaDB databases from nested structure
            databases = self._device_info.get("databases", {})
            mariadb_databases = databases.get("MariaDB", {})

            if not mariadb_databases:
                raise BackupError(
                    f"No MariaDB databases found in nested structure for device {self._device_id}"
                )

            # For now, take the first MariaDB database (typically there's only one)
            # In the future, we might need to handle multiple MariaDB databases
            db_name = list(mariadb_databases.keys())[0]
            db_info = mariadb_databases[db_name]

            self._logger.info(f"[{self._device_id}] Using MariaDB database: {db_name}")

            # Extract backup path from database info
            if "path" in db_info:
                backup_path = db_info["path"]
                self._logger.info(
                    f"[{self._device_id}] Using MariaDB path: {backup_path}"
                )
            else:
                # Construct path from backup_filename and device info
                backup_filename = db_info.get("backup_filename", "")
                if not backup_filename:
                    raise BackupError(
                        f"No backup filename found for MariaDB database {db_name}"
                    )

                # Extract components from backup filename
                filename_parts = backup_filename.replace(".db", "").split("_")
                if len(filename_parts) >= 3:
                    backup_date = filename_parts[0]
                    backup_time = filename_parts[1]
                    etho_id = "_".join(filename_parts[2:])
                    backup_path = f"{etho_id}/{self._device_name}/{backup_date}_{backup_time}/{backup_filename}"
                else:
                    raise BackupError(
                        f"Invalid MariaDB backup filename format: {backup_filename}"
                    )

            full_backup_path = os.path.join(self._results_dir, backup_path)

            # Ensure directory exists
            os.makedirs(os.path.dirname(full_backup_path), exist_ok=True)

            return full_backup_path

        except Exception as e:
            self._logger.error(
                f"[{self._device_id}] Error getting MariaDB backup path: {e}"
            )
            raise BackupError(f"Failed to get MariaDB backup path: {e}") from e

    def _get_backup_path(self) -> str:
        """Get and validate backup path (legacy method - use _get_mariadb_backup_path instead)."""
        return self._get_mariadb_backup_path()

    def _perform_database_backup(
        self, backup_path: str, db_name: str
    ) -> Tuple[bool, dict]:
        """
        Perform the actual database backup operation using MySQLdbToSQLite's
        built-in incremental max(id) approach to prevent duplicates.
        """
        backup_stats = {}

        try:
            self._logger.info(
                f"[{self._device_id}] Initializing MySQL to SQLite mirror connection..."
            )
            self._logger.info(
                f"[{self._device_id}] Target: {backup_path}, DB: {db_name}, Host: {self._database_ip}"
            )

            # Initialize MySQL to SQLite mirror (handles incremental updates automatically)
            mirror = MySQLdbToSQLite(
                backup_path,
                db_name,
                remote_host=self._database_ip,
                remote_user=self.DB_CREDENTIALS["user"],
                remote_pass=self.DB_CREDENTIALS["password"],
            )
            self._logger.info(
                f"[{self._device_id}] MySQL mirror initialized successfully"
            )

            # Update ROI tables using built-in max(id) incremental logic
            self._logger.info(
                f"[{self._device_id}] Starting incremental ROI tables update (max ID approach)..."
            )
            mirror.update_all_tables()
            self._logger.info(
                f"[{self._device_id}] Incremental ROI tables update completed"
            )

            # Verify backup integrity
            self._logger.info(f"[{self._device_id}] Starting database comparison...")
            comparison_status = mirror.compare_databases()
            self._logger.info(
                f"[{self._device_id}] Database comparison: {comparison_status:.2f}% match"
            )

            backup_stats["comparison_percentage"] = comparison_status
            backup_stats["backup_success"] = comparison_status > 0

            # Check for data duplication
            self._logger.info(f"[{self._device_id}] Checking for data duplication...")
            duplication_found = self._check_data_duplication(backup_path)
            backup_stats["data_duplication"] = duplication_found

            if comparison_status > 0:
                self._logger.info(
                    f"[{self._device_id}] Incremental database backup successful (match: {comparison_status:.2f}%)"
                )
            else:
                self._logger.warning(
                    f"[{self._device_id}] Database backup may have issues (match: {comparison_status:.2f}%)"
                )

            return comparison_status > 0, backup_stats

        except Exception as e:
            backup_stats["error"] = str(e)
            self._logger.error(f"[{self._device_id}] Database backup failed: {e}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            raise BackupError(f"Database backup failed: {e}") from e

    def _check_data_duplication(self, backup_path: str) -> bool:
        """
        Check for data duplication in METADATA and VAR_MAP tables.

        Args:
            backup_path: Path to the SQLite backup file

        Returns:
            bool: True if duplicates found in either table, False otherwise
        """
        try:
            self._logger.info(
                f"[{self._device_id}] Checking for data duplication in backup database..."
            )

            with sqlite3.connect(backup_path) as conn:
                cursor = conn.cursor()

                # Check METADATA table for duplicates
                metadata_duplicates = False
                try:
                    cursor.execute("SELECT COUNT(*) FROM METADATA")
                    total_metadata = cursor.fetchone()[0]

                    cursor.execute(
                        "SELECT COUNT(*) FROM (SELECT DISTINCT field, value FROM METADATA)"
                    )
                    distinct_metadata = cursor.fetchone()[0]

                    metadata_duplicates = total_metadata > distinct_metadata
                    self._logger.debug(
                        f"[{self._device_id}] METADATA table: {total_metadata} total, {distinct_metadata} distinct"
                    )

                except sqlite3.OperationalError as e:
                    self._logger.warning(
                        f"[{self._device_id}] Could not check METADATA table: {e}"
                    )

                # Check VAR_MAP table for duplicates
                varmap_duplicates = False
                try:
                    cursor.execute("SELECT COUNT(*) FROM VAR_MAP")
                    total_varmap = cursor.fetchone()[0]

                    cursor.execute(
                        "SELECT COUNT(*) FROM (SELECT DISTINCT var_name, sql_type, functional_type FROM VAR_MAP)"
                    )
                    distinct_varmap = cursor.fetchone()[0]

                    varmap_duplicates = total_varmap > distinct_varmap
                    self._logger.debug(
                        f"[{self._device_id}] VAR_MAP table: {total_varmap} total, {distinct_varmap} distinct"
                    )

                except sqlite3.OperationalError as e:
                    self._logger.warning(
                        f"[{self._device_id}] Could not check VAR_MAP table: {e}"
                    )

                duplicates_found = metadata_duplicates or varmap_duplicates

                if duplicates_found:
                    self._logger.warning(
                        f"[{self._device_id}] Data duplication detected - METADATA: {metadata_duplicates}, VAR_MAP: {varmap_duplicates}"
                    )
                else:
                    self._logger.info(
                        f"[{self._device_id}] No data duplication detected"
                    )

                return duplicates_found

        except Exception as e:
            self._logger.error(
                f"[{self._device_id}] Error checking data duplication: {e}"
            )
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            return False  # Return False on error to avoid false positives

    def get_sqlite_table_counts(self, backup_path: str) -> Dict[str, int]:
        """
        Get row counts for all tables in a SQLite database file.

        Args:
            backup_path: Path to the SQLite database file

        Returns:
            Dictionary mapping table names to row counts
        """
        table_counts = {}
        try:
            with sqlite3.connect(backup_path) as conn:
                cursor = conn.cursor()

                # Get all table names
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]

                # Get row count for each table
                for table in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                        count = cursor.fetchone()[0]
                        table_counts[table] = count
                    except sqlite3.Error as e:
                        self._logger.warning(
                            f"[{self._device_id}] Could not get count for table {table}: {e}"
                        )
                        table_counts[table] = 0

        except sqlite3.Error as e:
            self._logger.warning(
                f"[{self._device_id}] Failed to read backup database {backup_path}: {e}"
            )

        return table_counts

    def check_sync_status(self) -> Dict:
        """Check synchronization status of the database backup."""
        # TODO: Implement database sync status checking
        return {"tracking_db": {}}


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
        import re
        import subprocess

        start_time = time.time()
        try:
            self._logger.info(
                f"[{self._device_id}] === RSYNC VIDEO BACKUP STARTING ==="
            )
            yield self._yield_status(
                "info", f"Rsync video backup initiated for device {self._device_id}"
            )

            # Step 1: Get video information from ethoscope
            self._logger.info(f"[{self._device_id}] Retrieving video metadata...")
            video_info = self.get_video_list_json()
            if not video_info:
                self._logger.warning(
                    f"[{self._device_id}] Failed to retrieve video information"
                )
                yield self._yield_status(
                    "error",
                    f"Failed to retrieve video information from device {self._device_id}",
                )
                return False

            metadata = video_info.get("metadata", {})
            video_files = video_info.get("video_files", {})

            if not video_files:
                self._logger.info(f"[{self._device_id}] No videos found for backup")
                yield self._yield_status(
                    "warning", f"No videos to backup for device {self._device_id}"
                )
                return True

            # Extract key information
            source_dir = metadata.get("videos_directory", "/ethoscope_data/videos")
            device_ip = metadata.get("device_ip", self._ip)
            total_files = metadata.get("total_files", len(video_files))
            disk_usage = metadata.get("disk_usage_bytes", 0)

            self._logger.info(
                f"[{self._device_id}] Found {total_files} videos ({disk_usage} bytes) in {source_dir}"
            )
            yield self._yield_status(
                "info", f"Found {total_files} videos to backup from {source_dir}"
            )

            # Store device metadata for status reporting
            device_metadata = {
                "total_files": total_files,
                "disk_usage_bytes": disk_usage,
                "videos_directory": source_dir,
                "device_ip": device_ip,
            }
            yield self._yield_status("metadata", json.dumps(device_metadata))

            # Step 2: Prepare rsync command
            destination_dir = self._results_dir
            os.makedirs(destination_dir, exist_ok=True)

            # Get SSH key path for authentication
            private_key_path, _ = ensure_ssh_keys()

            rsync_source = f"ethoscope@{device_ip}:{source_dir}/"
            rsync_command = [
                "rsync",
                "-avz",  # archive, verbose, compress
                "--progress",  # show progress
                "--partial",  # keep partial files
                "--timeout=300",  # 5 minute timeout
                "-e",
                f"ssh -i {private_key_path} -o StrictHostKeyChecking=no",  # SSH key authentication
                rsync_source,
                destination_dir,
            ]

            self._logger.info(
                f"[{self._device_id}] Starting rsync: {' '.join(rsync_command)}"
            )
            yield self._yield_status(
                "info", f"Starting rsync from {rsync_source} to {destination_dir}"
            )

            # Step 3: Execute rsync with progress monitoring
            process = subprocess.Popen(
                rsync_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            files_transferred = 0
            current_file = ""

            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue

                self._logger.debug(f"[{self._device_id}] rsync: {line}")

                # Parse progress information
                if line.endswith("bytes/sec"):
                    # Progress line format: "1,234,567  67%   123.45kB/s    0:00:12"
                    match = re.search(r"(\d{1,3}(?:,\d{3})*)\s+(\d+)%\s+(.+?/s)", line)
                    if match:
                        int(match.group(1).replace(",", ""))
                        percentage = int(match.group(2))
                        speed = match.group(3)

                        yield self._yield_status(
                            "info",
                            f"Transferring {current_file}: {percentage}% complete ({speed})",
                        )

                elif line.startswith("./") or "/" in line:
                    # File being transferred
                    if not line.startswith("rsync:") and not line.startswith(
                        "total size"
                    ):
                        current_file = os.path.basename(line)
                        files_transferred += 1
                        yield self._yield_status(
                            "info",
                            f"Transferring file {files_transferred}/{total_files}: {current_file}",
                        )

            # Wait for rsync to complete
            return_code = process.wait()
            elapsed_time = time.time() - start_time

            if return_code == 0:
                self._logger.info(
                    f"[{self._device_id}] === RSYNC VIDEO BACKUP COMPLETED SUCCESSFULLY in {elapsed_time:.1f}s ==="
                )
                yield self._yield_status(
                    "success",
                    f"Rsync backup completed successfully in {elapsed_time:.1f}s",
                )
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
            self._logger.info(
                f"[{self._device_id}] Requesting video list from: {video_list_url}"
            )

            with urllib.request.urlopen(
                video_list_url, timeout=self.REQUEST_TIMEOUT
            ) as response:
                video_data = json.load(response)

                # Validate response structure
                if not isinstance(video_data, dict):
                    self._logger.warning(
                        f"[{self._device_id}] Invalid response format from enhanced video API"
                    )
                    return None

                # Extract video files and metadata
                video_files = video_data.get("video_files", {})
                metadata = video_data.get("metadata", {})

                self._logger.info(
                    f"[{self._device_id}] Retrieved video list: {len(video_files)} videos, metadata: {list(metadata.keys())}"
                )

                return {"video_files": video_files, "metadata": metadata}

        except urllib.error.HTTPError as e:
            self._logger.warning(
                f"[{self._device_id}] HTTP error getting video list from {video_list_url}: {e}"
            )
            return None

        except json.JSONDecodeError as e:
            self._logger.warning(
                f"[{self._device_id}] JSON decode error from video list API {video_list_url}: {e}"
            )
            return None

        except Exception as e:
            self._logger.error(
                f"[{self._device_id}] Unexpected error getting video list from {video_list_url}: {e}"
            )
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

            remote_videos = video_info.get("video_files", {})
            local_videos = list_local_video_files(self._results_dir, createMD5=False)

            present_files = 0
            total_files = len(remote_videos)

            for filename in remote_videos.keys():
                if filename in local_videos:
                    present_files += 1
                else:
                    self._logger.debug(f"File missing locally: {filename}")

            return {"video_files": {"present": present_files, "total": total_files}}

        except Exception as e:
            self._logger.error(f"Error checking sync status: {e}")
            return None


class UnifiedRsyncBackupClass(BaseBackupClass):
    """Unified rsync-based backup class for both results (databases) and videos."""

    DEFAULT_PORT = 9000
    REQUEST_TIMEOUT = 30

    def __init__(
        self,
        device_info: Dict,
        results_dir: str,
        videos_dir: str = None,
        backup_results: bool = True,
        backup_videos: bool = True,
    ):
        super().__init__(device_info, results_dir)
        self._port = self.DEFAULT_PORT
        self._device_url = f"http://{self._ip}:{self._port}"

        # Directory configuration
        self._results_dir = results_dir
        self._videos_dir = videos_dir or results_dir.replace("/results/", "/videos/")

        # Backup selection
        self._backup_results = backup_results
        self._backup_videos = backup_videos

        # Ensure at least one backup type is selected
        if not (self._backup_results or self._backup_videos):
            raise ValueError(
                "At least one of backup_results or backup_videos must be True"
            )

    def backup(self) -> Iterator[str]:
        """
        Performs unified rsync backup for SQLite results and videos.

        Yields:
            str: JSON-encoded status messages with detailed progress updates
        """

        start_time = time.time()
        try:
            self._logger.info(
                f"[{self._device_id}] === UNIFIED RSYNC BACKUP STARTING ==="
            )

            # Validate device has SQLite database if backing up results
            if self._backup_results and not self._validate_sqlite_database():
                error_msg = f"Device {self._device_id} does not have a SQLite database - skipping SQLite results backup"
                self._logger.warning(f"[{self._device_id}] {error_msg}")
                yield self._yield_status("warning", error_msg)
                # Still allow video backup to proceed
                self._backup_results = False

            backup_types = []
            if self._backup_results:
                backup_types.append("results")
            if self._backup_videos:
                backup_types.append("videos")

            if not backup_types:
                error_msg = f"No valid backup types for device {self._device_id}"
                self._logger.warning(f"[{self._device_id}] {error_msg}")
                yield self._yield_status("warning", error_msg)
                return False

            yield self._yield_status(
                "info",
                f"SQLite rsync backup initiated for {', '.join(backup_types)} on device {self._device_id}",
            )

            # Get SSH key path for authentication
            private_key_path, _ = ensure_ssh_keys()

            total_operations = len(backup_types)
            completed_operations = 0

            # Backup results (databases) if requested
            if self._backup_results:
                yield self._yield_status(
                    "info",
                    f"Starting results backup ({completed_operations + 1}/{total_operations})",
                )
                success = yield from self._rsync_directory(
                    source_dir="/ethoscope_data/results/",
                    destination_dir=self._results_dir,
                    private_key_path=private_key_path,
                    operation_name="results",
                )
                if not success:
                    yield self._yield_status("error", "Results backup failed")
                    return False
                completed_operations += 1

            # Backup videos if requested
            if self._backup_videos:
                yield self._yield_status(
                    "info",
                    f"Starting videos backup ({completed_operations + 1}/{total_operations})",
                )
                success = yield from self._rsync_directory(
                    source_dir="/ethoscope_data/videos/",
                    destination_dir=self._videos_dir,
                    private_key_path=private_key_path,
                    operation_name="videos",
                )
                if not success:
                    yield self._yield_status("error", "Videos backup failed")
                    return False
                completed_operations += 1

            elapsed_time = time.time() - start_time
            self._logger.info(
                f"[{self._device_id}] === UNIFIED RSYNC BACKUP COMPLETED SUCCESSFULLY in {elapsed_time:.1f}s ==="
            )
            yield self._yield_status(
                "success",
                f"Unified backup completed successfully in {elapsed_time:.1f}s",
            )
            return True

        except Exception as e:
            elapsed_time = time.time() - start_time
            error_msg = f"Unexpected error during unified backup for device {self._device_id} after {elapsed_time:.1f}s: {e}"
            self._logger.error(f"[{self._device_id}] {error_msg}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            yield self._yield_status("error", error_msg)
            return False

    def _rsync_directory(
        self,
        source_dir: str,
        destination_dir: str,
        private_key_path: str,
        operation_name: str,
    ) -> Iterator[bool]:
        """
        Perform rsync for a specific directory.

        Args:
            source_dir: Source directory on ethoscope (e.g., "/ethoscope_data/results/")
            destination_dir: Destination directory on node
            private_key_path: Path to SSH private key
            operation_name: Name for logging ("results" or "videos")

        Yields:
            str: Progress status messages

        Returns:
            bool: True if successful, False otherwise
        """
        import re
        import subprocess

        try:
            # Ensure destination directory exists
            os.makedirs(destination_dir, exist_ok=True)

            # Construct rsync command with enhanced verbosity for file size capture
            rsync_source = f"ethoscope@{self._ip}:{source_dir}"
            rsync_command = [
                "rsync",
                "-avz",  # archive, verbose, compress
                "--progress",  # show progress
                "--partial",  # keep partial files
                "--stats",  # show detailed transfer statistics
                "--itemize-changes",  # show per-file change details
                "--exclude=*.db-shm",  # exclude SQLite shared memory files (temporary)
                "--exclude=*.db-wal",  # exclude SQLite write-ahead log files (temporary)
                "--exclude=*.db-journal",  # exclude SQLite rollback journal files (temporary)
                "--timeout=300",  # 5 minute timeout
                "-e",
                f"ssh -i {private_key_path} -o StrictHostKeyChecking=no",  # SSH key authentication
                rsync_source,
                destination_dir,
            ]

            self._logger.info(
                f"[{self._device_id}] Starting {operation_name} rsync: {' '.join(rsync_command)}"
            )
            yield self._yield_status(
                "info",
                f"Starting {operation_name} rsync from {rsync_source} to {destination_dir}",
            )

            # Execute rsync with progress monitoring
            process = subprocess.Popen(
                rsync_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            files_transferred = 0
            current_file = ""
            file_details = {}  # Store detailed file information
            total_bytes_transferred = 0

            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if not line:
                    continue

                self._logger.debug(
                    f"[{self._device_id}] {operation_name} rsync: {line}"
                )

                # Parse itemize-changes output format: >f+++++++++ path/to/file
                if re.match(r"^[<>ch.*]f[.+cstpoguax]{9}\s+", line):
                    # This is a file (not directory) itemize-changes line
                    parts = line.split(None, 1)  # Split on first whitespace only
                    if len(parts) >= 2:
                        file_path = parts[1]  # Full path after the flags
                        filename = os.path.basename(file_path)

                        # Skip empty filenames
                        if filename:
                            # Initialize file details if not exists
                            if filename not in file_details:
                                file_details[filename] = {
                                    "path": file_path,
                                    "relative_path": file_path,  # Store relative path for size lookup
                                    "size_bytes": 0,
                                    "transfer_start": time.time(),
                                    "status": "transferring",
                                }
                                files_transferred += 1
                                current_file = filename
                                yield self._yield_status(
                                    "info",
                                    f"{operation_name.title()}: Processing {filename} (file #{files_transferred})",
                                )

                # Parse progress information: "12,664,832 100% 11.06MB/s 0:00:01 (xfr#12, to-chk=3/27)"
                elif re.search(r"\d+\s+100%.*\(xfr#\d+", line):
                    # This is a final transfer line showing completed file size
                    match = re.search(
                        r"(\d{1,3}(?:,\d{3})*)\s+100%\s+(.+?/s).*\(xfr#(\d+)", line
                    )
                    if match:
                        final_bytes = int(match.group(1).replace(",", ""))
                        speed = match.group(2)
                        int(match.group(3))

                        # Update the most recently processed file with final size
                        if current_file and current_file in file_details:
                            file_details[current_file]["size_bytes"] = final_bytes
                            file_details[current_file]["size_human"] = (
                                self._format_bytes(final_bytes)
                            )
                            file_details[current_file]["transfer_speed"] = speed

                            self._logger.info(
                                f"[{self._device_id}] File {current_file}: {final_bytes} bytes ({speed})"
                            )

                        total_bytes_transferred += final_bytes

                        yield self._yield_status(
                            "info",
                            f"{operation_name.title()}: {current_file} completed - {self._format_bytes(final_bytes)} ({speed})",
                        )

                # Parse rsync statistics for final file sizes
                elif line.startswith("Total file size:"):
                    # Extract total size: "Total file size: 123,456,789 bytes"
                    match = re.search(r"Total file size:\s*(\d{1,3}(?:,\d{3})*)", line)
                    if match:
                        total_size = int(match.group(1).replace(",", ""))
                        self._logger.info(
                            f"[{self._device_id}] {operation_name} total size: {total_size} bytes"
                        )

                # Skip progress lines and rsync status messages
                elif (
                    (line.endswith("%") and ("kB/s" in line or "MB/s" in line))
                    or line.startswith("rsync:")
                    or line.startswith("total size")
                    or "xfr#" in line
                    or "to-chk=" in line
                ):
                    # These are progress/status lines, not file names
                    continue

            # Wait for rsync to complete
            return_code = process.wait()

            # Mark all files as completed and get final sizes from filesystem
            for filename, details in file_details.items():
                details["status"] = "completed"
                details["transfer_end"] = time.time()

                # Get actual file size from destination using relative path
                relative_path = details.get("relative_path", details["path"])
                dest_file_path = os.path.join(
                    destination_dir, relative_path.lstrip("./")
                )

                # Try multiple path combinations to find the file
                possible_paths = [
                    dest_file_path,
                    os.path.join(destination_dir, filename),
                    os.path.join(destination_dir, details["path"]),
                ]

                for path_attempt in possible_paths:
                    if os.path.exists(path_attempt):
                        try:
                            actual_size = os.path.getsize(path_attempt)
                            details["size_bytes"] = actual_size
                            details["size_human"] = self._format_bytes(actual_size)
                            self._logger.debug(
                                f"[{self._device_id}] Found file {filename}: {actual_size} bytes at {path_attempt}"
                            )
                            break
                        except OSError:
                            continue
                else:
                    # File not found, log for debugging
                    self._logger.warning(
                        f"[{self._device_id}] Could not find transferred file {filename} in any of: {possible_paths}"
                    )

            # Store file details for status endpoint retrieval
            if not hasattr(self, "_transfer_details"):
                self._transfer_details = {}
            self._transfer_details[operation_name] = {
                "files": file_details,
                "total_files": files_transferred,
                "total_bytes": total_bytes_transferred,
                "completion_time": time.time(),
            }

            if return_code == 0:
                self._logger.info(
                    f"[{self._device_id}] {operation_name.title()} rsync completed successfully - {files_transferred} files"
                )
                yield self._yield_status(
                    "info",
                    f"{operation_name.title()} rsync completed successfully - {files_transferred} files",
                )
                return True
            else:
                error_msg = f"{operation_name.title()} rsync failed with return code {return_code}"
                self._logger.error(f"[{self._device_id}] {error_msg}")
                yield self._yield_status("error", error_msg)
                return False

        except Exception as e:
            error_msg = f"Error during {operation_name} rsync: {e}"
            self._logger.error(f"[{self._device_id}] {error_msg}")
            self._logger.error(f"[{self._device_id}] Full traceback:", exc_info=True)
            yield self._yield_status("error", error_msg)
            return False

    def check_sync_status(self) -> Optional[Dict]:
        """
        Check sync status for both results and videos directories.

        Returns:
            dict: Sync status for both backup types including detailed file information
        """
        try:
            status = {}

            if self._backup_results:
                status["results"] = self._check_directory_sync_status(
                    self._results_dir, "results"
                )

            if self._backup_videos:
                status["videos"] = self._check_directory_sync_status(
                    self._videos_dir, "videos"
                )

            # Add detailed transfer information if available
            if hasattr(self, "_transfer_details"):
                status["transfer_details"] = self._transfer_details

            return status

        except Exception as e:
            self._logger.error(f"Error checking unified sync status: {e}")
            return None

    def _check_directory_sync_status(self, local_dir: str, dir_type: str) -> Dict:
        """
        Check sync status for a specific directory type.

        Args:
            local_dir: Local directory path
            dir_type: Type of directory ("results" or "videos")

        Returns:
            dict: Sync status with file counts and disk usage
        """
        try:
            # Count local files and calculate disk usage
            local_file_count = 0
            total_size_bytes = 0

            if os.path.exists(local_dir):
                for root, _dirs, files in os.walk(local_dir):
                    local_file_count += len(files)
                    for file in files:
                        try:
                            file_path = os.path.join(root, file)
                            total_size_bytes += os.path.getsize(file_path)
                        except OSError:
                            # Skip files that can't be accessed
                            pass

            # Convert bytes to human-readable format
            disk_usage = self._format_bytes(total_size_bytes)

            return {
                "local_files": local_file_count,
                "directory": local_dir,
                "type": dir_type,
                "disk_usage_bytes": total_size_bytes,
                "disk_usage_human": disk_usage,
            }

        except Exception as e:
            self._logger.error(f"Error checking {dir_type} sync status: {e}")
            return {
                "local_files": 0,
                "directory": local_dir,
                "type": dir_type,
                "disk_usage_bytes": 0,
                "disk_usage_human": "0 B",
                "error": str(e),
            }

    def _format_bytes(self, bytes_value: int) -> str:
        """
        Format bytes into human-readable string.

        Args:
            bytes_value: Size in bytes

        Returns:
            str: Human-readable size (e.g., "1.5 GB", "234.7 MB")
        """
        if bytes_value == 0:
            return "0 B"

        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        size = float(bytes_value)

        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1

        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.1f} {units[unit_index]}"

    def _validate_sqlite_database(self) -> bool:
        """Validate that the device has a SQLite database available for backup."""
        try:
            # Check the new nested databases structure
            databases = self._device_info.get("databases", {})
            sqlite_databases = databases.get("SQLite", {})

            # Check if there are any SQLite databases
            if len(sqlite_databases) > 0:
                self._logger.info(
                    f"[{self._device_id}] SQLite database(s) validated for backup: {list(sqlite_databases.keys())}"
                )
                return True

            self._logger.info(
                f"[{self._device_id}] No SQLite databases found in nested structure"
            )
            return False

        except Exception as e:
            self._logger.error(
                f"[{self._device_id}] Error validating SQLite database: {e}"
            )
            return False


class GenericBackupWrapper(threading.Thread):
    """
    Optimized backup wrapper with better resource management and error handling.
    """

    DEFAULT_BACKUP_INTERVAL = 5 * 60  # 5 minutes
    DEFAULT_MAX_THREADS = 4
    DEFAULT_DEVICE_SCAN_TIMEOUT = 10

    def __init__(
        self,
        results_dir: str,
        node_address: str,
        video: bool = False,
        max_threads: int = None,
    ):
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

        # Backup instances for detailed status retrieval
        self._backup_instances: Dict[str, UnifiedRsyncBackupClass] = {}

        # Device discovery tracking
        self._last_device_count = 0
        self._last_discovery_source = "unknown"
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
            self._logger.info(
                f"Attempting to get devices from node at {self._node_address}"
            )
            devices = self._get_devices_from_node()
            self._logger.info(
                f"Successfully retrieved {len(devices)} devices from node"
            )
            self._last_discovery_source = "node"
        except Exception as e:
            self._logger.warning(f"Could not get devices from node: {e}")
            self._logger.info("Falling back to direct device scanning...")
            try:
                devices = self._get_devices_via_scanner()
                self._logger.info(f"Scanner found {len(devices)} devices")
                self._last_discovery_source = "scanner"
            except Exception as scanner_error:
                self._logger.error(f"Scanner also failed: {scanner_error}")
                self._last_discovery_source = "failed"
                # Still update discovery tracking even on failure
                import time

                self._last_device_count = 0
                self._last_discovery_time = time.time()
                return []

        # Update discovery tracking
        import time

        self._last_device_count = len(devices)
        self._last_discovery_time = time.time()

        self._logger.debug(
            f"Updated device discovery tracking: count={self._last_device_count}, source={self._last_discovery_source}, time={self._last_discovery_time}"
        )

        if only_active:
            active_devices = [
                device
                for device in devices.values()
                if (
                    device.get("status") not in ["not_in_use", "offline"]
                    and device.get("name") != "ETHOSCOPE_000"
                )
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

            req = urllib.request.Request(
                url, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(
                req, timeout=self.DEFAULT_DEVICE_SCAN_TIMEOUT
            ) as response:
                self._logger.info(
                    f"Received response from node server (status: {response.status})"
                )
                devices = json.load(response)
                self._logger.info(
                    f"Successfully parsed JSON response with {len(devices)} devices"
                )
                return devices
        except urllib.error.HTTPError as e:
            self._logger.error(
                f"HTTP error from node {self._node_address}: {e.code} {e.reason}"
            )
            raise
        except urllib.error.URLError as e:
            self._logger.error(
                f"URL error connecting to node {self._node_address}: {e.reason}"
            )
            raise
        except json.JSONDecodeError as e:
            self._logger.error(f"JSON decode error from node {self._node_address}: {e}")
            raise
        except Exception as e:
            self._logger.error(
                f"Unexpected error getting devices from node {self._node_address}: {e}"
            )
            self._logger.error("Full traceback:", exc_info=True)
            raise

    def _get_devices_via_scanner(self) -> Dict:
        """Get devices via direct scanning as fallback."""
        self._logger.info("Using EthoscopeScanner as fallback")

        try:
            # Import here to avoid circular dependency
            from ethoscope_node.scanner.ethoscope_scanner import EthoscopeScanner

            self._logger.info("Creating EthoscopeScanner instance...")
            scanner = EthoscopeScanner()

            self._logger.info("Starting EthoscopeScanner...")
            scanner.start()

            self._logger.info(
                f"Waiting {self.DEFAULT_DEVICE_SCAN_TIMEOUT} seconds for device discovery..."
            )
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
                if hasattr(scanner, "stop"):
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
        device_id = device_info.get("id", "unknown")
        device_name = device_info.get("name", "unknown")
        device_ip = device_info.get("ip", "unknown")
        device_status = device_info.get("status", "unknown")

        job_start_time = time.time()

        try:
            self._logger.info(
                f"=== INITIATING BACKUP JOB for {device_name} (ID: {device_id}) ==="
            )
            self._logger.info(
                f"Device details: IP={device_ip}, Status={device_status}, Video={self._is_video_backup}"
            )

            # Incremental backups are safe - no need to throttle retry attempts

            # Create appropriate backup job
            if self._is_video_backup:
                self._logger.info(f"Creating VideoBackupClass for device {device_id}")
                backup_job = VideoBackupClass(device_info, self._results_dir)
            else:
                self._logger.info(
                    f"Creating BackupClass (database) for device {device_id}"
                )
                backup_job = BackupClass(device_info, self._results_dir)

            self._logger.info(
                f"Backup job object created successfully for device {device_id}"
            )

            # Initialize backup status
            self._logger.info(f"Initializing backup status for device {device_id}")
            self._initialize_backup_status(device_id, device_info)

            # Perform backup with real-time status updates
            self._logger.info(f"Starting backup execution for device {device_id}")
            success = self._execute_backup_job(device_id, backup_job)

            job_elapsed_time = time.time() - job_start_time

            # Update final status
            self._logger.info(
                f"Finalizing backup status for device {device_id} (success={success}, elapsed={job_elapsed_time:.1f}s)"
            )
            self._finalize_backup_status(device_id, backup_job, success)

            if success:
                self._logger.info(
                    f"=== BACKUP JOB COMPLETED SUCCESSFULLY for {device_name} in {job_elapsed_time:.1f}s ==="
                )
            else:
                self._logger.error(
                    f"=== BACKUP JOB FAILED for {device_name} after {job_elapsed_time:.1f}s ==="
                )

            return success

        except Exception as e:
            job_elapsed_time = time.time() - job_start_time
            self._logger.error(
                f"=== BACKUP JOB CRASHED for {device_name} after {job_elapsed_time:.1f}s ==="
            )
            self._logger.error(f"Backup job failed for device {device_id}: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            self._handle_backup_failure(device_id, str(e))
            return False

    def _initialize_backup_status(self, device_id: str, device_info: Dict):
        """Initialize backup status for a device using new comprehensive device data."""
        with self._lock:
            if device_id not in self.backup_status:
                self.backup_status[device_id] = BackupStatus(
                    name=device_info.get("name", ""),
                    status=device_info.get("status", ""),
                    count=0,
                )

            status = self.backup_status[device_id]
            status.started = int(time.time())
            status.ended = 0
            status.processing = True
            status.count += 1

            # Extract progress information from new device data format
            status.progress = {
                "backup_status": device_info.get("backup_status", 0.0),
                "backup_size": device_info.get("backup_size", 0),
                "time_since_backup": device_info.get("time_since_backup", 0.0),
                "backup_type": device_info.get("backup_type", "unknown"),
                "backup_method": device_info.get("backup_method", "unknown"),
                "status": "initializing",
                "message": f'Starting backup for {device_info.get("name", "unknown")}',
            }

    def _execute_backup_job(self, device_id: str, backup_job) -> bool:
        """Execute backup job and track progress using new comprehensive device data."""
        try:
            for message in backup_job.backup():
                with self._lock:
                    progress_data = json.loads(message)

                    # Check if this is a metadata message
                    if progress_data.get("status") == "metadata":
                        # Extract and store device metadata
                        try:
                            device_metadata = json.loads(
                                progress_data.get("message", "{}")
                            )
                            self.backup_status[device_id].metadata = device_metadata
                            self._logger.debug(
                                f"Stored device metadata for {device_id}: {device_metadata}"
                            )

                            # Update progress with device metadata fields if available
                            if "backup_status" in device_metadata:
                                self.backup_status[device_id].progress[
                                    "backup_status"
                                ] = device_metadata["backup_status"]
                            if "backup_size" in device_metadata:
                                self.backup_status[device_id].progress[
                                    "backup_size"
                                ] = device_metadata["backup_size"]
                            if "time_since_backup" in device_metadata:
                                self.backup_status[device_id].progress[
                                    "time_since_backup"
                                ] = device_metadata["time_since_backup"]
                            if "backup_type" in device_metadata:
                                self.backup_status[device_id].progress[
                                    "backup_type"
                                ] = device_metadata["backup_type"]
                            if "backup_method" in device_metadata:
                                self.backup_status[device_id].progress[
                                    "backup_method"
                                ] = device_metadata["backup_method"]

                        except json.JSONDecodeError:
                            self._logger.warning(
                                f"Could not parse metadata for device {device_id}"
                            )
                    else:
                        # Merge regular progress information with existing device data
                        current_progress = self.backup_status[device_id].progress.copy()
                        current_progress.update(progress_data)
                        self.backup_status[device_id].progress = current_progress
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
                self._logger.warning(
                    f"Could not check sync status for {device_id}: {e}"
                )
                status.synced = {}

            status.processing = False
            status.ended = int(time.time())

            # Update final progress status
            if success:
                # Update progress with success status while preserving device data
                current_progress = status.progress.copy()
                current_progress.update(
                    {
                        "status": "completed",
                        "message": "Backup completed successfully",
                        "backup_status": 100.0,  # 100% completion
                        "completion_time": status.ended,
                    }
                )
                status.progress = current_progress
            else:
                # Update progress with error status while preserving device data
                current_progress = status.progress.copy()
                current_progress.update(
                    {
                        "status": "error",
                        "message": "Backup failed",
                        "backup_status": 0.0,  # 0% completion on failure
                        "completion_time": status.ended,
                    }
                )
                status.progress = current_progress

    def _handle_backup_failure(self, device_id: str, error_message: str):
        """Handle backup failure by updating status."""
        with self._lock:
            if device_id in self.backup_status:
                status = self.backup_status[device_id]
                status.processing = False
                status.ended = -1  # Indicates failure

                # Update progress with error status while preserving device data
                current_progress = status.progress.copy()
                current_progress.update(
                    {
                        "status": "error",
                        "message": error_message,
                        "backup_status": 0.0,  # 0% completion on failure
                        "completion_time": int(time.time()),
                    }
                )
                status.progress = current_progress

    def run(self):
        """
        Main backup loop with comprehensive fault tolerance and auto-recovery.
        """
        # Log thread startup with multiple loggers to ensure visibility
        logging.info("=== BACKUP WRAPPER THREAD STARTING ===")
        self._logger.info("=== BACKUP WRAPPER THREAD STARTING ===")
        self._logger.info(
            f"Configuration: max_threads={self._max_threads}, interval={self._backup_interval}s, video_backup={self._is_video_backup}"
        )
        logging.info(
            f"Configuration: max_threads={self._max_threads}, interval={self._backup_interval}s, video_backup={self._is_video_backup}"
        )

        # Thread health monitoring
        consecutive_failures = 0
        max_consecutive_failures = 5
        last_successful_cycle = time.time()

        try:
            with ThreadPoolExecutor(
                max_workers=self._max_threads, thread_name_prefix="BackupWorker"
            ) as executor:

                while not self._stop_event.is_set():
                    cycle_start_time = time.time()
                    self._cycle_count += 1
                    self._last_cycle_start = cycle_start_time

                    logging.info(f"=== Starting backup cycle #{self._cycle_count} ===")
                    self._logger.info(
                        f"=== Starting backup cycle #{self._cycle_count} ==="
                    )

                    try:
                        # Execute backup cycle with comprehensive fault tolerance
                        self._execute_backup_cycle_with_recovery(executor)

                        consecutive_failures = 0
                        last_successful_cycle = time.time()

                        cycle_duration = time.time() - cycle_start_time
                        logging.info(
                            f"=== Backup cycle #{self._cycle_count} completed successfully in {cycle_duration:.1f}s ==="
                        )
                        self._logger.info(
                            f"=== Backup cycle #{self._cycle_count} completed successfully in {cycle_duration:.1f}s ==="
                        )

                    except Exception as e:
                        consecutive_failures += 1
                        cycle_duration = time.time() - cycle_start_time

                        logging.error(
                            f"=== ERROR in backup cycle #{self._cycle_count} after {cycle_duration:.1f}s: {e} ==="
                        )
                        self._logger.error(
                            f"=== ERROR in backup cycle #{self._cycle_count} after {cycle_duration:.1f}s: {e} ==="
                        )
                        self._logger.error("Full traceback:", exc_info=True)

                        # Check for critical failure conditions
                        if consecutive_failures >= max_consecutive_failures:
                            time_since_success = time.time() - last_successful_cycle
                            self._logger.error(
                                f"CRITICAL: {consecutive_failures} consecutive backup cycle failures over {time_since_success:.1f}s"
                            )
                            self._logger.error(
                                "Attempting emergency recovery procedures..."
                            )

                            # Emergency recovery
                            try:
                                self._perform_emergency_recovery()
                                consecutive_failures = 0  # Reset after recovery attempt
                            except Exception as recovery_error:
                                self._logger.error(
                                    f"Emergency recovery failed: {recovery_error}"
                                )

                    # Health monitoring and adaptive behavior
                    if not self._stop_event.is_set():
                        # Adaptive wait time based on recent failures
                        wait_time = self._calculate_adaptive_wait_time(
                            consecutive_failures
                        )

                        self._logger.info(
                            f"Backup cycle #{self._cycle_count} complete. Waiting {wait_time}s until next cycle..."
                        )
                        self._logger.info(
                            f"Health status: {consecutive_failures} consecutive failures"
                        )

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
                self._logger.error(
                    f"Failed to preserve emergency state: {preserve_error}"
                )

        finally:
            final_stats = {
                "total_cycles": self._cycle_count,
                "consecutive_failures": consecutive_failures,
                "last_successful_cycle": last_successful_cycle,
            }
            self._logger.info(
                f"=== BACKUP WRAPPER THREAD ENDING === Final stats: {final_stats}"
            )

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
                self._logger.info(
                    "Recovery attempt 1 successful: cleared problematic status entries"
                )
            except Exception as recovery_error:
                self._logger.error(f"Recovery attempt 1 failed: {recovery_error}")

            # Recovery attempt 2: Reset device discovery state
            if not recovery_success:
                try:
                    self._reset_device_discovery_state()
                    recovery_success = True
                    self._logger.info(
                        "Recovery attempt 2 successful: reset device discovery state"
                    )
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
                self._logger.info(
                    f"Cleared {failed_devices} problematic backup status entries"
                )
        except Exception as e:
            self._logger.error(f"Emergency recovery step 1 failed: {e}")

        # Recovery step 2: Reset discovery state
        try:
            self._last_device_count = 0
            self._last_discovery_source = "recovery_reset"
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
                if (
                    hasattr(status, "processing")
                    and status.processing
                    and hasattr(status, "started")
                    and status.started
                    and current_time - status.started > 3600
                ):  # 1 hour
                    problem_devices.append(device_id)

                # Remove devices with error status older than 24 hours
                elif (
                    hasattr(status, "status")
                    and status.status == "error"
                    and hasattr(status, "ended")
                    and status.ended
                    and current_time - status.ended > 86400
                ):  # 24 hours
                    problem_devices.append(device_id)

            for device_id in problem_devices:
                del self.backup_status[device_id]
                self._logger.info(
                    f"Removed problematic status entry for device {device_id}"
                )

            self._logger.info(
                f"Cleared {len(problem_devices)} problematic status entries"
            )

    def _reset_device_discovery_state(self):
        """Reset device discovery state to recover from discovery issues."""
        self._last_device_count = 0
        self._last_discovery_source = "reset"
        self._last_discovery_time = time.time()
        self._logger.info("Reset device discovery state for recovery")

    def _preserve_emergency_state(self, error_message: str):
        """Preserve critical state information before thread termination."""
        emergency_state = {
            "timestamp": time.time(),
            "cycle_count": self._cycle_count,
            "last_cycle_start": self._last_cycle_start,
            "device_count": self._last_device_count,
            "discovery_source": self._last_discovery_source,
            "error_message": error_message,
            "backup_status_count": (
                len(self.backup_status) if hasattr(self, "backup_status") else 0
            ),
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
                device_name = device.get("name", "unknown")
                device_status = device.get("status", "unknown")
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
                self._logger.info(
                    f"Device discovery attempt {attempt}/{max_discovery_attempts}"
                )
                active_devices = self.find_devices()

                if active_devices:
                    self._logger.info(
                        f"Successfully discovered {len(active_devices)} devices on attempt {attempt}"
                    )
                    return active_devices
                else:
                    self._logger.warning(
                        f"No active devices found on attempt {attempt}"
                    )
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
                    self._logger.info("Retrying device discovery in 10 seconds...")
                    time.sleep(10)

        return []

    def _submit_backup_jobs_safely(
        self, executor: ThreadPoolExecutor, active_devices: List[Dict]
    ) -> List[Tuple]:
        """Submit backup jobs with comprehensive error isolation."""
        self._logger.info("Submitting backup jobs to thread pool...")
        futures = []
        successful_submissions = 0
        failed_submissions = 0

        for device in active_devices:
            device_id = device.get("id", "unknown")
            device_name = device.get("name", "unknown")

            try:
                self._logger.info(
                    f"Submitting backup job for device {device_name} (ID: {device_id})"
                )

                # Validate device before submission
                if not self._validate_device_for_backup(device):
                    self._logger.warning(
                        f"Device {device_name} failed validation, skipping"
                    )
                    failed_submissions += 1
                    continue

                # Create fault-isolated backup job wrapper
                future = executor.submit(self._execute_backup_job_safely, device)
                futures.append((future, device_id, device_name))
                successful_submissions += 1

            except Exception as e:
                self._logger.error(
                    f"CRITICAL: Failed to submit backup job for {device_name} (ID: {device_id}): {e}"
                )
                self._logger.error("Full traceback:", exc_info=True)
                failed_submissions += 1

                # Mark device as failed in status
                try:
                    self._handle_backup_failure(
                        device_id, f"Job submission failed: {str(e)}"
                    )
                except Exception as status_error:
                    self._logger.error(
                        f"Additional error updating status for {device_id}: {status_error}"
                    )

        self._logger.info(
            f"Job submission summary: {successful_submissions} successful, {failed_submissions} failed"
        )
        return futures

    def _validate_device_for_backup(self, device: Dict) -> bool:
        """Validate that device has required information for backup."""
        required_fields = ["id", "name", "ip"]

        for field in required_fields:
            if not device.get(field):
                self._logger.warning(
                    f"Device missing required field '{field}': {device}"
                )
                return False

        return True

    def _execute_backup_job_safely(self, device: Dict) -> bool:
        """Execute backup job with comprehensive fault isolation and error recovery."""
        device_id = device.get("id", "unknown")
        device_name = device.get("name", "unknown")

        try:
            # Use the existing initiate_backup_job method which already has error handling
            return self.initiate_backup_job(device)

        except DBNotReadyError as e:
            # Non-critical error - device database not ready
            self._logger.warning(
                f"Device {device_name} database not ready, will retry later: {e}"
            )
            self._handle_backup_failure(device_id, f"Database not ready: {str(e)}")
            return False

        except Exception as e:
            # Critical error - comprehensive logging and recovery
            self._logger.error(
                f"CRITICAL: Backup job for {device_name} (ID: {device_id}) crashed with unexpected error: {e}"
            )
            self._logger.error("Full traceback:", exc_info=True)

            try:
                self._handle_backup_failure(device_id, f"Job crashed: {str(e)}")
            except Exception as status_error:
                self._logger.error(
                    f"Additional error updating status for {device_id}: {status_error}"
                )

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
                self._logger.info(
                    f"Waiting for backup completion: {device_name} (ID: {device_id})"
                )

                # Wait for completion with timeout
                result = future.result(timeout=600)  # 10 minute timeout per job
                completed_jobs += 1

                if result:
                    successful_jobs += 1
                    self._logger.info(
                        f"✓ Backup SUCCESSFUL: {device_name} (ID: {device_id})"
                    )
                else:
                    failed_jobs += 1
                    self._logger.error(
                        f"✗ Backup FAILED: {device_name} (ID: {device_id})"
                    )

            except concurrent.futures.TimeoutError:
                timed_out_jobs += 1
                self._logger.error(
                    f"⏰ Backup TIMED OUT (600s): {device_name} (ID: {device_id})"
                )

                # Cancel the timed out job to free resources
                try:
                    future.cancel()
                    self._handle_backup_failure(
                        device_id, "Backup timed out after 600 seconds"
                    )
                except Exception as cancel_error:
                    self._logger.error(
                        f"Error canceling timed out job for {device_id}: {cancel_error}"
                    )

            except Exception as e:
                failed_jobs += 1
                self._logger.error(
                    f"✗ Backup job CRASHED: {device_name} (ID: {device_id}): {e}"
                )
                self._logger.error("Full traceback:", exc_info=True)

                try:
                    self._handle_backup_failure(
                        device_id, f"Job crashed during execution: {str(e)}"
                    )
                except Exception as status_error:
                    self._logger.error(
                        f"Error updating status for crashed job {device_id}: {status_error}"
                    )

        # Log comprehensive backup cycle summary
        total_jobs = len(futures)
        self._logger.info("=== BACKUP CYCLE SUMMARY ===")
        self._logger.info(f"Total jobs: {total_jobs}")
        self._logger.info(f"Successful: {successful_jobs}")
        self._logger.info(f"Failed: {failed_jobs}")
        self._logger.info(f"Timed out: {timed_out_jobs}")
        self._logger.info(
            f"Success rate: {(successful_jobs/total_jobs*100):.1f}%"
            if total_jobs > 0
            else "N/A"
        )
        self._logger.info("=== END BACKUP CYCLE SUMMARY ===")

    def _update_last_backup_time(self):
        """Update last backup timestamp."""
        self.last_backup = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                if hasattr(status, "__dict__"):
                    # Convert BackupStatus dataclass to dictionary
                    serializable_status[device_id] = {
                        "name": status.name,
                        "status": status.status,
                        "started": status.started,
                        "ended": status.ended,
                        "processing": status.processing,
                        "count": status.count,
                        "synced": status.synced,
                        "progress": status.progress,
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
            status_counts = {
                "processing": 0,
                "success": 0,
                "error": 0,
                "warning": 0,
                "unknown": 0,
            }
            recent_errors = []

            for device_id, status in self.backup_status.items():
                if hasattr(status, "processing") and status.processing:
                    status_counts["processing"] += 1
                elif hasattr(status, "progress") and status.progress:
                    progress_status = status.progress.get("status", "unknown")
                    if progress_status in status_counts:
                        status_counts[progress_status] += 1
                    else:
                        status_counts["unknown"] += 1

                    # Collect recent errors
                    if (
                        progress_status == "error"
                        and hasattr(status, "ended")
                        and status.ended
                        and current_time - status.ended < 3600
                    ):  # Last hour
                        recent_errors.append(
                            {
                                "device_id": device_id,
                                "device_name": getattr(status, "name", "unknown"),
                                "error_time": status.ended,
                                "error_message": status.progress.get(
                                    "message", "Unknown error"
                                ),
                            }
                        )
                else:
                    status_counts["unknown"] += 1

            return {
                "thread_alive": self.is_alive(),
                "thread_running": not self._stop_event.is_set(),
                "cycle_count": self._cycle_count,
                "last_cycle_start": self._last_cycle_start,
                "device_discovery": {
                    "last_count": self._last_device_count,
                    "last_source": self._last_discovery_source,
                    "last_time": self._last_discovery_time,
                },
                "device_status_counts": status_counts,
                "recent_errors": recent_errors,
                "total_tracked_devices": len(self.backup_status),
            }

    def get_statistics(self) -> Dict:
        """
        Get backup statistics.

        Returns:
            dict: Backup statistics
        """
        with self._lock:
            total_devices = len(self.backup_status)
            processing_devices = sum(
                1 for status in self.backup_status.values() if status.processing
            )

            return {
                "total_devices": total_devices,
                "processing_devices": processing_devices,
                "last_backup": self.last_backup,
                "backup_interval": self._backup_interval,
                "is_video_backup": self._is_video_backup,
                "max_threads": self._max_threads,
            }


def _fallback_database_discovery(device_id: str) -> dict:
    """
    Fallback method to discover databases by scanning local filesystem.
    Used when device is offline and cannot provide database information.

    Args:
        device_id: The ethoscope device ID

    Returns:
        dict: Databases dictionary with SQLite and MariaDB information
    """
    databases = {"SQLite": {}, "MariaDB": {}}

    # Scan for SQLite files in results directory
    data_dir = "/ethoscope_data"
    results_dir = os.path.join(data_dir, "results", device_id)

    if os.path.exists(results_dir):
        for root, _dirs, files in os.walk(results_dir):
            for file in files:
                if file.endswith(".db"):
                    file_path = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(file_path)
                        file_stat = os.path.stat(file_path)

                        databases["SQLite"][file] = {
                            "filesize": file_size,
                            "backup_filename": file,
                            "version": "Unknown",
                            "path": file_path,
                            "date": file_stat.st_mtime,
                            "db_status": "unknown",
                            "table_counts": {},
                            "file_exists": True,
                        }
                    except OSError:
                        # File might be inaccessible, include with 0 size
                        databases["SQLite"][file] = {
                            "filesize": 0,
                            "backup_filename": file,
                            "version": "Unknown",
                            "path": file_path,
                            "date": 0,
                            "db_status": "error",
                            "table_counts": {},
                            "file_exists": False,
                        }

    return databases


def _format_bytes_simple(bytes_size: int) -> str:
    """Simple bytes formatting helper."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def _get_video_cache_path(
    device_id: str, video_directory: str = "/ethoscope_data/videos"
) -> str:
    """Get the file path for video cache for a specific device in the video directory root."""
    import os

    cache_dir = os.path.join(video_directory, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"video_cache_{device_id}.pkl")


def _load_video_cache(
    device_id: str, video_directory: str = "/ethoscope_data/videos"
) -> dict:
    """Load video file cache from disk."""
    import logging
    import os
    import pickle

    cache_path = _get_video_cache_path(device_id, video_directory)
    try:
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                cache_data = pickle.load(f)
                # Validate cache structure
                if (
                    isinstance(cache_data, dict)
                    and "files" in cache_data
                    and "timestamp" in cache_data
                ):
                    return cache_data
    except Exception as e:
        logging.warning(f"Failed to load video cache for {device_id}: {e}")
    return {"files": {}, "timestamp": 0}


def _save_video_cache(
    device_id: str, video_files: dict, video_directory: str = "/ethoscope_data/videos"
) -> None:
    """Save video file cache to disk."""
    import logging
    import pickle
    import time

    cache_path = _get_video_cache_path(device_id, video_directory)
    try:
        cache_data = {"files": video_files, "timestamp": time.time()}
        with open(cache_path, "wb") as f:
            pickle.dump(cache_data, f)
        logging.info(
            f"Saved video cache for {device_id}: {len(video_files)} files to {cache_path}"
        )
    except Exception as e:
        logging.warning(f"Failed to save video cache for {device_id}: {e}")


def _is_file_older_than_week(file_path: str) -> bool:
    """Check if a file is older than a week."""
    import os
    import time

    try:
        file_mtime = os.path.getmtime(file_path)
        one_week_ago = time.time() - (7 * 24 * 60 * 60)  # 7 days in seconds
        return file_mtime < one_week_ago
    except OSError:
        return False


def _get_device_size_cache_path(
    device_id: str, base_directory: str = "/ethoscope_data"
) -> str:
    """Get the file path for device size cache."""
    import os

    cache_dir = os.path.join(base_directory, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"device_size_cache_{device_id}.pkl")


def _load_device_size_cache(
    device_id: str, base_directory: str = "/ethoscope_data"
) -> dict:
    """Load device size cache from disk."""
    import logging
    import os
    import pickle
    import time

    cache_path = _get_device_size_cache_path(device_id, base_directory)
    try:
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                cache_data = pickle.load(f)

                # Validate cache structure and check TTL
                if (
                    isinstance(cache_data, dict)
                    and "videos_size" in cache_data
                    and "results_size" in cache_data
                    and "timestamp" in cache_data
                ):

                    # Check if cache is still valid (1 hour TTL)
                    cache_age = time.time() - cache_data["timestamp"]
                    cache_ttl = cache_data.get("ttl", 3600)  # Default 1 hour

                    if cache_age < cache_ttl:
                        return cache_data
                    else:
                        logging.debug(
                            f"Device size cache expired for {device_id} (age: {cache_age:.0f}s)"
                        )

    except Exception as e:
        logging.warning(f"Failed to load device size cache for {device_id}: {e}")

    return {"videos_size": 0, "results_size": 0, "timestamp": 0, "ttl": 3600}


def _save_device_size_cache(
    device_id: str,
    videos_size: int,
    results_size: int,
    base_directory: str = "/ethoscope_data",
) -> None:
    """Save device size cache to disk."""
    import logging
    import pickle
    import time

    cache_path = _get_device_size_cache_path(device_id, base_directory)
    try:
        cache_data = {
            "videos_size": videos_size,
            "results_size": results_size,
            "timestamp": time.time(),
            "ttl": 3600,  # 1 hour cache TTL
        }

        with open(cache_path, "wb") as f:
            pickle.dump(cache_data, f)

        logging.info(
            f"Saved device size cache for {device_id}: videos={_format_bytes_simple(videos_size)}, "
            f"results={_format_bytes_simple(results_size)}"
        )

    except Exception as e:
        logging.warning(f"Failed to save device size cache for {device_id}: {e}")


def _get_device_disk_usage(
    device_id: str, base_directory: str, subdirectory: str
) -> int:
    """
    Get disk usage for a specific device directory using du command.

    Args:
        device_id: The ethoscope device ID
        base_directory: Base directory (e.g., '/ethoscope_data')
        subdirectory: Subdirectory name ('videos' or 'results')

    Returns:
        int: Size in bytes, 0 if directory doesn't exist or command fails
    """
    import logging
    import os
    import subprocess

    device_dir = os.path.join(base_directory, subdirectory, device_id)

    if not os.path.exists(device_dir):
        return 0

    try:
        # Use du -sb for size in bytes, -x to stay on same filesystem
        result = subprocess.run(
            ["du", "-sbx", device_dir],
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout for large directories
        )

        if result.returncode == 0:
            # du output format: "size_bytes    directory_path"
            size_bytes = int(result.stdout.split()[0])
            logging.debug(
                f"Device {device_id} {subdirectory} size: {_format_bytes_simple(size_bytes)}"
            )
            return size_bytes
        else:
            logging.warning(f"du command failed for {device_dir}: {result.stderr}")
            return 0

    except subprocess.TimeoutExpired:
        logging.warning(f"du command timeout for {device_dir}")
        return 0
    except (ValueError, IndexError, OSError) as e:
        logging.warning(f"Error calculating disk usage for {device_dir}: {e}")
        return 0


def _get_device_backup_sizes_cached(
    device_id: str, base_directory: str = "/ethoscope_data"
) -> dict:
    """
    Get device-specific backup sizes with caching for performance.

    Returns cached values immediately if available, and optionally triggers
    background update if cache is expired.

    Args:
        device_id: The ethoscope device ID
        base_directory: Base directory containing videos and results

    Returns:
        dict: {'videos_size': bytes, 'results_size': bytes, 'cache_hit': bool, 'cache_age': seconds}
    """
    import logging
    import time

    # Load cached values first
    cache_data = _load_device_size_cache(device_id, base_directory)
    cache_hit = cache_data["timestamp"] > 0
    cache_age = time.time() - cache_data["timestamp"] if cache_hit else float("inf")

    # If cache is valid (< 1 hour old), return cached values
    cache_ttl = cache_data.get("ttl", 3600)
    if cache_age < cache_ttl:
        return {
            "videos_size": cache_data["videos_size"],
            "results_size": cache_data["results_size"],
            "cache_hit": True,
            "cache_age": cache_age,
        }

    # Cache is expired or missing, calculate new values
    logging.info(
        f"Calculating fresh disk usage for device {device_id} (cache age: {cache_age:.0f}s)"
    )

    videos_size = _get_device_disk_usage(device_id, base_directory, "videos")
    results_size = _get_device_disk_usage(device_id, base_directory, "results")

    # Save updated cache
    _save_device_size_cache(device_id, videos_size, results_size, base_directory)

    return {
        "videos_size": videos_size,
        "results_size": results_size,
        "cache_hit": False,
        "cache_age": 0,
    }


def _enhance_databases_with_rsync_info(device_id: str, databases: dict) -> dict:
    """
    Enhance database information with file sizes from rsync backup service.
    Uses file-based caching for video files older than a week to reduce filesystem scanning.

    Args:
        device_id: The ethoscope device ID
        databases: The databases dictionary to enhance

    Returns:
        dict: Enhanced databases with actual file sizes from rsync service
    """
    try:
        import glob
        import json
        import logging
        import os
        import urllib.error
        import urllib.request

        # Try to get enhanced file info from rsync backup service
        rsync_url = "http://localhost:8093/status"

        with urllib.request.urlopen(rsync_url, timeout=5) as response:
            rsync_data = json.loads(response.read().decode())

        # Extract file details for this device
        device_data = rsync_data.get("devices", {}).get(device_id, {})

        if device_data:
            logging.info(
                f"[ENHANCE] Found device data for {device_id} in rsync service"
            )
        else:
            logging.warning(
                f"[ENHANCE] No device data found for {device_id} in rsync service"
            )
        synced_data = device_data.get("synced", {})

        # Enhance SQLite database entries with rsync file sizes
        detailed_files = synced_data.get("results", {}).get("detailed_files", {})
        if "SQLite" in databases:
            for db_name, db_info in databases["SQLite"].items():
                if detailed_files and db_name in detailed_files:
                    # Update with actual file size from rsync if available
                    rsync_file_info = detailed_files[db_name]
                    db_info["filesize"] = rsync_file_info.get(
                        "size_bytes", db_info.get("filesize", 0)
                    )
                    db_info["size_human"] = rsync_file_info.get("size_human", "")
                    db_info["rsync_enhanced"] = True
                elif db_info.get("filesize", 0) == 0 and db_info.get("path"):
                    # File not in rsync cache and has 0 size, try filesystem fallback
                    try:
                        file_path = db_info["path"]
                        if os.path.exists(file_path):
                            actual_size = os.path.getsize(file_path)
                            db_info["filesize"] = actual_size
                            db_info["size_human"] = _format_bytes_simple(actual_size)
                            db_info["filesystem_enhanced"] = True
                    except (OSError, KeyError):
                        pass  # Keep original filesize

        # Add video backup information from rsync data
        video_data = synced_data.get("videos", {})
        transfer_details = device_data.get("transfer_details", {})

        logging.info(f"[ENHANCE] Video data available: {bool(video_data)}")
        logging.info(
            f"[ENHANCE] Transfer details available: {bool(transfer_details.get('videos'))}"
        )

        if video_data or transfer_details.get("videos"):
            logging.info("[ENHANCE] Processing video backup data...")
            # Add video backup to databases structure
            if "Video" not in databases:
                databases["Video"] = {}

            # Extract video files information - prefer detailed_files, fall back to transfer_details
            video_files = {}

            # First try to get from synced.videos.detailed_files (comprehensive data)
            detailed_video_files = video_data.get("detailed_files", {})
            if detailed_video_files:
                for filename, file_info in detailed_video_files.items():
                    # Only include .h264 files (exclude .md5 checksum files)
                    if filename.endswith(".h264"):
                        video_files[filename] = {
                            "size_bytes": file_info.get("size_bytes", 0),
                            "size_human": file_info.get("size_human", "0B"),
                            "path": file_info.get("path", ""),
                            "status": file_info.get("status", "unknown"),
                            "transfer_speed": file_info.get("transfer_speed", ""),
                        }

            # If no detailed files, try transfer_details as fallback
            elif transfer_details.get("videos", {}).get("files"):
                transfer_video_files = transfer_details["videos"]["files"]
                for filename, file_info in transfer_video_files.items():
                    # Only include .h264 files (exclude .md5 checksum files)
                    if filename.endswith(".h264"):
                        video_files[filename] = {
                            "size_bytes": file_info.get("size_bytes", 0),
                            "size_human": file_info.get("size_human", "0B"),
                            "path": file_info.get("path", ""),
                            "status": file_info.get("status", "unknown"),
                            "transfer_speed": file_info.get("transfer_speed", ""),
                        }

            # If no individual files found from rsync but we have summary data, try cache-aware filesystem fallback
            if not video_files and video_data.get("local_files", 0) > 0:
                # Try to enumerate video files from filesystem using cache optimization
                video_directory = video_data.get("directory", "/ethoscope_data/videos")

                # Load cached video file information
                cache_data = _load_video_cache(device_id, video_directory)
                cached_files = cache_data.get("files", {})

                device_video_path = f"{video_directory}/{device_id}"

                try:
                    if os.path.exists(device_video_path):
                        # Find all .h264 files for this device
                        h264_pattern = f"{device_video_path}/**/*.h264"
                        h264_files = glob.glob(h264_pattern, recursive=True)

                        new_files_found = 0
                        cache_hits = 0

                        for h264_file in h264_files:
                            if os.path.exists(h264_file):
                                filename = os.path.basename(h264_file)
                                relative_path = os.path.relpath(
                                    h264_file, video_directory
                                )

                                # Check if file is in cache and older than a week
                                if (
                                    filename in cached_files
                                    and _is_file_older_than_week(h264_file)
                                ):
                                    # Use cached information for old files
                                    video_files[filename] = cached_files[filename]
                                    video_files[filename]["cache_hit"] = True
                                    cache_hits += 1
                                else:
                                    # Fresh scan for new/recent files
                                    file_size = os.path.getsize(h264_file)
                                    video_files[filename] = {
                                        "size_bytes": file_size,
                                        "size_human": _format_bytes_simple(file_size),
                                        "path": relative_path,
                                        "status": "backed-up",
                                        "filesystem_enhanced": True,
                                        "cache_hit": False,
                                    }
                                    new_files_found += 1

                        # Save updated cache with all current files
                        _save_video_cache(device_id, video_files, video_directory)

                        logging.info(
                            f"[ENHANCE] Found {len(video_files)} video files via cache-aware filesystem fallback "
                            f"(cache hits: {cache_hits}, fresh scans: {new_files_found})"
                        )
                except Exception as e:
                    logging.warning(
                        f"[ENHANCE] Cache-aware filesystem video enumeration failed: {e}"
                    )

            # Get device-specific backup sizes using cached du calculation
            # This replaces the problematic disk_usage_bytes which was returning total directory size
            device_sizes = _get_device_backup_sizes_cached(device_id)

            logging.info(
                f"[ENHANCE] Device {device_id} backup sizes: "
                f"videos={_format_bytes_simple(device_sizes['videos_size'])}, "
                f"cache_hit={device_sizes['cache_hit']}, "
                f"cache_age={device_sizes.get('cache_age', 0):.0f}s"
            )

            # Use device-specific video size from cache/du calculation
            total_video_size = device_sizes["videos_size"]
            total_video_files = video_data.get("local_files", 0)

            # If no file count from rsync but we have video files from detailed scan, use that count
            if total_video_files == 0 and video_files:
                total_video_files = len(video_files)

            # If we have individual file details but no cached size, calculate from file details
            if total_video_size == 0 and video_files:
                total_video_size = sum(
                    f.get("size_bytes", 0) for f in video_files.values()
                )

            databases["Video"]["video_backup"] = {
                "total_files": total_video_files,
                "total_size_bytes": total_video_size,
                "size_human": _format_bytes_simple(total_video_size),
                "files": video_files,
                "directory": f"{video_data.get('directory', '/ethoscope_data/videos')}/{device_id}",
                "rsync_enhanced": len(video_files) > 0,
            }

        return databases

    except Exception as e:
        # If rsync service is unavailable, return databases unchanged
        logging.warning(f"[ENHANCE] Failed to enhance databases with rsync info: {e}")
        return databases


def get_device_backup_info(device_id: str, databases: dict) -> dict:
    """
    Get backup information for a specific device based on its databases.

    Args:
        device_id: The ethoscope device ID
        databases: The databases dictionary from device.info()["databases"]

    Returns:
        dict: Backup information including database types and backup status
    """
    # If databases dict is empty (device offline), use fallback discovery
    if not databases or not any(databases.values()):
        databases = _fallback_database_discovery(device_id)

    # Enhance with rsync backup service file sizes if available
    databases = _enhance_databases_with_rsync_info(device_id, databases)

    # Get device-specific backup sizes for accurate reporting
    device_sizes = _get_device_backup_sizes_cached(device_id)

    backup_info = {
        "device_id": device_id,
        "databases": databases,
        "backup_status": {
            "mysql": {
                "available": False,
                "database_count": 0,
                "databases": [],
                "total_size_bytes": 0,
            },
            "sqlite": {
                "available": False,
                "database_count": 0,
                "databases": [],
                "total_size_bytes": 0,
            },
            "video": {
                "available": False,
                "file_count": 0,
                "total_size_bytes": 0,
                "size_human": "0B",
            },
            "total_databases": 0,
        },
        "recommended_backup_type": None,
    }

    # Count total databases
    total_db_count = 0
    mysql_databases = []
    sqlite_databases = []

    # Check for MySQL/MariaDB databases
    if "MariaDB" in databases:
        mariadb_dbs = databases["MariaDB"]
        if mariadb_dbs and isinstance(mariadb_dbs, dict):
            mysql_databases = list(mariadb_dbs.keys())
            backup_info["backup_status"]["mysql"]["available"] = True
            backup_info["backup_status"]["mysql"]["database_count"] = len(
                mysql_databases
            )
            backup_info["backup_status"]["mysql"]["databases"] = mysql_databases
            # For MySQL, we could calculate exported backup size specifically, but for now use results size
            # This represents the size of data that would be backed up from this device's database
            backup_info["backup_status"]["mysql"]["total_size_bytes"] = device_sizes[
                "results_size"
            ]
            total_db_count += len(mysql_databases)

    # Check for SQLite databases
    if "SQLite" in databases:
        sqlite_dbs = databases["SQLite"]
        if sqlite_dbs and isinstance(sqlite_dbs, dict):
            sqlite_databases = list(sqlite_dbs.keys())
            backup_info["backup_status"]["sqlite"]["available"] = True
            backup_info["backup_status"]["sqlite"]["database_count"] = len(
                sqlite_databases
            )
            backup_info["backup_status"]["sqlite"]["databases"] = sqlite_databases
            # For SQLite, use results directory size (where SQLite files are stored)
            backup_info["backup_status"]["sqlite"]["total_size_bytes"] = device_sizes[
                "results_size"
            ]
            total_db_count += len(sqlite_databases)

    # Check for Video backup
    if "Video" in databases:
        video_data = databases["Video"]
        if video_data and isinstance(video_data, dict):
            # Get video backup information
            video_backup = video_data.get("video_backup", {})
            if video_backup:
                backup_info["backup_status"]["video"]["available"] = True
                backup_info["backup_status"]["video"]["file_count"] = video_backup.get(
                    "total_files", 0
                )
                backup_info["backup_status"]["video"]["total_size_bytes"] = (
                    video_backup.get("total_size_bytes", 0)
                )
                backup_info["backup_status"]["video"]["size_human"] = video_backup.get(
                    "size_human", "0B"
                )
                backup_info["backup_status"]["video"]["directory"] = video_backup.get(
                    "directory", f"/ethoscope_data/videos/{device_id}"
                )

    backup_info["backup_status"]["total_databases"] = total_db_count

    # Determine recommended backup type
    if backup_info["backup_status"]["mysql"]["available"]:
        backup_info["recommended_backup_type"] = "mysql"
    elif backup_info["backup_status"]["sqlite"]["available"]:
        backup_info["recommended_backup_type"] = "rsync"
    else:
        backup_info["recommended_backup_type"] = "none"

    return backup_info
