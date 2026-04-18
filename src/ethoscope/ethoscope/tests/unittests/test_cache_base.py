"""
Unit tests for BaseDatabaseMetadataCache in io/cache.py.

Tests the abstract base class functionality including cache file operations,
metadata handling, experiment info storage, and cache summary generation.
Complements test_cache.py which tests SQLiteDatabaseMetadataCache.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from ethoscope.io.cache import BaseDatabaseMetadataCache


class ConcreteCacheForTest(BaseDatabaseMetadataCache):
    """Concrete subclass for testing abstract BaseDatabaseMetadataCache."""

    def _query_database(self):
        return {
            "db_version": "3.39.0",
            "db_size_bytes": 1024000,
            "table_counts": {"ROI_1": 100, "ROI_2": 200, "METADATA": 5},
            "last_db_update": time.time(),
        }

    def _get_value_from_database(self, field_name=None):
        values = {
            "machine_name": "TEST_DEVICE",
            "date_time": "1700000000",
            "stop_date_time": None,
            "experimental_info": "{'name': 'test_user', 'location': 'lab1'}",
        }
        return values.get(field_name)


class TestBaseDatabaseMetadataCacheInit(unittest.TestCase):
    """Test cache initialization."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_init_with_device_name(self):
        cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )
        self.assertEqual(cache.device_name, "ETHOSCOPE_001")

    def test_init_auto_detects_device_name(self):
        cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            cache_dir=self.cache_dir,
        )
        self.assertEqual(cache.device_name, "TEST_DEVICE")

    def test_init_creates_cache_dir(self):
        new_dir = os.path.join(self.cache_dir, "subdir", "cache")
        ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=new_dir,
        )
        self.assertTrue(os.path.isdir(new_dir))

    def test_init_no_device_name_raises(self):
        class NoNameCache(BaseDatabaseMetadataCache):
            def _query_database(self):
                return {}

            def _get_value_from_database(self, field_name=None):
                return None

        with self.assertRaises(ValueError):
            NoNameCache(
                db_credentials={"name": "test.db"},
                cache_dir=self.cache_dir,
            )


class TestCacheFilePath(unittest.TestCase):
    """Test _get_cache_file_path."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_with_timestamp(self):
        path = self.cache._get_cache_file_path(1700000000)
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(".json"))
        self.assertIn("ETHOSCOPE_001", path)

    def test_without_timestamp(self):
        path = self.cache._get_cache_file_path(None)
        self.assertIsNone(path)

    def test_without_device_name(self):
        self.cache.device_name = ""
        path = self.cache._get_cache_file_path(1700000000)
        self.assertIsNone(path)


class TestWriteAndReadCache(unittest.TestCase):
    """Test cache write and read operations."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_write_creates_cache_file(self):
        cache_path = self.cache._get_cache_file_path(1700000000)
        db_info = self.cache._query_database()
        self.cache._write_cache(cache_path, db_info, 1700000000)
        self.assertTrue(os.path.exists(cache_path))

    def test_write_and_read_roundtrip(self):
        cache_path = self.cache._get_cache_file_path(1700000000)
        db_info = self.cache._query_database()
        self.cache._write_cache(cache_path, db_info, 1700000000)

        result = self.cache._read_cache_file(cache_path)
        self.assertEqual(result["db_size_bytes"], 1024000)
        self.assertIn("ROI_1", result["table_counts"])

    def test_write_with_experiment_info(self):
        cache_path = self.cache._get_cache_file_path(1700000000)
        exp_info = {
            "date_time": 1700000000,
            "user": "test",
            "backup_filename": "test.db",
        }
        self.cache._write_cache(cache_path, experiment_info=exp_info)
        result = self.cache._read_cache_file(cache_path)
        self.assertEqual(result["experiment_info"]["user"], "test")

    def test_write_finalize(self):
        cache_path = self.cache._get_cache_file_path(1700000000)
        db_info = self.cache._query_database()
        self.cache._write_cache(cache_path, db_info, 1700000000)

        self.cache._write_cache(
            cache_path, finalise=True, graceful=True, stop_reason="user_stop"
        )
        result = self.cache._read_cache_file(cache_path)
        self.assertEqual(result["db_status"], "finalised")

    def test_write_finalize_nonexistent(self):
        cache_path = os.path.join(self.cache_dir, "nonexistent.json")
        self.cache._write_cache(cache_path, finalise=True)
        self.assertFalse(os.path.exists(cache_path))

    def test_read_cache_with_index(self):
        for ts in [1700000000, 1700100000]:
            path = self.cache._get_cache_file_path(ts)
            self.cache._write_cache(path, self.cache._query_database(), ts)
            time.sleep(0.01)

        result = self.cache._read_cache(None, cache_index=0)
        self.assertGreater(result["db_size_bytes"], 0)

    def test_read_cache_out_of_range_index(self):
        path = self.cache._get_cache_file_path(1700000000)
        self.cache._write_cache(path, self.cache._query_database(), 1700000000)

        result = self.cache._read_cache(None, cache_index=99)
        self.assertGreater(result["db_size_bytes"], 0)

    def test_read_cache_no_files(self):
        result = self.cache._read_cache(None)
        self.assertEqual(result["db_size_bytes"], 0)


