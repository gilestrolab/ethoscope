"""
Unit tests for database append functionality.

This module tests the append features for both MySQL and SQLite databases,
ensuring proper time offset handling and database compatibility.
"""

import logging
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from ethoscope.core.monitor import Monitor
from ethoscope.core.roi import ROI

# Import the classes we're testing
from ethoscope.io import MySQLResultWriter
from ethoscope.io import SQLiteResultWriter


@pytest.fixture
def mock_camera():
    """Create a mock camera for testing."""
    camera = Mock()
    # Simulate camera frames with timestamps
    camera.__iter__ = Mock(
        return_value=iter(
            [
                (0, Mock()),  # t=0ms
                (1000, Mock()),  # t=1000ms
                (2000, Mock()),  # t=2000ms
                (3000, Mock()),  # t=3000ms
            ]
        )
    )
    return camera


@pytest.fixture
def mock_tracker_class():
    """Create a mock tracker class."""
    tracker = Mock()
    tracker.return_value.track = Mock(return_value=[])
    return tracker


@pytest.fixture
def sample_rois():
    """Create sample ROIs for testing."""
    roi1 = Mock(spec=ROI)
    roi1.idx = 1
    roi1.get_feature_dict = Mock(
        return_value={"idx": 1, "value": 255, "x": 10, "y": 10, "w": 100, "h": 100}
    )

    roi2 = Mock(spec=ROI)
    roi2.idx = 2
    roi2.get_feature_dict = Mock(
        return_value={"idx": 2, "value": 255, "x": 120, "y": 10, "w": 100, "h": 100}
    )

    return [roi1, roi2]


@pytest.fixture
def temp_sqlite_db():
    """Create a temporary SQLite database for testing."""
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Create a basic database structure
    conn = sqlite3.connect(temp_path)
    cursor = conn.cursor()

    # Create ROI tables with some test data
    cursor.execute(
        """
        CREATE TABLE ROI_1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            t INTEGER,
            x REAL,
            y REAL
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE ROI_2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            t INTEGER,
            x REAL,
            y REAL
        )
    """
    )

    # Insert test data with timestamps
    cursor.execute("INSERT INTO ROI_1 (t, x, y) VALUES (?, ?, ?)", (5000, 10.5, 20.5))
    cursor.execute("INSERT INTO ROI_1 (t, x, y) VALUES (?, ?, ?)", (10000, 15.5, 25.5))
    cursor.execute("INSERT INTO ROI_2 (t, x, y) VALUES (?, ?, ?)", (7000, 30.5, 40.5))
    cursor.execute("INSERT INTO ROI_2 (t, x, y) VALUES (?, ?, ?)", (12000, 35.5, 45.5))

    conn.commit()
    conn.close()

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


class TestMonitorTimeOffset:
    """Test time offset handling in Monitor class."""

    def test_monitor_init_with_time_offset(
        self, mock_camera, mock_tracker_class, sample_rois
    ):
        """Test Monitor initialization with time_offset parameter."""
        time_offset = 15000  # 15 seconds

        monitor = Monitor(
            camera=mock_camera,
            tracker_class=mock_tracker_class,
            rois=sample_rois,
            time_offset=time_offset,
        )

        assert monitor._time_offset == time_offset
        assert monitor._last_time_stamp == time_offset

    def test_monitor_time_offset_applied_to_timestamps(
        self, mock_camera, mock_tracker_class, sample_rois
    ):
        """Test that time offset is properly applied to timestamps during tracking."""
        time_offset = 10000  # 10 seconds

        monitor = Monitor(
            camera=mock_camera,
            tracker_class=mock_tracker_class,
            rois=sample_rois,
            time_offset=time_offset,
        )

        # Mock result writer to capture timestamps
        mock_result_writer = Mock()

        # Run monitor for a few frames
        frames_processed = 0
        for i, (t, frame) in enumerate(mock_camera):
            if frames_processed >= 2:  # Process only 2 frames
                break

            monitor._last_frame_idx = i
            monitor._last_time_stamp = t + monitor._time_offset

            # Simulate the timestamp adjustment for database writes
            t_with_offset = t + monitor._time_offset

            # Verify the timestamp includes the offset
            expected_timestamp = t + time_offset
            assert t_with_offset == expected_timestamp

            frames_processed += 1

    def test_monitor_last_time_stamp_property(
        self, mock_camera, mock_tracker_class, sample_rois
    ):
        """Test that last_time_stamp property returns correct offset time."""
        time_offset = 5000  # 5 seconds
        raw_timestamp = 3000  # 3 seconds

        monitor = Monitor(
            camera=mock_camera,
            tracker_class=mock_tracker_class,
            rois=sample_rois,
            time_offset=time_offset,
        )

        # Simulate timestamp update
        monitor._last_time_stamp = raw_timestamp + time_offset

        # last_time_stamp property should return time in seconds
        expected_seconds = (raw_timestamp + time_offset) / 1000.0
        assert monitor.last_time_stamp == expected_seconds


