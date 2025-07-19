# Device Scanner Integration Tests

This directory contains integration tests for the ethoscope device scanner functionality.

## Tests

### test_complete_logger_fix.py
Tests the complete workflow of logger name updates from IP-based to device-name-based when device info is fetched. Validates:
- Logger name initialization with IP addresses
- Logger name updates when device info becomes available
- Proper logger name format (e.g., "Ethoscope_ETHOSCOPE_065")
- Logger name usage in warning messages

### test_device_scanner_fix.py
Tests the updated device scanner methods to ensure they properly handle the new nested databases structure. Validates:
- MariaDB backup filename extraction from new format
- SQLite backup filename extraction from new format
- Appropriate backup filename selection logic
- Backup status update with new format
- Elimination of "No backup filename available" warnings

### test_logger_name_fix.py
Tests that logger names are properly updated from IP addresses to device names. Validates:
- Logger name update functionality
- Handling of invalid device names
- Different device name format variations
- Logger name persistence after updates

## Running Tests

From the node package directory:

```bash
# Run specific device scanner tests
python -m pytest tests/integration/device_scanner/ -v

# Run with coverage
python -m pytest tests/integration/device_scanner/ --cov=ethoscope_node.utils.device_scanner -v
```

## Requirements

These tests require:
- Mock objects for simulating HTTP responses
- Temporary directories for testing
- Device scanner module imports
- Logging capture functionality