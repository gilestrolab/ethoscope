# Backup System Tests

This directory contains comprehensive tests for the ethoscope backup system, including the new file-based cache optimization and enhanced backup functionality.

## Test Structure

### Unit Tests (`test_backup_helpers.py`)
Tests individual components of the backup system:

- **`TestVideoCacheSystem`**: Tests the file-based cache for video files
  - Cache file creation and management
  - Cache persistence across sessions
  - Cache corruption recovery
  
- **`TestBytesFormatting`**: Tests utility functions
  - Human-readable byte formatting
  - Size calculation accuracy
  
- **`TestRsyncEnhancement`**: Tests rsync service integration
  - Service communication and data parsing
  - Filesystem fallback behavior
  - Cache-aware file enumeration
  
- **`TestDeviceBackupInfo`**: Tests device backup information extraction
  - MySQL/SQLite/Video backup detection
  - Backup recommendation logic
  - Empty/offline device handling
  
- **`TestCachePerformance`**: Tests basic cache performance
  - Small-scale performance validation
  - Cache file size efficiency

### Integration Tests (`test_backup_api_integration.py`)
Tests complete API integration:

- **`TestBackupAPIIntegration`**: Tests backup API endpoints
  - Complete backup status endpoint functionality
  - Service availability detection
  - Device-level backup information
  - API response structure validation
  - Frontend compatibility (home page status)
  
- **`TestBackupAPIErrorHandling`**: Tests error scenarios
  - Service unavailable handling
  - Malformed responses
  - Cache corruption recovery
  - Device scanner failures

### Performance Tests (`test_backup_cache_performance.py`)
Tests production-scale performance:

- **`TestCachePerformanceRealistic`**: Large-scale performance tests
  - 1,000 file cache performance
  - 10,000 file cache performance (production scale)
  - Filesystem scan vs cache comparison
  - Disk space efficiency
  - Concurrent device access simulation
  
- **`TestCacheRobustness`**: Robustness and error handling
  - Cache corruption recovery
  - Permission error handling
  - Malformed data handling
  - Empty data edge cases

### Legacy Tests
- **`test_primary_key_backup.py`**: Tests PRIMARY KEY backup functionality
- **`test_backup_integration.html`**: HTML-based integration testing interface
- **`test_backup_status.py`**: Legacy backup status testing
- **`test_backup_format.py`**: Legacy backup format testing

## Running Tests

### Quick Test (Unit tests only)
```bash
python run_backup_tests.py --quick
```

### Full Test Suite
```bash
python run_backup_tests.py --type all --verbose
```

### Specific Test Types
```bash
# Unit tests only
python run_backup_tests.py --type unit

# Integration tests only  
python run_backup_tests.py --type integration

# Performance tests only (may take several minutes)
python run_backup_tests.py --type performance
```

### Using pytest directly
```bash
# Run all backup tests
pytest test_backup_*.py -v

# Run specific test file
pytest test_backup_helpers.py -v

# Run specific test class
pytest test_backup_helpers.py::TestVideoCacheSystem -v

# Run with coverage
pytest test_backup_*.py --cov=ethoscope_node.backup --cov-report=html
```

## Performance Expectations

### Cache Performance (10,000 files)
- **Cache Save**: < 10 seconds
- **Cache Load**: < 5 seconds  
- **Cache File Size**: < 100MB
- **Cache Hit Ratio**: > 70% for realistic age distribution

### API Performance
- **Backup Status Endpoint**: < 5 seconds (50 devices)
- **API Cache TTL**: 5 minutes (configurable)
- **Service Response**: < 2 seconds per service

### Filesystem vs Cache Optimization
- **Expected Improvement**: > 50% faster with cache
- **Cache Hit Ratio**: 60-90% depending on file age distribution
- **Memory Usage**: Minimal (cache loaded on demand)

## File-Based Cache System

### Cache Location
- **Path**: `/ethoscope_data/videos/.cache/video_cache_{device_id}.pkl`
- **Format**: Python pickle serialization
- **Persistence**: Survives system restarts

### Cache Strategy
- **Files > 1 week old**: Served from cache (no filesystem operations)
- **Files < 1 week old**: Fresh filesystem scan (captures recent changes)
- **Cache Updates**: Automatic after each scan
- **Cache Validation**: Corruption detection and recovery

### Production Benefits
For a production system with 10,000+ video files:
- **Typical scenario**: 90% files older than 1 week
- **Cache hits**: ~9,000 files (no filesystem operations)
- **Fresh scans**: ~1,000 files (recent files only)
- **Performance gain**: 90% reduction in filesystem operations

## Test Data and Mocking

### Realistic Test Data
Tests use realistic data distributions:
- **File sizes**: 1-5MB (typical h264 video sizes)
- **Age distribution**: 70% old files, 20% medium age, 10% recent
- **Device counts**: 1-50 devices for scalability testing
- **File counts**: 100-10,000 files for performance testing

### Mocking Strategy
- **Filesystem operations**: Mocked for deterministic testing
- **Service endpoints**: Mocked rsync/mysql service responses
- **Time dependencies**: Controlled file age simulation
- **Network calls**: Mocked for offline testing

## Troubleshooting

### Common Issues
1. **Import errors**: Ensure ethoscope_node package is in Python path
2. **Permission errors**: Ensure write access to test directories
3. **Performance test timeouts**: Performance tests may take several minutes
4. **Mock failures**: Check mock setup in integration tests

### Test Isolation
- Each test uses temporary directories
- Cleanup occurs in tearDown methods
- No persistent state between tests
- Mock objects reset for each test

### Debug Mode
```bash
# Run with maximum verbosity
python run_backup_tests.py --verbose

# Run single test with debug output
pytest test_backup_helpers.py::TestVideoCacheSystem::test_save_and_load_video_cache -v -s
```

## Contributing

When adding new backup functionality:

1. **Add unit tests** for individual components
2. **Add integration tests** for API endpoints
3. **Add performance tests** if affecting large-scale operations
4. **Update this documentation** with new test descriptions
5. **Ensure backward compatibility** with existing tests

### Test Coverage Goals
- **Unit tests**: > 90% coverage for backup helpers
- **Integration tests**: > 85% coverage for backup APIs
- **Performance tests**: Key scenarios for production scale
- **Error handling**: All exception paths covered