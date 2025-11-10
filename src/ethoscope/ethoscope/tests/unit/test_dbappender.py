"""
# flake8: noqa: E402, F811
Test suite for dbAppender meta-class functionality.

This module tests the dbAppender meta-class which provides unified interface
for appending to both SQLite and MySQL databases with automatic type detection.
"""

import json
import logging
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

# Configure logging for tests
logging.basicConfig(level=logging.INFO)

# Mock imports to avoid hardware dependencies during testing
import sys

sys.path.insert(0, "/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope")

# Import the actual classes we're testing
from ethoscope.io import MySQLResultWriter, SQLiteResultWriter, dbAppender


class TestDbAppender(unittest.TestCase):
    """Test cases for dbAppender meta-class functionality."""

    def setUp(self):
        """Set up test fixtures for each test case."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = os.path.join(self.temp_dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

        # Create mock ROIs
        self.rois = [
            Mock(idx=0, polygon=[(0, 0), (100, 0), (100, 100), (0, 100)]),
            Mock(idx=1, polygon=[(100, 0), (200, 0), (200, 100), (100, 100)]),
        ]

        # Create mock metadata
        self.metadata = {
            "machine_name": "TEST_MACHINE",
            "machine_id": "test_id_123",
            "experimental_info": {
                "name": "test_experiment",
                "location": "test_lab",
                "code": "test_code_001",
            },
        }

        # Mock database credentials
        self.sqlite_credentials = {
            "name": os.path.join(self.temp_dir, "test_database.db")
        }

        self.mysql_credentials = {
            "user": "test_user",
            "password": "test_password",
            "host": "localhost",
            "db_name": "test_database",
        }

    def tearDown(self):
        """Clean up test fixtures after each test case."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_init_requires_database_to_append(self):
        """Test that dbAppender requires database_to_append parameter."""
        with self.assertRaises(ValueError) as context:
            dbAppender(
                db_credentials=self.sqlite_credentials,
                rois=self.rois,
                metadata=self.metadata,
                database_to_append="",  # Empty string should raise error
            )

        self.assertIn(
            "database_to_append parameter is required", str(context.exception)
        )

    @patch("ethoscope.utils.io.SQLiteResultWriter")
    def test_detect_sqlite_by_extension(self, mock_sqlite_writer):
        """Test that SQLite databases are detected by file extension."""
        # Create a mock SQLite file
        test_db_path = os.path.join(self.temp_dir, "test.db")
        with open(test_db_path, "wb") as f:
            f.write(b"SQLite format 3\x00")  # SQLite file header

        mock_writer_instance = Mock()
        mock_sqlite_writer.return_value = mock_writer_instance

        # Mock the path finding to return the test path
        with patch.object(
            dbAppender, "_find_sqlite_database_path", return_value=test_db_path
        ):
            appender = dbAppender(
                db_credentials=self.sqlite_credentials,
                rois=self.rois,
                metadata=self.metadata,
                database_to_append="test.db",
            )

        # Verify SQLite writer was created
        mock_sqlite_writer.assert_called_once()
        self.assertEqual(appender._writer, mock_writer_instance)

    @patch("ethoscope.utils.io.MySQLResultWriter")
    def test_detect_mysql_by_name_pattern(self, mock_mysql_writer):
        """Test that MySQL databases are detected by name patterns."""
        mock_writer_instance = Mock()
        mock_mysql_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.mysql_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="experiment_001",  # No file extension, assume MySQL
        )

        # Verify MySQL writer was created
        mock_mysql_writer.assert_called_once()
        self.assertEqual(appender._writer, mock_writer_instance)

    @patch("ethoscope.utils.cache.get_all_databases_info")
    @patch("ethoscope.utils.io.SQLiteResultWriter")
    def test_detect_sqlite_from_cache(self, mock_sqlite_writer, mock_get_db_info):
        """Test SQLite detection using cache information."""
        # Mock cache information
        mock_get_db_info.return_value = {
            "SQLite": {
                "test_experiment": {
                    "file_exists": True,
                    "filesize": 1024000,
                    "path": "/ethoscope_data/results/test_experiment.db",
                }
            },
            "MariaDB": {},
        }

        mock_writer_instance = Mock()
        mock_sqlite_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.sqlite_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="test_experiment",
        )

        # Verify SQLite writer was created
        mock_sqlite_writer.assert_called_once()
        self.assertEqual(appender._writer, mock_writer_instance)

    @patch("ethoscope.utils.cache.get_all_databases_info")
    @patch("ethoscope.utils.io.MySQLResultWriter")
    def test_detect_mysql_from_cache(self, mock_mysql_writer, mock_get_db_info):
        """Test MySQL detection using cache information."""
        # Mock cache information
        mock_get_db_info.return_value = {
            "SQLite": {},
            "MariaDB": {
                "test_experiment": {
                    "db_size_bytes": 2048000,
                    "backup_filename": "test_experiment",
                    "db_status": "active",
                }
            },
        }

        mock_writer_instance = Mock()
        mock_mysql_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.mysql_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="test_experiment",
        )

        # Verify MySQL writer was created
        mock_mysql_writer.assert_called_once()
        self.assertEqual(appender._writer, mock_writer_instance)

    @patch("ethoscope.utils.io.SQLiteResultWriter")
    def test_sqlite_writer_created_with_correct_parameters(self, mock_sqlite_writer):
        """Test that SQLite writer is created with correct parameters."""
        test_db_path = os.path.join(self.temp_dir, "test.db")
        with open(test_db_path, "wb") as f:
            f.write(b"SQLite format 3\x00")

        mock_writer_instance = Mock()
        mock_sqlite_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.sqlite_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="test.db",
            make_dam_like_table=True,
            take_frame_shots=False,
        )

        # Verify SQLite writer was called with correct parameters
        call_args = mock_sqlite_writer.call_args
        self.assertEqual(call_args[1]["rois"], self.rois)
        self.assertEqual(call_args[1]["metadata"], self.metadata)
        self.assertEqual(call_args[1]["make_dam_like_table"], True)
        self.assertEqual(call_args[1]["take_frame_shots"], False)
        self.assertEqual(
            call_args[1]["erase_old_db"], False
        )  # Key for append functionality

    @patch("ethoscope.utils.io.MySQLResultWriter")
    def test_mysql_writer_created_with_correct_parameters(self, mock_mysql_writer):
        """Test that MySQL writer is created with correct parameters."""
        mock_writer_instance = Mock()
        mock_mysql_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.mysql_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="test_experiment",
            make_dam_like_table=False,
            take_frame_shots=True,
            db_host="test_host",
        )

        # Verify MySQL writer was called with correct parameters
        call_args = mock_mysql_writer.call_args
        self.assertEqual(call_args[1]["rois"], self.rois)
        self.assertEqual(call_args[1]["metadata"], self.metadata)
        self.assertEqual(call_args[1]["make_dam_like_table"], False)
        self.assertEqual(call_args[1]["take_frame_shots"], True)
        self.assertEqual(
            call_args[1]["erase_old_db"], False
        )  # Key for append functionality
        self.assertEqual(call_args[1]["db_host"], "test_host")

    def test_sqlite_database_path_finding(self):
        """Test SQLite database path resolution."""
        # Create a test database file
        test_db_path = os.path.join(self.temp_dir, "results", "test_database.db")
        os.makedirs(os.path.dirname(test_db_path), exist_ok=True)
        with open(test_db_path, "wb") as f:
            f.write(b"SQLite format 3\x00")

        # Mock the path resolution in dbAppender
        with patch("ethoscope.utils.io.SQLiteResultWriter") as mock_sqlite_writer:
            mock_writer_instance = Mock()
            mock_sqlite_writer.return_value = mock_writer_instance

            # Update credentials to point to temp directory structure
            credentials = {
                "name": os.path.join(self.temp_dir, "results", "test_database.db")
            }

            appender = dbAppender(
                db_credentials=credentials,
                rois=self.rois,
                metadata=self.metadata,
                database_to_append="test_database.db",
            )

            # Verify path was resolved correctly
            call_args = mock_sqlite_writer.call_args
            db_creds = call_args[0][0]  # First positional argument
            self.assertEqual(db_creds["name"], test_db_path)

    @patch("ethoscope.utils.cache.get_all_databases_info")
    def test_get_available_databases_class_method(self, mock_get_db_info):
        """Test the class method for getting available databases."""
        # Mock comprehensive database information
        mock_get_db_info.return_value = {
            "SQLite": {
                "experiment_001": {
                    "file_exists": True,
                    "filesize": 1024000,
                    "path": "/ethoscope_data/results/experiment_001.db",
                    "db_status": "completed",
                },
                "experiment_002": {
                    "file_exists": True,
                    "filesize": 2048000,
                    "path": "/ethoscope_data/results/experiment_002.db",
                    "db_status": "active",
                },
                "small_experiment": {
                    "file_exists": True,
                    "filesize": 1000,  # Too small, should be excluded
                    "path": "/ethoscope_data/results/small_experiment.db",
                    "db_status": "empty",
                },
            },
            "MariaDB": {
                "mysql_experiment": {
                    "db_size_bytes": 5000000,
                    "backup_filename": "mysql_experiment",
                    "db_status": "active",
                }
            },
        }

        db_list = dbAppender.get_available_databases(
            db_credentials=self.sqlite_credentials, device_name="TEST_DEVICE"
        )

        # Should have 3 databases (2 SQLite + 1 MySQL, excluding small one)
        self.assertEqual(len(db_list), 3)

        # Check SQLite databases
        sqlite_dbs = [db for db in db_list if db["type"] == "SQLite"]
        self.assertEqual(len(sqlite_dbs), 2)

        # Check MySQL databases
        mysql_dbs = [db for db in db_list if db["type"] == "MySQL"]
        self.assertEqual(len(mysql_dbs), 1)

        # Verify structure of returned databases
        for db in db_list:
            self.assertIn("name", db)
            self.assertIn("type", db)
            self.assertIn("active", db)
            self.assertIn("size", db)
            self.assertIn("status", db)

    @patch("ethoscope.utils.io.SQLiteResultWriter")
    def test_method_delegation(self, mock_sqlite_writer):
        """Test that methods are properly delegated to the wrapped writer."""
        mock_writer_instance = Mock()
        mock_writer_instance.write.return_value = "test_result"
        mock_sqlite_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.sqlite_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="test.db",
        )

        # Test method delegation
        result = appender.write("test_data")
        self.assertEqual(result, "test_result")
        mock_writer_instance.write.assert_called_once_with("test_data")

    @patch("ethoscope.utils.io.SQLiteResultWriter")
    def test_context_manager_support(self, mock_sqlite_writer):
        """Test that dbAppender works as a context manager."""
        mock_writer_instance = Mock()
        mock_sqlite_writer.return_value = mock_writer_instance

        appender = dbAppender(
            db_credentials=self.sqlite_credentials,
            rois=self.rois,
            metadata=self.metadata,
            database_to_append="test.db",
        )

        # Test context manager usage
        with appender as writer:
            self.assertEqual(writer, mock_writer_instance)

        # Verify enter and exit were called
        mock_writer_instance.__enter__.assert_called_once()
        mock_writer_instance.__exit__.assert_called_once()

    def test_database_type_detection_edge_cases(self):
        """Test edge cases in database type detection."""
        with patch("ethoscope.utils.io.MySQLResultWriter") as mock_mysql_writer:
            mock_writer_instance = Mock()
            mock_mysql_writer.return_value = mock_writer_instance

            # Test detection failure
            with self.assertRaises(ValueError) as context:
                dbAppender(
                    db_credentials=self.sqlite_credentials,
                    rois=self.rois,
                    metadata=self.metadata,
                    database_to_append="/path/to/nonexistent/file.unknown",
                )

            self.assertIn("Could not detect database type", str(context.exception))


if __name__ == "__main__":
    # Run the test suite
    unittest.main(verbosity=2)
