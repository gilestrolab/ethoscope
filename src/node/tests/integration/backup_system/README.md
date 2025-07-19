# Backup System Integration Tests

This directory contains integration tests for the ethoscope backup system functionality.

## Tests

### test_backup_format.py
Tests the updated backup system with the new nested databases structure. Validates:
- MariaDB database validation with new format
- SQLite database validation with new format
- Backup status initialization with new fields
- Device info creation for forced backups
- Frontend compatibility with new backup format

### test_backup_status.py
Tests the unified backup status endpoint that combines information from both MySQL backup daemon (port 8090) and rsync backup daemon (port 8093). Validates:
- Individual backup services connectivity
- Unified backup status endpoint functionality
- Service availability detection
- Status aggregation logic

## Running Tests

From the node package directory:

```bash
# Run specific backup system tests
python -m pytest tests/integration/backup_system/ -v

# Run with coverage
python -m pytest tests/integration/backup_system/ --cov=ethoscope_node.utils.backups_helpers -v
```

## Requirements

These tests require:
- Active backup services (for test_backup_status.py)
- Mock objects for simulating device responses
- Temporary directories for backup path testing