class TestGetAllCacheFiles(unittest.TestCase):
    """Test _get_all_cache_files."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_empty_directory(self):
        self.assertEqual(self.cache._get_all_cache_files(), [])

    def test_finds_matching_files(self):
        for ts in [1700000000, 1700100000]:
            path = self.cache._get_cache_file_path(ts)
            self.cache._write_cache(path, self.cache._query_database(), ts)

        self.assertEqual(len(self.cache._get_all_cache_files()), 2)

    def test_ignores_non_matching_files(self):
        with open(os.path.join(self.cache_dir, "other.json"), "w") as f:
            json.dump({}, f)

        self.assertEqual(len(self.cache._get_all_cache_files()), 0)


class TestListAndSummary(unittest.TestCase):
    """Test list_cache_files and get_cache_summary."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_list_empty(self):
        self.assertEqual(self.cache.list_cache_files(), [])

    def test_list_with_data(self):
        path = self.cache._get_cache_file_path(1700000000)
        self.cache._write_cache(path, self.cache._query_database(), 1700000000)
        result = self.cache.list_cache_files()
        self.assertEqual(len(result), 1)
        self.assertIn("index", result[0])
        self.assertIn("age_days", result[0])

    def test_summary_empty(self):
        result = self.cache.get_cache_summary()
        self.assertEqual(result["total_files"], 0)

    def test_summary_with_data(self):
        for ts in [1700000000, 1700100000]:
            path = self.cache._get_cache_file_path(ts)
            self.cache._write_cache(path, self.cache._query_database(), ts)

        result = self.cache.get_cache_summary()
        self.assertEqual(result["total_files"], 2)
        self.assertIsNotNone(result["newest_date"])


class TestGetMetadata(unittest.TestCase):
    """Test get_metadata with database and cache fallback."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_from_database(self):
        result = self.cache.get_metadata(tracking_start_time=1700000000)
        self.assertEqual(result["db_size_bytes"], 1024000)

    def test_cache_fallback(self):
        path = self.cache._get_cache_file_path(1700000000)
        self.cache._write_cache(path, self.cache._query_database(), 1700000000)

        with patch.object(
            self.cache, "_query_database", side_effect=Exception("DB down")
        ):
            result = self.cache.get_metadata(tracking_start_time=1700000000)
            self.assertEqual(result["db_size_bytes"], 1024000)


class TestFinalizeAndExperimentInfo(unittest.TestCase):
    """Test finalize_cache, store/get experiment info."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_finalize_clears_current_path(self):
        self.cache.current_cache_file_path = "/some/path"
        self.cache.finalize_cache(1700000000)
        self.assertIsNone(self.cache.current_cache_file_path)

    def test_store_experiment_info_creates_file(self):
        exp_info = {"date_time": 1700000000, "user": "scientist"}
        self.cache.store_experiment_info(1700000000, exp_info)
        # Cache file should exist
        path = self.cache._get_cache_file_path(1700000000)
        self.assertTrue(os.path.exists(path))
        # Read it back and check experiment_info is stored
        data = self.cache._read_cache_file(path)
        self.assertEqual(data["experiment_info"]["user"], "scientist")

    def test_has_last_experiment_info_false_when_empty(self):
        self.assertFalse(self.cache.has_last_experiment_info())

    def test_get_cached_metadata(self):
        path = self.cache._get_cache_file_path(1700000000)
        self.cache._write_cache(path, self.cache._query_database(), 1700000000)
        result = self.cache.get_cached_metadata(cache_index=0)
        self.assertGreater(result["db_size_bytes"], 0)


class TestExperimentalMetadata(unittest.TestCase):
    """Test metadata extraction methods."""

    def setUp(self):
        self.cache_dir = tempfile.mkdtemp()
        self.cache = ConcreteCacheForTest(
            db_credentials={"name": "test.db"},
            device_name="ETHOSCOPE_001",
            cache_dir=self.cache_dir,
        )

    def tearDown(self):
        shutil.rmtree(self.cache_dir)

    def test_get_experimental_metadata(self):
        result = self.cache.get_experimental_metadata()
        self.assertEqual(result["user"], "test_user")
        self.assertEqual(result["location"], "lab1")

    def test_get_database_timestamp(self):
        self.assertEqual(self.cache.get_database_timestamp(), 1700000000.0)

    def test_get_device_name(self):
        self.assertEqual(self.cache.get_device_name(), "TEST_DEVICE")

    def test_create_experiment_info(self):
        result = self.cache.create_experiment_info_from_metadata(
            timestamp=1700000000,
            backup_filename="test.db",
            result_writer_type="SQLiteResultWriter",
        )
        self.assertEqual(result["backup_filename"], "test.db")
        self.assertEqual(result["user"], "test_user")

    def test_create_experiment_info_with_sqlite_path(self):
        result = self.cache.create_experiment_info_from_metadata(
            timestamp=1700000000,
            backup_filename="test.db",
            result_writer_type="SQLiteResultWriter",
            sqlite_source_path="/data/test.db",
        )
        self.assertEqual(result["sqlite_source_path"], "/data/test.db")


if __name__ == "__main__":
    unittest.main()
