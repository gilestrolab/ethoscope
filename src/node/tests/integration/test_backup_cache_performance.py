#!/usr/bin/env python3
"""
Performance tests for the backup system file-based cache.

Tests the performance characteristics of the video file cache system
with realistic production-scale data (10,000+ files).
"""

import unittest
import tempfile
import shutil
import os
import time
import sys
from unittest.mock import patch, MagicMock

# Add the source path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ethoscope_node'))

from ethoscope_node.backup.helpers import (
    _save_video_cache,
    _load_video_cache,
    _enhance_databases_with_rsync_info,
    _format_bytes_simple
)


class TestCachePerformanceRealistic(unittest.TestCase):
    """Performance tests with realistic production scale."""
    
    def setUp(self):
        """Set up test environment with large-scale simulation."""
        self.test_dir = tempfile.mkdtemp()
        self.device_id = "performance_device_001"
        self.video_directory = os.path.join(self.test_dir, "videos")
        os.makedirs(self.video_directory, exist_ok=True)
        
        # Create device directory structure
        self.device_dir = os.path.join(self.video_directory, self.device_id)
        os.makedirs(self.device_dir, exist_ok=True)
        
        # Performance tracking
        self.performance_metrics = {}
    
    def tearDown(self):
        """Clean up and report performance metrics."""
        shutil.rmtree(self.test_dir)
        
        # Print performance summary
        print("\n" + "="*60)
        print("PERFORMANCE TEST SUMMARY")
        print("="*60)
        for test_name, metrics in self.performance_metrics.items():
            print(f"{test_name}:")
            for metric_name, value in metrics.items():
                if isinstance(value, float):
                    print(f"  {metric_name}: {value:.4f}s")
                else:
                    print(f"  {metric_name}: {value}")
        print("="*60)
    
    def _create_simulated_files(self, count, age_distribution=None):
        """Create simulated video files with realistic size distribution."""
        simulated_files = {}
        current_time = time.time()
        
        if age_distribution is None:
            age_distribution = {
                'recent': 0.1,  # 10% files from last week
                'medium': 0.2,  # 20% files from last month
                'old': 0.7      # 70% files older than month
            }
        
        recent_count = int(count * age_distribution['recent'])
        medium_count = int(count * age_distribution['medium'])
        old_count = count - recent_count - medium_count
        
        file_index = 0
        
        # Create recent files (< 1 week old)
        for i in range(recent_count):
            filename = f"recent_video_{i:05d}.h264"
            age_seconds = i * (7 * 24 * 60 * 60) // recent_count  # Spread across last week
            file_age = current_time - age_seconds
            
            simulated_files[filename] = {
                'size_bytes': 1024000 + (i * 10000),  # 1MB + variation
                'size_human': _format_bytes_simple(1024000 + (i * 10000)),
                'path': f"{self.device_id}/{filename}",
                'status': 'backed-up',
                'filesystem_enhanced': True,
                'mtime': file_age,
                'age_category': 'recent'
            }
            file_index += 1
        
        # Create medium age files (1 week - 1 month old)
        for i in range(medium_count):
            filename = f"medium_video_{i:05d}.h264"
            age_seconds = (7 * 24 * 60 * 60) + (i * (23 * 24 * 60 * 60) // medium_count)  # 1-4 weeks old
            file_age = current_time - age_seconds
            
            simulated_files[filename] = {
                'size_bytes': 2048000 + (i * 15000),  # 2MB + variation
                'size_human': _format_bytes_simple(2048000 + (i * 15000)),
                'path': f"{self.device_id}/{filename}",
                'status': 'backed-up',
                'filesystem_enhanced': True,
                'mtime': file_age,
                'age_category': 'medium'
            }
            file_index += 1
        
        # Create old files (> 1 month old)
        for i in range(old_count):
            filename = f"old_video_{i:05d}.h264"
            age_seconds = (30 * 24 * 60 * 60) + (i * (335 * 24 * 60 * 60) // old_count)  # 1-12 months old
            file_age = current_time - age_seconds
            
            simulated_files[filename] = {
                'size_bytes': 3072000 + (i * 20000),  # 3MB + variation
                'size_human': _format_bytes_simple(3072000 + (i * 20000)),
                'path': f"{self.device_id}/{filename}",
                'status': 'backed-up',
                'filesystem_enhanced': True,
                'mtime': file_age,
                'age_category': 'old'
            }
            file_index += 1
        
        return simulated_files
    
    def test_cache_performance_1k_files(self):
        """Test cache performance with 1,000 files."""
        file_count = 1000
        simulated_files = self._create_simulated_files(file_count)
        
        # Test save performance
        start_time = time.time()
        _save_video_cache(self.device_id, simulated_files, self.video_directory)
        save_time = time.time() - start_time
        
        # Test load performance
        start_time = time.time()
        loaded_cache = _load_video_cache(self.device_id, self.video_directory)
        load_time = time.time() - start_time
        
        # Record metrics
        self.performance_metrics[f'Cache 1K Files'] = {
            'file_count': file_count,
            'save_time': save_time,
            'load_time': load_time,
            'files_per_second_save': file_count / save_time,
            'files_per_second_load': file_count / load_time
        }
        
        # Verify data integrity
        self.assertEqual(len(loaded_cache['files']), file_count)
        
        # Performance assertions
        self.assertLess(save_time, 2.0, f"Save 1K files should be under 2s, took {save_time:.3f}s")
        self.assertLess(load_time, 1.0, f"Load 1K files should be under 1s, took {load_time:.3f}s")
    
    def test_cache_performance_10k_files(self):
        """Test cache performance with 10,000 files (production scale)."""
        file_count = 10000
        simulated_files = self._create_simulated_files(file_count)
        
        # Test save performance
        start_time = time.time()
        _save_video_cache(self.device_id, simulated_files, self.video_directory)
        save_time = time.time() - start_time
        
        # Test load performance
        start_time = time.time()
        loaded_cache = _load_video_cache(self.device_id, self.video_directory)
        load_time = time.time() - start_time
        
        # Record metrics
        self.performance_metrics[f'Cache 10K Files'] = {
            'file_count': file_count,
            'save_time': save_time,
            'load_time': load_time,
            'files_per_second_save': file_count / save_time,
            'files_per_second_load': file_count / load_time
        }
        
        # Verify data integrity
        self.assertEqual(len(loaded_cache['files']), file_count)
        
        # Performance assertions (more lenient for larger scale)
        self.assertLess(save_time, 10.0, f"Save 10K files should be under 10s, took {save_time:.3f}s")
        self.assertLess(load_time, 5.0, f"Load 10K files should be under 5s, took {load_time:.3f}s")
    
    @patch('glob.glob')
    @patch('os.path.exists')
    @patch('os.path.getsize')
    @patch('os.path.getmtime')
    def test_filesystem_scan_vs_cache_performance(self, mock_getmtime, mock_getsize, mock_exists, mock_glob):
        """Compare filesystem scanning vs cache performance."""
        file_count = 5000
        simulated_files = self._create_simulated_files(file_count)
        
        # Prepare filesystem mocks
        device_path = os.path.join(self.video_directory, self.device_id)
        h264_files = [os.path.join(device_path, filename) for filename in simulated_files.keys()]
        
        mock_glob.return_value = h264_files
        mock_exists.return_value = True
        mock_getsize.side_effect = lambda path: simulated_files.get(os.path.basename(path), {}).get('size_bytes', 0)
        mock_getmtime.side_effect = lambda path: simulated_files.get(os.path.basename(path), {}).get('mtime', time.time())
        
        # Pre-populate cache
        _save_video_cache(self.device_id, simulated_files, self.video_directory)
        
        # Test full filesystem scan (simulated)
        start_time = time.time()
        scanned_files = {}
        for h264_file in h264_files:
            filename = os.path.basename(h264_file)
            file_size = mock_getsize(h264_file)
            scanned_files[filename] = {
                'size_bytes': file_size,
                'size_human': _format_bytes_simple(file_size),
                'path': f"{self.device_id}/{filename}",
                'status': 'backed-up',
                'filesystem_enhanced': True
            }
        filesystem_scan_time = time.time() - start_time
        
        # Test cache-optimized scan (only new/recent files)
        start_time = time.time()
        loaded_cache = _load_video_cache(self.device_id, self.video_directory)
        cache_load_time = time.time() - start_time
        
        # Simulate checking file ages and using cache for old files
        start_time = time.time()
        cache_optimized_files = {}
        cache_hits = 0
        fresh_scans = 0
        
        for filename, file_data in simulated_files.items():
            file_path = os.path.join(device_path, filename)
            file_age = time.time() - file_data['mtime']
            week_in_seconds = 7 * 24 * 60 * 60
            
            if file_age > week_in_seconds and filename in loaded_cache['files']:
                # Use cache for old files
                cache_optimized_files[filename] = loaded_cache['files'][filename]
                cache_hits += 1
            else:
                # Fresh scan for recent files
                file_size = mock_getsize(file_path)
                cache_optimized_files[filename] = {
                    'size_bytes': file_size,
                    'size_human': _format_bytes_simple(file_size),
                    'path': f"{self.device_id}/{filename}",
                    'status': 'backed-up',
                    'filesystem_enhanced': True
                }
                fresh_scans += 1
        
        cache_optimized_time = time.time() - start_time + cache_load_time
        
        # Record metrics
        self.performance_metrics['Filesystem vs Cache'] = {
            'file_count': file_count,
            'full_filesystem_scan': filesystem_scan_time,
            'cache_optimized_scan': cache_optimized_time,
            'cache_hits': cache_hits,
            'fresh_scans': fresh_scans,
            'performance_improvement': f"{((filesystem_scan_time - cache_optimized_time) / filesystem_scan_time * 100):.1f}%",
            'cache_hit_ratio': f"{(cache_hits / file_count * 100):.1f}%"
        }
        
        # Verify cache optimization is significantly faster
        self.assertLess(cache_optimized_time, filesystem_scan_time * 0.5,
                       f"Cache-optimized scan should be at least 50% faster")
        
        # Verify high cache hit ratio for realistic age distribution
        cache_hit_ratio = cache_hits / file_count
        self.assertGreater(cache_hit_ratio, 0.6, 
                          f"Should have high cache hit ratio, got {cache_hit_ratio:.2f}")
    
    def test_cache_disk_space_efficiency(self):
        """Test cache disk space usage efficiency."""
        file_count = 10000
        simulated_files = self._create_simulated_files(file_count)
        
        # Calculate total simulated data size
        total_data_size = sum(f['size_bytes'] for f in simulated_files.values())
        
        # Save cache
        _save_video_cache(self.device_id, simulated_files, self.video_directory)
        
        # Measure cache file size
        cache_path = os.path.join(self.video_directory, '.cache', f'video_cache_{self.device_id}.pkl')
        cache_size = os.path.getsize(cache_path)
        
        # Calculate compression ratio
        compression_ratio = cache_size / total_data_size
        
        # Record metrics
        self.performance_metrics['Cache Disk Usage'] = {
            'file_count': file_count,
            'total_data_size': _format_bytes_simple(total_data_size),
            'cache_file_size': _format_bytes_simple(cache_size),
            'compression_ratio': f"{compression_ratio:.6f}",
            'cache_overhead': f"{(cache_size / 1024 / 1024):.2f} MB"
        }
        
        # Cache should be much smaller than actual data
        self.assertLess(compression_ratio, 0.001, 
                       f"Cache should be <0.1% of data size, got {compression_ratio:.6f}")
        
        # Cache should be reasonable size (under 100MB for 10K files)
        max_cache_size = 100 * 1024 * 1024  # 100MB
        self.assertLess(cache_size, max_cache_size,
                       f"Cache should be under 100MB, got {cache_size / 1024 / 1024:.2f}MB")
    
    def test_concurrent_cache_access_simulation(self):
        """Simulate concurrent cache access (multiple devices)."""
        device_count = 10
        files_per_device = 1000
        
        # Create multiple device caches
        devices = {}
        for i in range(device_count):
            device_id = f"device_{i:03d}"
            simulated_files = self._create_simulated_files(files_per_device)
            devices[device_id] = simulated_files
        
        # Test concurrent save operations
        start_time = time.time()
        for device_id, files in devices.items():
            _save_video_cache(device_id, files, self.video_directory)
        concurrent_save_time = time.time() - start_time
        
        # Test concurrent load operations
        start_time = time.time()
        loaded_caches = {}
        for device_id in devices.keys():
            loaded_caches[device_id] = _load_video_cache(device_id, self.video_directory)
        concurrent_load_time = time.time() - start_time
        
        # Record metrics
        self.performance_metrics['Concurrent Access'] = {
            'device_count': device_count,
            'files_per_device': files_per_device,
            'total_files': device_count * files_per_device,
            'concurrent_save_time': concurrent_save_time,
            'concurrent_load_time': concurrent_load_time,
            'avg_save_per_device': concurrent_save_time / device_count,
            'avg_load_per_device': concurrent_load_time / device_count
        }
        
        # Verify all caches were created and loaded correctly
        self.assertEqual(len(loaded_caches), device_count)
        for device_id, cache_data in loaded_caches.items():
            self.assertEqual(len(cache_data['files']), files_per_device)
        
        # Performance should scale reasonably
        avg_save_per_device = concurrent_save_time / device_count
        avg_load_per_device = concurrent_load_time / device_count
        
        self.assertLess(avg_save_per_device, 5.0, 
                       f"Average save per device should be under 5s, got {avg_save_per_device:.3f}s")
        self.assertLess(avg_load_per_device, 2.0,
                       f"Average load per device should be under 2s, got {avg_load_per_device:.3f}s")


class TestCacheRobustness(unittest.TestCase):
    """Test cache system robustness and error handling."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.device_id = "robustness_test_device"
        self.video_directory = os.path.join(self.test_dir, "videos")
        os.makedirs(self.video_directory, exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)
    
    def test_cache_corruption_recovery(self):
        """Test recovery from corrupted cache files."""
        cache_path = os.path.join(self.video_directory, '.cache', f'video_cache_{self.device_id}.pkl')
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        
        # Create corrupted cache file
        with open(cache_path, 'wb') as f:
            f.write(b"corrupted data that is not valid pickle")
        
        # Should handle corruption gracefully
        cache_data = _load_video_cache(self.device_id, self.video_directory)
        expected = {'files': {}, 'timestamp': 0}
        self.assertEqual(cache_data, expected)
    
    def test_cache_permission_handling(self):
        """Test handling of permission issues."""
        # Create cache directory but make it read-only
        cache_dir = os.path.join(self.video_directory, '.cache')
        os.makedirs(cache_dir, exist_ok=True)
        os.chmod(cache_dir, 0o444)  # Read-only
        
        test_files = {'test.h264': {'size_bytes': 1024, 'path': 'test.h264'}}
        
        try:
            # Should handle permission error gracefully
            _save_video_cache(self.device_id, test_files, self.video_directory)
            # No exception should be raised
        except Exception as e:
            self.fail(f"Cache save should handle permission errors gracefully, got: {e}")
        finally:
            # Restore permissions for cleanup
            os.chmod(cache_dir, 0o755)
    
    def test_cache_with_empty_files_dict(self):
        """Test cache behavior with empty files dictionary."""
        empty_files = {}
        
        # Should handle empty files gracefully
        _save_video_cache(self.device_id, empty_files, self.video_directory)
        
        loaded_cache = _load_video_cache(self.device_id, self.video_directory)
        self.assertEqual(loaded_cache['files'], {})
        self.assertIsInstance(loaded_cache['timestamp'], float)
    
    def test_cache_with_malformed_data(self):
        """Test cache behavior with malformed input data."""
        malformed_files = {
            'file1.h264': {'size_bytes': 'not_a_number'},  # Invalid size
            'file2.h264': None,  # None value
            'file3.h264': {'missing_required_fields': True}
        }
        
        # Should handle malformed data without crashing
        try:
            _save_video_cache(self.device_id, malformed_files, self.video_directory)
            loaded_cache = _load_video_cache(self.device_id, self.video_directory)
            # Should load the data as-is (garbage in, garbage out, but no crash)
            self.assertIn('files', loaded_cache)
        except Exception as e:
            self.fail(f"Cache should handle malformed data gracefully, got: {e}")


if __name__ == '__main__':
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        TestCachePerformanceRealistic,
        TestCacheRobustness
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2, buffer=False)
    result = runner.run(suite)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)