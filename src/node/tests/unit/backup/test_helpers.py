"""
Unit tests for backup helpers module.

Tests cover:
- Utility functions (get_sqlite_table_counts, calculate_backup_percentage)
- BackupStatus dataclass
- Backup file locking mechanisms
- Backup completion tracking functions
- BackupClass initialization and validation
- get_device_backup_info function
"""

import datetime
import fcntl
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, mock_open, patch

import pytest

from ethoscope_node.backup.helpers import (
    BackupClass,
    BackupError,
    BackupLockError,
    BackupStatus,
    backup_file_lock,
    calculate_backup_percentage_from_table_counts,
    get_backup_completion_file,
    get_device_backup_info,
    get_sqlite_table_counts,
    is_backup_recent,
    mark_backup_completed,
)


class TestGetSqliteTableCounts:
    """Test get_sqlite_table_counts utility function."""

    def test_get_table_counts_empty_database(self, tmp_path):
        """Test getting counts from an empty database."""
        db_path = tmp_path / "test.db"

        # Create empty database
        conn = sqlite3.connect(str(db_path))
        conn.close()

        counts = get_sqlite_table_counts(str(db_path))
        assert counts == {}

    def test_get_table_counts_with_tables(self, tmp_path):
        """Test getting counts from database with tables."""
        db_path = tmp_path / "test.db"

        # Create database with tables
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Create tables with data
        cursor.execute("CREATE TABLE METADATA (id INTEGER PRIMARY KEY, name TEXT)")
        cursor.execute("CREATE TABLE VAR_MAP (id INTEGER PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE ROI_MAP (id INTEGER PRIMARY KEY, roi TEXT)")

        # Insert data
        cursor.execute("INSERT INTO METADATA (name) VALUES ('test1')")
        cursor.execute("INSERT INTO METADATA (name) VALUES ('test2')")
        cursor.execute("INSERT INTO VAR_MAP (value) VALUES ('val1')")
        cursor.execute("INSERT INTO VAR_MAP (value) VALUES ('val2')")
        cursor.execute("INSERT INTO VAR_MAP (value) VALUES ('val3')")

        conn.commit()
        conn.close()

        counts = get_sqlite_table_counts(str(db_path))

        assert counts["METADATA"] == 2
        assert counts["VAR_MAP"] == 3
        assert counts["ROI_MAP"] == 0

    def test_get_table_counts_nonexistent_file(self, tmp_path):
        """Test handling of nonexistent database file."""
        db_path = tmp_path / "nonexistent.db"

        counts = get_sqlite_table_counts(str(db_path))
        assert counts == {}

    def test_get_table_counts_corrupted_table(self, tmp_path):
        """Test handling of corrupted table that can't be queried."""
        db_path = tmp_path / "test.db"

        # Create database with a table
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE good_table (id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO good_table (id) VALUES (1)")
        conn.commit()
        conn.close()

        # Mock sqlite3.connect to simulate corrupted table
        with patch("ethoscope_node.backup.helpers.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=None)
            mock_conn.cursor.return_value = mock_cursor

            # Make fetchall return table names
            mock_cursor.fetchall.return_value = [("good_table",), ("bad_table",)]

            # Make COUNT fail for bad_table
            def side_effect_execute(query):
                if "bad_table" in query:
                    raise sqlite3.Error("Table is corrupted")
                elif "good_table" in query:
                    return MagicMock(fetchone=lambda: [5])
                else:
                    return MagicMock(fetchall=lambda: [("good_table",), ("bad_table",)])

            mock_cursor.execute.side_effect = side_effect_execute
            mock_cursor.fetchone.return_value = [5]

            counts = get_sqlite_table_counts(str(db_path))

            # Should have count for good_table and 0 for bad_table
            assert "good_table" in counts or "bad_table" in counts


class TestCalculateBackupPercentage:
    """Test calculate_backup_percentage_from_table_counts function."""

    def test_calculate_percentage_empty_remote(self):
        """Test with empty remote database."""
        remote_counts = {}
        backup_counts = {"METADATA": 1, "VAR_MAP": 1}

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        assert percentage == 0.0

    def test_calculate_percentage_full_backup(self):
        """Test with complete backup."""
        remote_counts = {
            "METADATA": 10,
            "VAR_MAP": 5,
            "ROI_MAP": 3,
            "IMG_SNAPSHOTS": 100,
        }
        backup_counts = {
            "METADATA": 10,
            "VAR_MAP": 5,
            "ROI_MAP": 3,
            "IMG_SNAPSHOTS": 100,
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        assert percentage == 100.0

    def test_calculate_percentage_partial_backup(self):
        """Test with partial backup."""
        remote_counts = {
            "METADATA": 10,
            "VAR_MAP": 5,
            "IMG_SNAPSHOTS": 100,
        }
        backup_counts = {
            "METADATA": 10,
            "VAR_MAP": 5,
            "IMG_SNAPSHOTS": 50,  # 50% of data backed up
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        assert percentage == 50.0

    def test_calculate_percentage_no_data_tables(self):
        """Test with only metadata tables (no data)."""
        remote_counts = {
            "METADATA": 1,
            "VAR_MAP": 1,
            "ROI_MAP": 1,
        }
        backup_counts = {
            "METADATA": 1,
            "VAR_MAP": 1,
            "ROI_MAP": 1,
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        # Should return 100% since structure exists but no data tables
        assert percentage == 100.0

    def test_calculate_percentage_missing_structure(self):
        """Test when backup is missing required structure tables."""
        remote_counts = {
            "METADATA": 1,
            "VAR_MAP": 1,
        }
        backup_counts = {
            "METADATA": 1,
            # Missing VAR_MAP
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        assert percentage == 0.0

    def test_calculate_percentage_excludes_metadata_tables(self):
        """Test that metadata tables don't affect percentage calculation."""
        remote_counts = {
            "METADATA": 100,
            "VAR_MAP": 100,
            "ROI_MAP": 100,
            "START_EVENTS": 100,
            "IMG_SNAPSHOTS": 100,  # Only data table
        }
        backup_counts = {
            "METADATA": 50,  # Different count in metadata
            "VAR_MAP": 50,
            "ROI_MAP": 50,
            "START_EVENTS": 50,
            "IMG_SNAPSHOTS": 50,  # 50% of data backed up
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        # Only IMG_SNAPSHOTS counts: 50/100 = 50%
        assert percentage == 50.0

    def test_calculate_percentage_caps_at_100(self):
        """Test that percentage is capped at 100% even if backup has more rows."""
        remote_counts = {
            "IMG_SNAPSHOTS": 100,
        }
        backup_counts = {
            "IMG_SNAPSHOTS": 150,  # More than remote (shouldn't happen, but handle it)
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        assert percentage == 100.0

    def test_calculate_percentage_mixed_progress(self):
        """Test with different progress across tables."""
        remote_counts = {
            "METADATA": 1,
            "VAR_MAP": 1,
            "TABLE1": 100,
            "TABLE2": 200,
        }
        backup_counts = {
            "METADATA": 1,
            "VAR_MAP": 1,
            "TABLE1": 100,  # 100% backed up
            "TABLE2": 50,  # 25% backed up
        }

        percentage = calculate_backup_percentage_from_table_counts(
            remote_counts, backup_counts
        )
        # (100 + 50) / (100 + 200) = 150/300 = 50%
        assert percentage == 50.0


class TestBackupStatus:
    """Test BackupStatus dataclass."""

    def test_backup_status_default_initialization(self):
        """Test BackupStatus with default values."""
        status = BackupStatus()

        assert status.name == ""
        assert status.status == ""
        assert status.started == 0
        assert status.ended == 0
        assert status.processing is False
        assert status.count == 0
        assert status.synced == {}
        assert status.progress == {}
        assert status.metadata == {}

    def test_backup_status_with_values(self):
        """Test BackupStatus with provided values."""
        status = BackupStatus(
            name="device_001",
            status="running",
            started=123456,
            ended=123789,
            processing=True,
            count=5,
        )

        assert status.name == "device_001"
        assert status.status == "running"
        assert status.started == 123456
        assert status.ended == 123789
        assert status.processing is True
        assert status.count == 5
        assert status.synced == {}
        assert status.progress == {}
        assert status.metadata == {}

    def test_backup_status_with_dictionaries(self):
        """Test BackupStatus with dictionary values."""
        synced_data = {"db1": True, "db2": False}
        progress_data = {"percent": 75.5}
        metadata_data = {"size": 1024}

        status = BackupStatus(
            name="device_002",
            synced=synced_data,
            progress=progress_data,
            metadata=metadata_data,
        )

        assert status.synced == synced_data
        assert status.progress == progress_data
        assert status.metadata == metadata_data

    def test_backup_status_none_dictionaries_initialized(self):
        """Test that None dictionary values are initialized to empty dicts."""
        status = BackupStatus(
            name="test",
            synced=None,
            progress=None,
            metadata=None,
        )

        assert status.synced == {}
        assert status.progress == {}
        assert status.metadata == {}


class TestBackupFileLock:
    """Test backup_file_lock context manager."""

    def test_backup_file_lock_creates_lock_file(self, tmp_path):
        """Test that lock file is created."""
        backup_path = tmp_path / "test.db"
        lock_path = Path(f"{backup_path}.lock")

        with backup_file_lock(str(backup_path)) as lock:
            assert lock is not None
            assert lock_path.exists()

        # Lock file should be removed after context exit
        assert not lock_path.exists()

    def test_backup_file_lock_creates_directory(self, tmp_path):
        """Test that lock file directory is created if it doesn't exist."""
        backup_path = tmp_path / "subdir" / "nested" / "test.db"

        with backup_file_lock(str(backup_path)) as lock:
            assert lock is not None
            assert Path(f"{backup_path}.lock").exists()

        assert not Path(f"{backup_path}.lock").exists()

    def test_backup_file_lock_writes_process_info(self, tmp_path):
        """Test that process info is written to lock file."""
        backup_path = tmp_path / "test.db"
        lock_path = Path(f"{backup_path}.lock")

        with backup_file_lock(str(backup_path)):
            # Read lock file content while locked
            with open(lock_path) as f:
                content = f.read()

            assert "PID:" in content
            assert str(os.getpid()) in content
            assert "Timestamp:" in content

    def test_backup_file_lock_prevents_concurrent_access(self, tmp_path):
        """Test that lock prevents concurrent access."""
        backup_path = tmp_path / "test.db"

        with backup_file_lock(str(backup_path)):
            # Try to acquire lock again (should fail)
            with pytest.raises(BackupLockError):
                with backup_file_lock(str(backup_path)):
                    pass

    def test_backup_file_lock_cleanup_on_exception(self, tmp_path):
        """Test that lock file is cleaned up even when exception occurs."""
        backup_path = tmp_path / "test.db"
        lock_path = Path(f"{backup_path}.lock")

        try:
            with backup_file_lock(str(backup_path)):
                assert lock_path.exists()
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Lock file should still be removed
        assert not lock_path.exists()


class TestBackupCompletionFunctions:
    """Test backup completion tracking functions."""

    def test_get_backup_completion_file(self):
        """Test get_backup_completion_file returns correct path."""
        backup_path = "/path/to/backup.db"
        completion_file = get_backup_completion_file(backup_path)

        assert completion_file == "/path/to/backup.db.completed"

    def test_is_backup_recent_no_completion_file(self, tmp_path):
        """Test is_backup_recent with no completion file."""
        backup_path = tmp_path / "test.db"

        result = is_backup_recent(str(backup_path))
        assert result is False

    def test_is_backup_recent_within_max_age(self, tmp_path):
        """Test is_backup_recent with recent completion file."""
        backup_path = tmp_path / "test.db"
        completion_file = Path(f"{backup_path}.completed")

        # Create completion file
        completion_file.touch()

        result = is_backup_recent(str(backup_path), max_age_hours=1)
        assert result is True

    def test_is_backup_recent_exceeds_max_age(self, tmp_path):
        """Test is_backup_recent with old completion file."""
        backup_path = tmp_path / "test.db"
        completion_file = Path(f"{backup_path}.completed")

        # Create completion file and set old timestamp
        completion_file.touch()
        old_time = time.time() - (2 * 3600)  # 2 hours ago
        os.utime(completion_file, (old_time, old_time))

        result = is_backup_recent(str(backup_path), max_age_hours=1)
        assert result is False

    def test_is_backup_recent_custom_max_age(self, tmp_path):
        """Test is_backup_recent with custom max_age_hours."""
        backup_path = tmp_path / "test.db"
        completion_file = Path(f"{backup_path}.completed")

        # Create completion file 30 minutes ago
        completion_file.touch()
        old_time = time.time() - (0.5 * 3600)
        os.utime(completion_file, (old_time, old_time))

        # Should be recent for 1 hour max age
        assert is_backup_recent(str(backup_path), max_age_hours=1) is True

        # Should not be recent for 15 minute max age
        assert is_backup_recent(str(backup_path), max_age_hours=0.25) is False

    def test_is_backup_recent_handles_os_error(self, tmp_path):
        """Test is_backup_recent handles OS errors gracefully."""
        backup_path = tmp_path / "test.db"

        # Mock os.path.exists to return True but os.path.getmtime to raise OSError
        with patch("ethoscope_node.backup.helpers.os.path.exists", return_value=True):
            with patch(
                "ethoscope_node.backup.helpers.os.path.getmtime",
                side_effect=OSError("Test error"),
            ):
                result = is_backup_recent(str(backup_path))
                assert result is False

    def test_mark_backup_completed_creates_file(self, tmp_path):
        """Test mark_backup_completed creates completion file."""
        backup_path = tmp_path / "test.db"
        backup_path.touch()

        mark_backup_completed(str(backup_path))

        completion_file = Path(f"{backup_path}.completed")
        assert completion_file.exists()

    def test_mark_backup_completed_contains_metadata(self, tmp_path):
        """Test mark_backup_completed writes correct metadata."""
        backup_path = tmp_path / "test.db"
        # Create file with some content to have non-zero size
        backup_path.write_text("some backup data")

        stats = {"rows": 100, "tables": 5}
        mark_backup_completed(str(backup_path), stats=stats)

        completion_file = Path(f"{backup_path}.completed")
        with open(completion_file) as f:
            data = json.load(f)

        assert "completed_at" in data
        assert data["backup_file"] == str(backup_path)
        assert data["file_size"] > 0
        assert data["stats"] == stats

    def test_mark_backup_completed_no_stats(self, tmp_path):
        """Test mark_backup_completed with no stats."""
        backup_path = tmp_path / "test.db"
        backup_path.touch()

        mark_backup_completed(str(backup_path))

        completion_file = Path(f"{backup_path}.completed")
        with open(completion_file) as f:
            data = json.load(f)

        assert data["stats"] == {}

    def test_mark_backup_completed_missing_backup_file(self, tmp_path):
        """Test mark_backup_completed when backup file doesn't exist."""
        backup_path = tmp_path / "nonexistent.db"

        mark_backup_completed(str(backup_path))

        completion_file = Path(f"{backup_path}.completed")
        assert completion_file.exists()

        with open(completion_file) as f:
            data = json.load(f)

        assert data["file_size"] == 0

    def test_mark_backup_completed_handles_write_error(self, tmp_path):
        """Test mark_backup_completed handles write errors gracefully."""
        backup_path = tmp_path / "test.db"

        # Mock open to raise OSError
        with patch(
            "ethoscope_node.backup.helpers.open", side_effect=OSError("Test error")
        ):
            # Should not raise exception
            mark_backup_completed(str(backup_path))


class TestBackupClass:
    """Test BackupClass initialization and validation methods."""

    def test_backup_class_initialization(self):
        """Test BackupClass basic initialization."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {},
        }
        results_dir = "/tmp/results"

        backup = BackupClass(device_info, results_dir)

        assert backup._device_id == "device_001"
        assert backup._device_name == "ETHOSCOPE_001"
        assert backup._ip == "192.168.1.100"
        assert backup._database_ip == "192.168.1.100"
        assert backup._results_dir == results_dir

    def test_backup_class_db_credentials(self):
        """Test BackupClass has correct database credentials."""
        assert BackupClass.DB_CREDENTIALS["name"] == "ethoscope_db"
        assert BackupClass.DB_CREDENTIALS["user"] == "ethoscope"
        assert BackupClass.DB_CREDENTIALS["password"] == "ethoscope"

    def test_backup_class_db_timeouts(self):
        """Test BackupClass has defined timeouts."""
        assert BackupClass.DB_CONNECTION_TIMEOUT == 30
        assert BackupClass.DB_OPERATION_TIMEOUT == 120

    def test_validate_mariadb_database_no_databases(self):
        """Test _validate_mariadb_database with no databases."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {},
        }

        backup = BackupClass(device_info, "/tmp/results")
        result = backup._validate_mariadb_database()

        assert result is False

    def test_validate_mariadb_database_with_mariadb(self):
        """Test _validate_mariadb_database with MariaDB database."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {
                "MariaDB": {
                    "ethoscope_db": {
                        "path": "/var/lib/mysql/ethoscope_db",
                        "size": 1024000,
                    }
                }
            },
        }

        backup = BackupClass(device_info, "/tmp/results")
        result = backup._validate_mariadb_database()

        assert result is True

    def test_validate_mariadb_database_empty_mariadb(self):
        """Test _validate_mariadb_database with empty MariaDB dict."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {"MariaDB": {}},
        }

        backup = BackupClass(device_info, "/tmp/results")
        result = backup._validate_mariadb_database()

        assert result is False

    def test_validate_mariadb_database_only_sqlite(self):
        """Test _validate_mariadb_database with only SQLite databases."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {
                "SQLite": {
                    "results.db": {
                        "path": "/ethoscope_data/results/results.db",
                    }
                }
            },
        }

        backup = BackupClass(device_info, "/tmp/results")
        result = backup._validate_mariadb_database()

        assert result is False

    def test_validate_mariadb_database_handles_exception(self):
        """Test _validate_mariadb_database handles exceptions gracefully."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": None,  # Will cause exception when calling .get()
        }

        backup = BackupClass(device_info, "/tmp/results")
        result = backup._validate_mariadb_database()

        assert result is False

    def test_get_mariadb_backup_path_success(self, tmp_path):
        """Test _get_mariadb_backup_path with valid database and path."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {
                "MariaDB": {
                    "ethoscope_db": {
                        "path": "ETHOSCOPE_001/ETHOSCOPE_001_db.db",
                    }
                }
            },
        }

        results_dir = str(tmp_path / "results")
        backup = BackupClass(device_info, results_dir)
        backup_path = backup._get_mariadb_backup_path()

        # Should construct full path from results_dir + path
        expected_path = os.path.join(results_dir, "ETHOSCOPE_001/ETHOSCOPE_001_db.db")
        assert backup_path == expected_path

    def test_get_mariadb_backup_path_no_mariadb(self):
        """Test _get_mariadb_backup_path raises error when no MariaDB."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {},
        }

        backup = BackupClass(device_info, "/tmp/results")

        with pytest.raises(BackupError, match="No MariaDB databases found"):
            backup._get_mariadb_backup_path()

    def test_get_mariadb_backup_path_multiple_databases(self, tmp_path):
        """Test _get_mariadb_backup_path with multiple MariaDB databases."""
        device_info = {
            "id": "device_001",
            "name": "ETHOSCOPE_001",
            "ip": "192.168.1.100",
            "databases": {
                "MariaDB": {
                    "ethoscope_db": {
                        "path": "device/ethoscope_db.db",
                    },
                    "other_db": {
                        "path": "device/other_db.db",
                    },
                }
            },
        }

        results_dir = str(tmp_path / "results")
        backup = BackupClass(device_info, results_dir)
        backup_path = backup._get_mariadb_backup_path()

        # Should return first database's path (dict ordering is preserved in Python 3.7+)
        # The path will be one of the databases, constructed from results_dir + path
        assert "device" in backup_path
        assert backup_path.startswith(results_dir)


class TestGetDeviceBackupInfo:
    """Test get_device_backup_info function."""

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_empty_databases(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test get_device_backup_info with empty databases."""
        mock_fallback.return_value = {}
        mock_enhance.return_value = {}
        mock_sizes.return_value = {
            "results_size": 0,
            "videos_size": 0,
        }

        info = get_device_backup_info("device_001", {})

        assert info["device_id"] == "device_001"
        assert info["backup_status"]["total_databases"] == 0
        assert info["backup_status"]["mysql"]["available"] is False
        assert info["backup_status"]["sqlite"]["available"] is False
        assert info["backup_status"]["video"]["available"] is False
        assert info["recommended_backup_type"] == "none"

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_with_mariadb(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test get_device_backup_info with MariaDB databases."""
        databases = {
            "MariaDB": {
                "ethoscope_db": {
                    "path": "/var/lib/mysql/ethoscope_db",
                    "size": 1024000,
                }
            }
        }

        mock_fallback.return_value = databases
        mock_enhance.return_value = databases
        mock_sizes.return_value = {
            "results_size": 1024000,
            "videos_size": 0,
        }

        info = get_device_backup_info("device_001", databases)

        assert info["backup_status"]["mysql"]["available"] is True
        assert info["backup_status"]["mysql"]["database_count"] == 1
        assert info["backup_status"]["mysql"]["databases"] == ["ethoscope_db"]
        assert info["backup_status"]["mysql"]["total_size_bytes"] == 1024000
        assert info["backup_status"]["total_databases"] == 1
        assert info["recommended_backup_type"] == "mysql"

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_with_sqlite(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test get_device_backup_info with SQLite databases."""
        databases = {
            "SQLite": {
                "results.db": {
                    "path": "/ethoscope_data/results/results.db",
                    "size": 512000,
                }
            }
        }

        mock_fallback.return_value = databases
        mock_enhance.return_value = databases
        mock_sizes.return_value = {
            "results_size": 512000,
            "videos_size": 0,
        }

        info = get_device_backup_info("device_001", databases)

        assert info["backup_status"]["sqlite"]["available"] is True
        assert info["backup_status"]["sqlite"]["database_count"] == 1
        assert info["backup_status"]["sqlite"]["databases"] == ["results.db"]
        assert info["backup_status"]["sqlite"]["total_size_bytes"] == 512000
        assert info["backup_status"]["total_databases"] == 1
        assert info["recommended_backup_type"] == "rsync"

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_with_video(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test get_device_backup_info with video backup."""
        databases = {
            "Video": {
                "video_backup": {
                    "total_files": 10,
                    "total_size_bytes": 10485760,
                    "size_human": "10.0MB",
                    "directory": "/ethoscope_data/videos/device_001",
                }
            }
        }

        mock_fallback.return_value = databases
        mock_enhance.return_value = databases
        mock_sizes.return_value = {
            "results_size": 0,
            "videos_size": 10485760,
        }

        info = get_device_backup_info("device_001", databases)

        assert info["backup_status"]["video"]["available"] is True
        assert info["backup_status"]["video"]["file_count"] == 10
        assert info["backup_status"]["video"]["total_size_bytes"] == 10485760
        assert info["backup_status"]["video"]["size_human"] == "10.0MB"
        assert (
            info["backup_status"]["video"]["directory"]
            == "/ethoscope_data/videos/device_001"
        )

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_mixed_databases(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test get_device_backup_info with mixed database types."""
        databases = {
            "MariaDB": {
                "ethoscope_db": {"path": "/var/lib/mysql/ethoscope_db"},
                "metadata_db": {"path": "/var/lib/mysql/metadata_db"},
            },
            "SQLite": {
                "results.db": {"path": "/ethoscope_data/results/results.db"},
            },
            "Video": {
                "video_backup": {
                    "total_files": 5,
                    "total_size_bytes": 5242880,
                    "size_human": "5.0MB",
                }
            },
        }

        mock_fallback.return_value = databases
        mock_enhance.return_value = databases
        mock_sizes.return_value = {
            "results_size": 2048000,
            "videos_size": 5242880,
        }

        info = get_device_backup_info("device_001", databases)

        assert info["backup_status"]["mysql"]["database_count"] == 2
        assert info["backup_status"]["sqlite"]["database_count"] == 1
        assert info["backup_status"]["total_databases"] == 3
        # MariaDB should be preferred
        assert info["recommended_backup_type"] == "mysql"

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_uses_fallback_discovery(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test that fallback discovery is called when databases are empty."""
        fallback_databases = {
            "SQLite": {"results.db": {"path": "/ethoscope_data/results/results.db"}}
        }

        mock_fallback.return_value = fallback_databases
        mock_enhance.return_value = fallback_databases
        mock_sizes.return_value = {
            "results_size": 1024,
            "videos_size": 0,
        }

        # Call with empty databases
        info = get_device_backup_info("device_001", {})

        # Should have called fallback discovery
        mock_fallback.assert_called_once_with("device_001")
        assert info["backup_status"]["sqlite"]["available"] is True

    @patch("ethoscope_node.backup.helpers._fallback_database_discovery")
    @patch("ethoscope_node.backup.helpers._enhance_databases_with_rsync_info")
    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    def test_get_device_backup_info_invalid_database_structure(
        self, mock_sizes, mock_enhance, mock_fallback
    ):
        """Test handling of invalid database structure."""
        databases = {
            "MariaDB": "not a dict",  # Invalid structure
        }

        mock_fallback.return_value = databases
        mock_enhance.return_value = databases
        mock_sizes.return_value = {
            "results_size": 0,
            "videos_size": 0,
        }

        info = get_device_backup_info("device_001", databases)

        # Should handle gracefully and report no databases
        assert info["backup_status"]["mysql"]["available"] is False
        assert info["backup_status"]["total_databases"] == 0