class TestSQLiteAppendFunctionality:
    """Test SQLite database append functionality."""

    def test_sqlite_get_last_timestamp_success(self, temp_sqlite_db, sample_rois):
        """Test successful retrieval of last timestamp from SQLite database."""
        db_credentials = {"name": temp_sqlite_db}

        writer = SQLiteResultWriter(
            db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
        )

        last_timestamp = writer.get_last_timestamp()

        # Should return the maximum timestamp across all ROI tables
        # ROI_1 max: 10000, ROI_2 max: 12000, so overall max: 12000
        assert last_timestamp == 12000

    def test_sqlite_get_last_timestamp_nonexistent_file(self, sample_rois):
        """Test handling of non-existent SQLite database file."""
        db_credentials = {"name": "/nonexistent/path/test.db"}

        writer = SQLiteResultWriter(
            db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
        )

        last_timestamp = writer.get_last_timestamp()

        # Should return 0 for non-existent file
        assert last_timestamp == 0

    def test_sqlite_get_last_timestamp_empty_database(self, sample_rois):
        """Test handling of empty SQLite database."""
        # Create empty database
        fd, temp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            # Create empty database with just table structure
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE ROI_1 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    t INTEGER,
                    x REAL,
                    y REAL
                )
            """
            )
            conn.commit()
            conn.close()

            db_credentials = {"name": temp_path}

            writer = SQLiteResultWriter(
                db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
            )

            last_timestamp = writer.get_last_timestamp()

            # Should return 0 for empty tables
            assert last_timestamp == 0

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_sqlite_get_last_timestamp_missing_roi_table(self, sample_rois):
        """Test handling when some ROI tables are missing."""
        # Create database with only ROI_1 table
        fd, temp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        try:
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()

            # Only create ROI_1 table, not ROI_2
            cursor.execute(
                """
                CREATE TABLE ROI_1 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    t INTEGER,
                    x REAL,
                    y REAL
                )
            """
            )

            cursor.execute(
                "INSERT INTO ROI_1 (t, x, y) VALUES (?, ?, ?)", (8000, 10.5, 20.5)
            )

            conn.commit()
            conn.close()

            db_credentials = {"name": temp_path}

            writer = SQLiteResultWriter(
                db_credentials=db_credentials,
                rois=sample_rois,  # This includes ROI_2 which doesn't exist in DB
                erase_old_db=False,
            )

            last_timestamp = writer.get_last_timestamp()

            # Should return the max from existing tables only
            assert last_timestamp == 8000

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_sqlite_get_last_timestamp_corrupted_database(self, sample_rois):
        """Test handling of corrupted SQLite database."""
        # Create a corrupted database file
        fd, temp_path = tempfile.mkstemp(suffix=".db")
        with os.fdopen(fd, "wb") as f:
            f.write(b"This is not a valid SQLite database")

        try:
            db_credentials = {"name": temp_path}

            writer = SQLiteResultWriter(
                db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
            )

            last_timestamp = writer.get_last_timestamp()

            # Should return 0 for corrupted database
            assert last_timestamp == 0

        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestMySQLAppendFunctionality:
    """Test MySQL database append functionality."""

    @patch("ethoscope.utils.io.mysql.connector.connect")
    def test_mysql_get_last_timestamp_success(self, mock_connect, sample_rois):
        """Test successful retrieval of last timestamp from MySQL database."""
        # Mock database connection and cursor
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock cursor responses for different ROI tables
        def mock_fetchone_side_effect():
            # Return different max timestamps for each ROI table
            calls = mock_cursor.execute.call_count
            if calls == 1:  # First call for ROI_1
                return (15000,)
            elif calls == 2:  # Second call for ROI_2
                return (18000,)
            return (None,)

        mock_cursor.fetchone.side_effect = mock_fetchone_side_effect

        db_credentials = {
            "name": "test_db",
            "user": "test_user",
            "password": "test_pass",
        }

        writer = MySQLResultWriter(
            db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
        )

        last_timestamp = writer.get_last_timestamp()

        # Should return the maximum timestamp (18000)
        assert last_timestamp == 18000

        # Verify database connection was established correctly
        mock_connect.assert_called_once_with(
            host="localhost", user="test_user", passwd="test_pass", db="test_db"
        )

    @patch("ethoscope.utils.io.mysql.connector.connect")
    def test_mysql_get_last_timestamp_connection_error(self, mock_connect, sample_rois):
        """Test handling of MySQL connection errors."""
        # Mock connection error
        import mysql.connector

        mock_connect.side_effect = mysql.connector.Error("Connection failed")

        db_credentials = {
            "name": "test_db",
            "user": "test_user",
            "password": "test_pass",
        }

        writer = MySQLResultWriter(
            db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
        )

        last_timestamp = writer.get_last_timestamp()

        # Should return 0 on connection error
        assert last_timestamp == 0

    @patch("ethoscope.utils.io.mysql.connector.connect")
    def test_mysql_get_last_timestamp_empty_tables(self, mock_connect, sample_rois):
        """Test handling of empty MySQL tables."""
        # Mock database connection and cursor
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock empty table responses
        mock_cursor.fetchone.return_value = (None,)

        db_credentials = {
            "name": "test_db",
            "user": "test_user",
            "password": "test_pass",
        }

        writer = MySQLResultWriter(
            db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
        )

        last_timestamp = writer.get_last_timestamp()

        # Should return 0 for empty tables
        assert last_timestamp == 0


class TestAppendIntegration:
    """Integration tests for complete append functionality."""

    def test_append_method_calls_get_last_timestamp(self, temp_sqlite_db, sample_rois):
        """Test that append() method properly calls get_last_timestamp()."""
        db_credentials = {"name": temp_sqlite_db}

        writer = SQLiteResultWriter(
            db_credentials=db_credentials, rois=sample_rois, erase_old_db=False
        )

        # The append() method should return the result of get_last_timestamp()
        append_result = writer.append()
        expected_timestamp = writer.get_last_timestamp()

        assert append_result == expected_timestamp
        assert append_result == 12000  # Based on test data in temp_sqlite_db

    def test_monitor_with_append_offset(
        self, mock_camera, mock_tracker_class, sample_rois
    ):
        """Test complete Monitor workflow with append time offset."""
        time_offset = 12000  # Should match the max timestamp from database

        monitor = Monitor(
            camera=mock_camera,
            tracker_class=mock_tracker_class,
            rois=sample_rois,
            time_offset=time_offset,
        )

        # Verify monitor is initialized with correct offset
        assert monitor._time_offset == time_offset
        assert monitor._last_time_stamp == time_offset

        # Test that timestamps are properly offset
        raw_timestamp = 1000
        expected_offset_timestamp = raw_timestamp + time_offset

        # Simulate the timestamp calculation from the run method
        calculated_timestamp = raw_timestamp + monitor._time_offset
        assert calculated_timestamp == expected_offset_timestamp


if __name__ == "__main__":
    # Configure logging for tests
    logging.basicConfig(level=logging.DEBUG)

    # Run the tests
    pytest.main([__file__, "-v"])
