"""
Unit tests for SQLite database writers (io/sqlite.py).

Tests SQLiteResultWriter and AsyncSQLiteWriter operations including:
- Database initialization and connection
- Table creation and data insertion
- Timestamp retrieval from databases
- Error handling and resilience
- Placeholder conversion (MySQL %s to SQLite ?)
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from multiprocessing import Queue
from unittest.mock import Mock, patch

from ethoscope.core.roi import ROI
from ethoscope.io.sqlite import AsyncSQLiteWriter, SQLiteResultWriter


class TestAsyncSQLiteWriter(unittest.TestCase):
    """Test suite for AsyncSQLiteWriter."""

    def setUp(self):
        """Create temporary database file for testing."""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.queue = Mock(spec=Queue)

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_init_stores_db_name(self):
        """Test initialization stores database name."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)
        self.assertEqual(writer._db_name, self.db_path)

    def test_get_connection_succeeds(self):
        """Test _get_connection creates valid connection."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)
        conn = writer._get_connection()

        self.assertIsNotNone(conn)
        self.assertIsInstance(conn, sqlite3.Connection)
        conn.close()

    def test_get_connection_with_invalid_path_raises(self):
        """Test _get_connection raises exception for invalid path."""
        # Use a path that cannot be created (invalid characters on some systems)
        invalid_path = "/invalid/\x00/path.db"
        writer = AsyncSQLiteWriter(invalid_path, self.queue, erase_old_db=False)

        with self.assertRaises((ValueError, sqlite3.Error)):
            writer._get_connection()
        # Note: Error can be ValueError ("embedded null byte") or sqlite3.Error

    def test_initialize_database_erases_old_db(self):
        """Test _initialize_database erases old database when flag set."""
        # Create initial database with data
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        # Initialize with erase flag
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=True)
        writer._initialize_database()

        # Verify database was erased and recreated
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        conn.close()

        # No tables should exist (freshly created database)
        self.assertEqual(len(tables), 0)

    def test_initialize_database_preserves_existing_db(self):
        """Test _initialize_database preserves existing database when flag not set."""
        # Create initial database with data
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        # Initialize without erase flag
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)
        writer._initialize_database()

        # Verify database was preserved
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM test")
        result = cursor.fetchone()
        conn.close()

        self.assertEqual(result[0], 1)

    def test_initialize_database_creates_directory(self):
        """Test _initialize_database creates parent directory if needed."""
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = os.path.join(temp_dir, "subdir", "test.db")

            writer = AsyncSQLiteWriter(db_path, self.queue, erase_old_db=True)
            writer._initialize_database()

            # Verify directory was created
            self.assertTrue(os.path.exists(os.path.dirname(db_path)))
            self.assertTrue(os.path.isdir(os.path.dirname(db_path)))
        finally:
            shutil.rmtree(temp_dir)

    def test_initialize_database_sets_pragmas(self):
        """Test _initialize_database sets SQLite PRAGMAs correctly."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=True)
        writer._initialize_database()

        # Verify PRAGMAs were set
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check some key PRAGMAs
        cursor.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]
        self.assertEqual(journal_mode.upper(), "WAL")

        cursor.execute("PRAGMA synchronous")
        synchronous = cursor.fetchone()[0]
        # synchronous can be 0 (OFF), 1 (NORMAL), 2 (FULL), or 3 (EXTRA)
        # Just verify it was set (not default DELETE)
        self.assertIn(
            str(synchronous), ["0", "1", "2", "3", "OFF", "NORMAL", "FULL", "EXTRA"]
        )

        conn.close()

    def test_get_db_type_name(self):
        """Test _get_db_type_name returns correct string."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)
        self.assertEqual(writer._get_db_type_name(), "SQLite")

    def test_should_retry_on_locked_error(self):
        """Test _should_retry_on_error returns True for locked database."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)

        error = sqlite3.OperationalError("database is locked")
        self.assertTrue(writer._should_retry_on_error(error))

    def test_should_retry_on_busy_error(self):
        """Test _should_retry_on_error returns True for busy database."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)

        error = sqlite3.OperationalError("database is busy")
        self.assertTrue(writer._should_retry_on_error(error))

    def test_should_not_retry_on_critical_error(self):
        """Test _should_retry_on_error returns False for critical errors."""
        writer = AsyncSQLiteWriter(self.db_path, self.queue, erase_old_db=False)

        # Test various critical errors
        error = sqlite3.DatabaseError("database disk image is malformed")
        self.assertFalse(writer._should_retry_on_error(error))

        error = sqlite3.IntegrityError("UNIQUE constraint failed")
        self.assertFalse(writer._should_retry_on_error(error))

        error = Exception("some other error")
        self.assertFalse(writer._should_retry_on_error(error))


class TestSQLiteResultWriter(unittest.TestCase):
    """Test suite for SQLiteResultWriter."""

    def setUp(self):
        """Create temporary database and mock objects for testing."""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)

        self.db_credentials = {"name": self.db_path}

        # Create mock ROIs
        self.rois = [
            ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1),
            ROI(polygon=((100, 0), (200, 0), (200, 100), (100, 100)), idx=2, value=2),
        ]

        self.metadata = {
            "machine_name": "test_device",
            "machine_id": "TEST_001",
            "date_time": "2025_01_15_120000",
        }

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_init_creates_writer(self):
        """Test initialization creates writer instance."""
        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        self.assertIsNotNone(writer)
        self.assertEqual(len(writer._rois), 2)

    def test_get_last_timestamp_with_missing_database(self):
        """Test get_last_timestamp returns 0 for missing database."""
        # Remove database file
        os.remove(self.db_path)

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        result = writer.get_last_timestamp()
        self.assertEqual(result, 0)

    def test_get_last_timestamp_with_empty_database(self):
        """Test get_last_timestamp returns 0 for empty database."""
        # Create empty database file
        open(self.db_path, "w").close()

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        result = writer.get_last_timestamp()
        self.assertEqual(result, 0)

    def test_get_last_timestamp_with_no_roi_tables(self):
        """Test get_last_timestamp returns 0 when no ROI tables exist."""
        # Create database with no ROI tables
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE METADATA (field TEXT, value TEXT)")
        conn.commit()
        conn.close()

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        result = writer.get_last_timestamp()
        self.assertEqual(result, 0)

    def test_get_last_timestamp_with_empty_roi_tables(self):
        """Test get_last_timestamp returns 0 when ROI tables are empty."""
        # Create database with empty ROI tables
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY, t INTEGER)")
        conn.execute("CREATE TABLE ROI_2 (id INTEGER PRIMARY KEY, t INTEGER)")
        conn.commit()
        conn.close()

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        result = writer.get_last_timestamp()
        self.assertEqual(result, 0)

    def test_get_last_timestamp_with_data(self):
        """Test get_last_timestamp returns maximum timestamp from ROI tables."""
        # Create database with ROI tables and data
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY, t INTEGER)")
        conn.execute("CREATE TABLE ROI_2 (id INTEGER PRIMARY KEY, t INTEGER)")

        # Insert timestamps (ROI_2 has the maximum)
        conn.execute("INSERT INTO ROI_1 (t) VALUES (1000)")
        conn.execute("INSERT INTO ROI_1 (t) VALUES (2000)")
        conn.execute("INSERT INTO ROI_2 (t) VALUES (1500)")
        conn.execute("INSERT INTO ROI_2 (t) VALUES (3000)")

        conn.commit()
        conn.close()

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        result = writer.get_last_timestamp()
        self.assertEqual(result, 3000)

    def test_get_last_timestamp_with_missing_roi_table(self):
        """Test get_last_timestamp handles missing ROI table gracefully."""
        # Create database with only one ROI table
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY, t INTEGER)")
        conn.execute("INSERT INTO ROI_1 (t) VALUES (1000)")
        # ROI_2 is missing
        conn.commit()
        conn.close()

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        result = writer.get_last_timestamp()
        self.assertEqual(result, 1000)

    def test_get_last_timestamp_with_corrupted_table(self):
        """Test get_last_timestamp handles corrupted table structure."""
        # Create database with ROI table missing 't' column
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE ROI_1 (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE ROI_2 (id INTEGER PRIMARY KEY, t INTEGER)")
        conn.execute("INSERT INTO ROI_2 (t) VALUES (2000)")
        conn.commit()
        conn.close()

        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        # Should return timestamp from valid table only
        result = writer.get_last_timestamp()
        self.assertEqual(result, 2000)

    def test_write_async_command_converts_placeholders(self):
        """Test _write_async_command converts MySQL placeholders to SQLite."""
        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        # Mock the parent method to capture converted command
        with patch.object(
            writer, "_write_async_command_resilient", return_value=True
        ) as mock_write:
            mysql_command = "INSERT INTO test VALUES (%s, %s, %s)"
            args = (1, "test", 3.14)

            writer._write_async_command(mysql_command, args)

            # Verify placeholder conversion
            called_command = mock_write.call_args[0][0]
            self.assertEqual(called_command, "INSERT INTO test VALUES (?, ?, ?)")
            self.assertEqual(mock_write.call_args[0][1], args)

    def test_write_async_command_handles_no_args(self):
        """Test _write_async_command works without arguments."""
        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        with patch.object(
            writer, "_write_async_command_resilient", return_value=True
        ) as mock_write:
            command = "CREATE TABLE test (id INTEGER)"

            writer._write_async_command(command)

            self.assertEqual(mock_write.call_args[0][0], command)
            self.assertIsNone(mock_write.call_args[0][1])

    def test_create_table(self):
        """Test _create_table creates table correctly."""
        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        with patch.object(writer, "_write_async_command") as mock_write:
            writer._create_table("test_table", "id INTEGER, name TEXT")

            # Verify CREATE TABLE command was sent
            call_args = mock_write.call_args[0]
            self.assertIn("CREATE TABLE IF NOT EXISTS test_table", call_args[0])
            self.assertIn("id INTEGER, name TEXT", call_args[0])

    def test_initialise_roi_table_converts_types(self):
        """Test _initialise_roi_table converts MySQL types to SQLite."""
        writer = SQLiteResultWriter(
            self.db_credentials,
            self.rois,
            metadata=self.metadata,
            erase_old_db=False,
        )

        # Create mock variable classes with different SQL types
        from ethoscope.core.variables import BaseIntVariable

        class XVariable(BaseIntVariable):
            header_name = "x"
            sql_data_type = "SMALLINT"
            functional_type = "distance"

        class YVariable(BaseIntVariable):
            header_name = "y"
            sql_data_type = "DOUBLE"
            functional_type = "distance"

        class LabelVariable(BaseIntVariable):
            header_name = "label"
            sql_data_type = "VARCHAR(100)"
            functional_type = "label"

        # Create data row matching the expected format
        data_row = {
            "x": XVariable(10),
            "y": YVariable(20),
            "label": LabelVariable(1),
        }

        with patch.object(writer, "_create_table") as mock_create:
            writer._initialise_roi_table(self.rois[0], data_row)

            # Verify type conversions
            call_args = mock_create.call_args[0]
            table_name = call_args[0]
            fields = call_args[1]

            self.assertEqual(table_name, "ROI_1")
            self.assertIn("INTEGER PRIMARY KEY AUTOINCREMENT", fields)
            self.assertIn("t INTEGER", fields)
            self.assertIn("x INTEGER", fields)
            self.assertIn("y REAL", fields)
            self.assertIn("label TEXT", fields)


if __name__ == "__main__":
    unittest.main()
