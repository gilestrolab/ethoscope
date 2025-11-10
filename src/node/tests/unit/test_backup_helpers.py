#!/usr/bin/env python3
"""
Unit tests for backup helper functions including file-based cache system.

Tests the enhanced backup functionality with video file caching,
rsync integration, and device backup information extraction.
"""

import json
import os
import pickle
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, mock_open, patch

# Add the source path for imports
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ethoscope_node")
)

from ethoscope_node.backup.helpers import (
    _enhance_databases_with_rsync_info,
    _format_bytes_simple,
    _get_video_cache_path,
    _is_file_older_than_week,
    _load_video_cache,
    _save_video_cache,
    get_device_backup_info,
)


class TestVideoCacheSystem(unittest.TestCase):
    """Test the file-based video cache system."""

    def setUp(self):
        """Set up test environment with temporary directories."""
        self.test_dir = tempfile.mkdtemp()
        self.device_id = "test_device_123"
        self.video_directory = os.path.join(self.test_dir, "videos")
        os.makedirs(self.video_directory, exist_ok=True)

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_get_video_cache_path(self):
        """Test cache path generation."""
        cache_path = _get_video_cache_path(self.device_id, self.video_directory)
        expected_path = os.path.join(
            self.video_directory, ".cache", f"video_cache_{self.device_id}.pkl"
        )

        self.assertEqual(cache_path, expected_path)
        self.assertTrue(os.path.exists(os.path.dirname(cache_path)))

    def test_save_and_load_video_cache(self):
        """Test saving and loading video cache."""
        # Create test video files data
        video_files = {
            "video1.h264": {
                "size_bytes": 1024000,
                "size_human": "1.0 MB",
                "path": "device/video1.h264",
                "status": "backed-up",
                "filesystem_enhanced": True,
            },
            "video2.h264": {
                "size_bytes": 2048000,
                "size_human": "2.0 MB",
                "path": "device/video2.h264",
                "status": "backed-up",
                "cache_hit": False,
            },
        }

        # Save cache
        _save_video_cache(self.device_id, video_files, self.video_directory)

        # Verify cache file exists
        cache_path = _get_video_cache_path(self.device_id, self.video_directory)
        self.assertTrue(os.path.exists(cache_path))

        # Load cache
        loaded_cache = _load_video_cache(self.device_id, self.video_directory)

        # Verify structure
        self.assertIn("files", loaded_cache)
        self.assertIn("timestamp", loaded_cache)
        self.assertEqual(loaded_cache["files"], video_files)
        self.assertIsInstance(loaded_cache["timestamp"], float)

    def test_load_nonexistent_cache(self):
        """Test loading cache when file doesn't exist."""
        loaded_cache = _load_video_cache("nonexistent_device", self.video_directory)

        expected = {"files": {}, "timestamp": 0}
        self.assertEqual(loaded_cache, expected)

    def test_is_file_older_than_week(self):
        """Test file age detection."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "test_file.h264")
        with open(test_file, "w") as f:
            f.write("test")

        # File should be recent (not older than a week)
        self.assertFalse(_is_file_older_than_week(test_file))

        # Modify file time to be older than a week
        old_time = time.time() - (8 * 24 * 60 * 60)  # 8 days ago
        os.utime(test_file, (old_time, old_time))

        # File should now be older than a week
        self.assertTrue(_is_file_older_than_week(test_file))

    def test_is_file_older_than_week_nonexistent(self):
        """Test file age detection for nonexistent file."""
        result = _is_file_older_than_week("/nonexistent/file.h264")
        self.assertFalse(result)


class TestBytesFormatting(unittest.TestCase):
    """Test bytes formatting helper."""

    def test_format_bytes_simple(self):
        """Test simple bytes formatting."""
        test_cases = [
            (0, "0.0 B"),
            (512, "512.0 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1048576, "1.0 MB"),
            (1073741824, "1.0 GB"),
            (1099511627776, "1.0 TB"),
        ]

        for bytes_input, expected in test_cases:
            with self.subTest(bytes_input=bytes_input):
                result = _format_bytes_simple(bytes_input)
                self.assertEqual(result, expected)


class TestRsyncEnhancement(unittest.TestCase):
    """Test rsync service integration and enhancement."""

    def setUp(self):
        """Set up test environment."""
        self.device_id = "test_device_456"
        self.test_dir = tempfile.mkdtemp()
        self.video_directory = os.path.join(self.test_dir, "videos")
        os.makedirs(self.video_directory, exist_ok=True)

        # Create test device directory with h264 files
        device_dir = os.path.join(self.video_directory, self.device_id)
        os.makedirs(device_dir, exist_ok=True)

        # Create test video files
        self.test_files = {
            "video1.h264": 1024000,
            "video2.h264": 2048000,
            "old_video.h264": 512000,
        }

        for filename, size in self.test_files.items():
            file_path = os.path.join(device_dir, filename)
            with open(file_path, "wb") as f:
                f.write(b"0" * size)

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    @patch("urllib.request.urlopen")
    def test_enhance_databases_with_rsync_info_success(
        self, mock_urlopen, mock_get_device_sizes
    ):
        """Test successful rsync enhancement."""
        # Mock device backup sizes
        mock_get_device_sizes.return_value = {
            "videos_size": 3584000,
            "results_size": 0,
            "cache_hit": False,
            "cache_age": 0,
        }

        # Mock rsync service response
        rsync_response = {
            "devices": {
                self.device_id: {
                    "synced": {
                        "videos": {
                            "disk_usage_bytes": 3584000,
                            "disk_usage_human": "3.5 MB",
                            "local_files": 3,
                            "directory": self.video_directory,
                        }
                    }
                }
            }
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(rsync_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Test databases input
        databases = {"Video": {"some_existing_data": "value"}}

        # Run enhancement
        enhanced_db = _enhance_databases_with_rsync_info(self.device_id, databases)

        # Verify enhancement
        self.assertIn("Video", enhanced_db)
        self.assertIn("video_backup", enhanced_db["Video"])

        video_backup = enhanced_db["Video"]["video_backup"]
        self.assertEqual(video_backup["total_files"], 3)
        self.assertEqual(video_backup["total_size_bytes"], 3584000)
        # Size formatting may vary between binary/decimal (3.4 MB vs 3.5 MB)
        self.assertIn("3.", video_backup["size_human"])
        self.assertIn("MB", video_backup["size_human"])
        # Directory includes device_id as subdirectory
        expected_directory = f"{self.video_directory}/{self.device_id}"
        self.assertEqual(video_backup["directory"], expected_directory)

    @patch("urllib.request.urlopen")
    def test_enhance_databases_with_rsync_service_unavailable(self, mock_urlopen):
        """Test enhancement when rsync service is unavailable."""
        # Mock service unavailable
        mock_urlopen.side_effect = Exception("Connection refused")

        original_databases = {"Video": {"existing": "data"}}

        # Run enhancement
        enhanced_db = _enhance_databases_with_rsync_info(
            self.device_id, original_databases
        )

        # Should return original databases unchanged
        self.assertEqual(enhanced_db, original_databases)

    @patch("ethoscope_node.backup.helpers._get_device_backup_sizes_cached")
    @patch("urllib.request.urlopen")
    @patch("glob.glob")
    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_filesystem_fallback_with_cache(
        self, mock_getsize, mock_exists, mock_glob, mock_urlopen, mock_get_device_sizes
    ):
        """Test filesystem fallback with cache utilization."""
        # Mock device backup sizes
        mock_get_device_sizes.return_value = {
            "videos_size": 3584000,
            "results_size": 0,
            "cache_hit": True,
            "cache_age": 3600,
        }

        # Mock rsync service response with minimal video data
        rsync_response = {
            "devices": {
                self.device_id: {
                    "synced": {
                        "videos": {
                            "local_files": 3,  # Indicates files exist but no details
                            "directory": self.video_directory,
                        }
                    }
                }
            }
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(rsync_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Mock filesystem operations
        device_path = os.path.join(self.video_directory, self.device_id)
        h264_files = [
            os.path.join(device_path, "video1.h264"),
            os.path.join(device_path, "video2.h264"),
            os.path.join(device_path, "old_video.h264"),
        ]

        mock_glob.return_value = h264_files
        mock_exists.return_value = True
        mock_getsize.side_effect = lambda path: self.test_files.get(
            os.path.basename(path), 0
        )

        # Mock file modification times
        with patch("os.path.getmtime") as mock_getmtime:
            current_time = time.time()
            mock_getmtime.side_effect = lambda path: {
                h264_files[0]: current_time - 86400,  # 1 day old (recent)
                h264_files[1]: current_time - 86400,  # 1 day old (recent)
                h264_files[2]: current_time - (8 * 24 * 60 * 60),  # 8 days old (old)
            }.get(path, current_time)

            # Pre-populate cache with old file
            cached_files = {
                "old_video.h264": {
                    "size_bytes": 512000,
                    "size_human": "512.0 KB",
                    "path": f"{self.device_id}/old_video.h264",
                    "status": "backed-up",
                    "cache_hit": True,
                }
            }
            _save_video_cache(self.device_id, cached_files, self.video_directory)

            # Test databases input
            databases = {"Video": {}}

            # Run enhancement
            enhanced_db = _enhance_databases_with_rsync_info(self.device_id, databases)

            # Verify video backup section
            self.assertIn("Video", enhanced_db)
            self.assertIn("video_backup", enhanced_db["Video"])

            video_backup = enhanced_db["Video"]["video_backup"]
            self.assertEqual(video_backup["total_files"], 3)
            self.assertIn("files", video_backup)

            files = video_backup["files"]

            # Verify cache hit for old file
            self.assertIn("old_video.h264", files)
            self.assertTrue(files["old_video.h264"].get("cache_hit", False))

            # Verify fresh scan for recent files
            self.assertIn("video1.h264", files)
            self.assertIn("video2.h264", files)
            self.assertFalse(files["video1.h264"].get("cache_hit", True))
            self.assertFalse(files["video2.h264"].get("cache_hit", True))


class TestDeviceBackupInfo(unittest.TestCase):
    """Test device backup information extraction."""

    def setUp(self):
        """Set up test environment."""
        self.device_id = "test_device_789"

    def test_get_device_backup_info_mysql_sqlite(self):
        """Test backup info extraction with MySQL and SQLite databases."""
        databases = {
            "MariaDB": {"ethoscope_db": {"table1": 1000, "table2": 2000}},
            "SQLite": {
                "file1.db": {"path": "/path/to/file1.db", "filesize": 1024000},
                "file2.db": {"path": "/path/to/file2.db", "filesize": 2048000},
            },
        }

        with patch(
            "ethoscope_node.backup.helpers._enhance_databases_with_rsync_info"
        ) as mock_enhance, patch(
            "ethoscope_node.backup.helpers._get_device_backup_sizes_cached"
        ) as mock_get_device_sizes:
            mock_enhance.return_value = databases
            mock_get_device_sizes.return_value = {
                "videos_size": 0,
                "results_size": 3072000,  # 3MB for SQLite files
                "cache_hit": False,
                "cache_age": 0,
            }

            backup_info = get_device_backup_info(self.device_id, databases)

            # Verify structure
            self.assertEqual(backup_info["device_id"], self.device_id)
            self.assertIn("backup_status", backup_info)

            backup_status = backup_info["backup_status"]

            # Verify MySQL status
            self.assertTrue(backup_status["mysql"]["available"])
            self.assertEqual(backup_status["mysql"]["database_count"], 1)
            self.assertEqual(backup_status["mysql"]["databases"], ["ethoscope_db"])

            # Verify SQLite status
            self.assertTrue(backup_status["sqlite"]["available"])
            self.assertEqual(backup_status["sqlite"]["database_count"], 2)
            self.assertEqual(
                set(backup_status["sqlite"]["databases"]), {"file1.db", "file2.db"}
            )

            # Verify totals
            self.assertEqual(backup_status["total_databases"], 3)
            self.assertEqual(backup_info["recommended_backup_type"], "mysql")

    def test_get_device_backup_info_video_only(self):
        """Test backup info extraction with video files only."""
        databases = {
            "Video": {
                "video_backup": {
                    "total_files": 5,
                    "total_size_bytes": 5242880,
                    "size_human": "5.0 MB",
                    "directory": "/ethoscope_data/videos",
                }
            }
        }

        with patch(
            "ethoscope_node.backup.helpers._enhance_databases_with_rsync_info"
        ) as mock_enhance, patch(
            "ethoscope_node.backup.helpers._get_device_backup_sizes_cached"
        ) as mock_get_device_sizes:
            mock_enhance.return_value = databases
            mock_get_device_sizes.return_value = {
                "videos_size": 5242880,  # 5MB for videos
                "results_size": 0,
                "cache_hit": False,
                "cache_age": 0,
            }

            backup_info = get_device_backup_info(self.device_id, databases)

            backup_status = backup_info["backup_status"]

            # Verify MySQL and SQLite not available
            self.assertFalse(backup_status["mysql"]["available"])
            self.assertFalse(backup_status["sqlite"]["available"])

            # Verify video available
            self.assertTrue(backup_status["video"]["available"])
            self.assertEqual(backup_status["video"]["file_count"], 5)
            self.assertEqual(backup_status["video"]["total_size_bytes"], 5242880)
            self.assertEqual(backup_status["video"]["size_human"], "5.0 MB")

            # Should recommend no specific backup type for video-only
            self.assertEqual(backup_info["recommended_backup_type"], "none")

    def test_get_device_backup_info_empty_databases(self):
        """Test backup info extraction with empty databases."""
        databases = {}

        with patch(
            "ethoscope_node.backup.helpers._fallback_database_discovery"
        ) as mock_fallback, patch(
            "ethoscope_node.backup.helpers._enhance_databases_with_rsync_info"
        ) as mock_enhance, patch(
            "ethoscope_node.backup.helpers._get_device_backup_sizes_cached"
        ) as mock_get_device_sizes:
            mock_fallback.return_value = {}
            mock_enhance.return_value = {}
            mock_get_device_sizes.return_value = {
                "videos_size": 0,
                "results_size": 0,
                "cache_hit": False,
                "cache_age": 0,
            }

            backup_info = get_device_backup_info(self.device_id, databases)

            backup_status = backup_info["backup_status"]

            # All should be unavailable
            self.assertFalse(backup_status["mysql"]["available"])
            self.assertFalse(backup_status["sqlite"]["available"])
            self.assertFalse(backup_status["video"]["available"])
            self.assertEqual(backup_status["total_databases"], 0)
            self.assertEqual(backup_info["recommended_backup_type"], "none")


class TestCachePerformance(unittest.TestCase):
    """Test cache performance characteristics."""

    def setUp(self):
        """Set up test environment with large file simulation."""
        self.test_dir = tempfile.mkdtemp()
        self.device_id = "performance_test_device"
        self.video_directory = os.path.join(self.test_dir, "videos")
        os.makedirs(self.video_directory, exist_ok=True)

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    def test_cache_performance_simulation(self):
        """Simulate cache performance with large number of files."""
        # Simulate 1000 video files (similar to production scale but smaller for testing)
        simulated_files = {}

        for i in range(1000):
            filename = f"video_{i:04d}.h264"
            simulated_files[filename] = {
                "size_bytes": 1024000 + (i * 1000),  # Varying sizes
                "size_human": _format_bytes_simple(1024000 + (i * 1000)),
                "path": f"{self.device_id}/{filename}",
                "status": "backed-up",
                "filesystem_enhanced": True,
            }

        # Test cache save performance
        start_time = time.time()
        _save_video_cache(self.device_id, simulated_files, self.video_directory)
        save_time = time.time() - start_time

        # Should be fast (under 1 second for 1000 files)
        self.assertLess(save_time, 1.0, "Cache save should be fast")

        # Test cache load performance
        start_time = time.time()
        loaded_cache = _load_video_cache(self.device_id, self.video_directory)
        load_time = time.time() - start_time

        # Should be fast (under 1 second for 1000 files)
        self.assertLess(load_time, 1.0, "Cache load should be fast")

        # Verify data integrity
        self.assertEqual(len(loaded_cache["files"]), 1000)
        self.assertEqual(loaded_cache["files"], simulated_files)

    def test_cache_file_size(self):
        """Test cache file size for reasonableness."""
        # Create moderate number of files
        simulated_files = {}
        for i in range(100):
            filename = f"video_{i:03d}.h264"
            simulated_files[filename] = {
                "size_bytes": 1024000,
                "size_human": "1.0 MB",
                "path": f"{self.device_id}/{filename}",
                "status": "backed-up",
                "filesystem_enhanced": True,
            }

        _save_video_cache(self.device_id, simulated_files, self.video_directory)

        cache_path = _get_video_cache_path(self.device_id, self.video_directory)
        cache_size = os.path.getsize(cache_path)

        # Cache should be reasonable size (under 1MB for 100 entries)
        self.assertLess(
            cache_size, 1024 * 1024, "Cache file should be reasonably sized"
        )

        # Cache should not be empty
        self.assertGreater(cache_size, 0, "Cache file should not be empty")


if __name__ == "__main__":
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestVideoCacheSystem,
        TestBytesFormatting,
        TestRsyncEnhancement,
        TestDeviceBackupInfo,
        TestCachePerformance,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
