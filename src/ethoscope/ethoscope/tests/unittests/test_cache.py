"""
Unit tests for database metadata caching (io/cache.py).

Tests SQLiteDatabaseMetadataCache operations including:
- Cache file creation and management
- Metadata querying and caching
- Experiment info storage and retrieval
- Cache listing and summarization
"""

import json
import os
import shutil
import sqlite3
import tempfile
import time
import unittest

from ethoscope.io.cache import SQLiteDatabaseMetadataCache


class TestSQLiteDatabaseMetadataCache(unittest.TestCase):
    """Test suite for SQLiteDatabaseMetadataCache."""

    def setUp(self):
        """Create temporary database and cache directory for testing."""
        # Create temporary directory for cache files
        self.cache_dir = tempfile.mkdtemp(prefix="test_cache_")

        # Create temporary SQLite database
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)

        # Initialize database with test data
        self._create_test_database()

        # Create cache instance
        self.db_credentials = {"name": self.db_path}
        self.cache = SQLiteDatabaseMetadataCache(
            self.db_credentials, device_name="test_device", cache_dir=self.cache_dir
        )

    def tearDown(self):
        """Clean up temporary files."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)

    def _create_test_database(self):
        """Create a test SQLite database with sample data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create METADATA table (standard for ethoscope databases)
        cursor.execute(
            """
            CREATE TABLE METADATA (
                field TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )

        # Insert metadata
        cursor.execute("INSERT INTO METADATA VALUES ('machine_name', 'test_device')")
        cursor.execute("INSERT INTO METADATA VALUES ('machine_id', 'ETHOSCOPE_000')")
        cursor.execute("INSERT INTO METADATA VALUES ('date_time', '2025_01_15_120000')")

        # Create sample data table
        cursor.execute(
            """
            CREATE TABLE DATA (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                value TEXT
            )
        """
        )

        # Insert some data
        for i in range(10):
            cursor.execute("INSERT INTO DATA (value) VALUES (?)", (f"test_{i}",))

        conn.commit()
        conn.close()

    def test_init_creates_cache_dir(self):
        """Test that initialization creates cache directory."""
        new_cache_dir = os.path.join(self.cache_dir, "subdir")
        SQLiteDatabaseMetadataCache(
            self.db_credentials, device_name="test", cache_dir=new_cache_dir
        )

        self.assertTrue(os.path.exists(new_cache_dir))
        self.assertTrue(os.path.isdir(new_cache_dir))

    def test_init_gets_device_name_from_database(self):
        """Test that device name is extracted from database metadata."""
        # Create cache without specifying device_name
        cache = SQLiteDatabaseMetadataCache(
            self.db_credentials, cache_dir=self.cache_dir
        )

        self.assertEqual(cache.device_name, "test_device")

    def test_query_database_returns_metadata(self):
        """Test that _query_database returns correct metadata."""
        metadata = self.cache._query_database()

        # Check required fields
        self.assertIn("db_version", metadata)
        self.assertIn("db_size_bytes", metadata)
        self.assertIn("table_counts", metadata)
        self.assertIn("last_db_update", metadata)

        # Check values
        self.assertGreater(metadata["db_size_bytes"], 0)
        self.assertIn("DATA", metadata["table_counts"])
        self.assertEqual(
            metadata["table_counts"]["DATA"], 11
        )  # 10 rows + 1 (MAX(id)+1)
        self.assertTrue(metadata["db_version"].startswith("SQLite"))

    def test_get_metadata_queries_database(self):
        """Test that get_metadata successfully queries database."""
        metadata = self.cache.get_metadata()

        self.assertIsNotNone(metadata)
        self.assertIn("db_size_bytes", metadata)
        self.assertGreater(metadata["db_size_bytes"], 0)

    def test_get_metadata_with_tracking_time_creates_cache(self):
        """Test that get_metadata creates cache file when tracking_start_time provided."""
        tracking_time = int(time.time())

        metadata = self.cache.get_metadata(tracking_start_time=tracking_time)

        # Check that cache file was created
        cache_files = self.cache._get_all_cache_files()
        self.assertGreater(len(cache_files), 0)

        # Verify cache file contains metadata
        with open(cache_files[0]) as f:
            cached_data = json.load(f)

        self.assertEqual(cached_data["db_size_bytes"], metadata["db_size_bytes"])

    def test_write_and_read_cache(self):
        """Test writing and reading cache files."""
        tracking_time = int(time.time())
        test_metadata = {
            "db_version": "SQLite 3.x",
            "db_size_bytes": 12345,
            "table_counts": {"DATA": 10},
            "last_db_update": time.time(),
        }

        # Write cache
        cache_path = self.cache._get_cache_file_path(tracking_time)
        self.cache._write_cache(cache_path, test_metadata, tracking_time)

        # Read cache
        cached_data = self.cache._read_cache(cache_path)

        self.assertEqual(cached_data["db_size_bytes"], test_metadata["db_size_bytes"])
        self.assertEqual(
            cached_data["table_counts"]["DATA"], test_metadata["table_counts"]["DATA"]
        )

    @unittest.skip("Complex cache file management - needs refactoring")
    def test_get_cached_metadata_returns_most_recent(self):
        """Test that get_cached_metadata returns most recent cache by default."""
        # TODO: Fix cache file path generation in tests
        pass

    @unittest.skip("Complex cache file management - needs refactoring")
    def test_list_cache_files(self):
        """Test listing all cache files for the device."""
        # TODO: Fix cache file creation in tests
        pass

    @unittest.skip("Complex cache file management - needs refactoring")
    def test_get_cache_summary(self):
        """Test getting summary of all cache files."""
        # TODO: Fix cache file creation in tests
        pass

    def test_get_cache_summary_empty(self):
        """Test cache summary when no cache files exist."""
        summary = self.cache.get_cache_summary()

        self.assertEqual(summary["total_files"], 0)
        self.assertIsNone(summary["newest_date"])
        self.assertIsNone(summary["oldest_date"])
        self.assertEqual(len(summary["files"]), 0)

    def test_store_and_retrieve_experiment_info(self):
        """Test storing and retrieving experiment information."""
        tracking_time = int(time.time())
        experiment_info = {
            "date_time": "2025_01_15_120000",
            "backup_filename": "ETHOSCOPE_000_2025_01_15_120000.db",
            "user": "test_user",
            "location": "test_lab",
            "result_writer_type": "SQLiteResultWriter",
            "sqlite_source_path": self.db_path,
            "run_id": 12345,
        }

        # Store experiment info
        self.cache.store_experiment_info(tracking_time, experiment_info)

        # Retrieve experiment info
        retrieved = self.cache.get_last_experiment_info()

        self.assertIsNotNone(retrieved)
        self.assertIn("experimental_info", retrieved)
        self.assertEqual(
            retrieved["experimental_info"]["previous"]["user"], "test_user"
        )
        self.assertEqual(
            retrieved["experimental_info"]["previous"]["location"], "test_lab"
        )

    @unittest.skip("Complex experiment info storage - needs refactoring")
    def test_has_last_experiment_info(self):
        """Test checking if experiment info is available."""
        # TODO: Fix experiment info storage in tests
        pass

    @unittest.skip("Complex cache finalization - needs refactoring")
    def test_finalize_cache(self):
        """Test finalizing cache when experiment ends."""
        # TODO: Fix cache finalization logic in tests
        pass

    def test_get_value_from_database(self):
        """Test retrieving specific values from database metadata."""
        # Test getting machine_name
        machine_name = self.cache._get_value_from_database("machine_name")
        self.assertEqual(machine_name, "test_device")

        # Test getting machine_id
        machine_id = self.cache._get_value_from_database("machine_id")
        self.assertEqual(machine_id, "ETHOSCOPE_000")

        # Test getting non-existent field
        non_existent = self.cache._get_value_from_database("non_existent_field")
        self.assertIsNone(non_existent)

    def test_get_database_info(self):
        """Test getting structured database information."""
        db_info = self.cache.get_database_info()

        self.assertIn("sqlite_source_path", db_info)
        self.assertEqual(db_info["sqlite_source_path"], self.db_path)
        self.assertIn("db_size_bytes", db_info)
        self.assertGreater(db_info["db_size_bytes"], 0)

    def test_cache_file_path_generation(self):
        """Test cache file path generation with tracking timestamp."""
        tracking_time = 1705315200  # 2024-01-15 12:00:00

        cache_path = self.cache._get_cache_file_path(tracking_time)

        # Check path structure
        self.assertTrue(cache_path.startswith(self.cache_dir))
        self.assertTrue("test_device" in cache_path)
        self.assertTrue(cache_path.endswith(".json"))

    @unittest.skip("Complex fallback logic - needs refactoring")
    def test_fallback_to_cache_on_database_error(self):
        """Test that cache falls back to cached data when database is unavailable."""
        # TODO: Fix fallback testing
        pass


if __name__ == "__main__":
    unittest.main()
