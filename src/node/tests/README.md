# Node Package Tests

This directory contains all tests for the Ethoscope node package.

## Structure

```
tests/
├── conftest.py              # Test configuration and fixtures
├── fixtures/                # Test utilities and mock objects
│   ├── mock_devices.py      # Mock device implementations
│   ├── mock_database.py     # Mock database utilities
│   └── __init__.py
├── unit/                    # Unit tests
│   └── __init__.py
├── integration/             # Integration tests
│   └── __init__.py
├── functional/              # Functional tests
│   └── __init__.py
└── README.md               # This file
```

## Test Types

### Unit Tests (`unit/`)
- Test individual functions and classes in isolation
- Fast execution (< 1 second per test)
- Mock all external dependencies
- High coverage of edge cases

### Integration Tests (`integration/`)
- Test component interactions
- Test with real or realistic external systems
- Moderate execution time
- Test data flows between components

### Functional Tests (`functional/`)
- End-to-end testing of complete workflows
- User-focused scenarios
- Longer execution time
- Real or realistic data

## Running Tests

### Using Make
```bash
# From the node package directory
make test                # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make test-functional    # Run functional tests only
make test-coverage      # Run with coverage report
```

### Using pytest directly
```bash
# From the node package directory
python -m pytest tests/
python -m pytest tests/unit/
python -m pytest tests/integration/
python -m pytest tests/functional/
```

### Using the shell script
```bash
# From the node package directory
./run_tests.sh
```

## Test Fixtures

Available fixtures (defined in `conftest.py`):

### Basic Fixtures
- `temp_dir`: Temporary directory for test files
- `mock_config`: Mock configuration dictionary
- `cleanup_test_files`: Automatic cleanup of test files

### Device Fixtures
- `mock_ethoscope_device`: Single mock device
- `mock_device_list`: List of mock devices
- `mock_zeroconf_service`: Mock Zeroconf service for device discovery

### Database Fixtures
- `mock_database`: Mock database connection
- `sample_experiment_data`: Sample experiment data
- `sample_tracking_data`: Sample tracking data

### Network Fixtures
- `mock_network_interface`: Mock network interface
- `mock_cherrypy_server`: Mock CherryPy server

### Git Fixtures
- `mock_git_repo`: Mock git repository for testing updates

## Mock Objects

### Mock Devices (`fixtures/mock_devices.py`)
- `MockEthoscopeDevice`: Complete mock device implementation
- `MockDeviceScanner`: Mock device scanner
- `MockDeviceManager`: Mock device manager
- `create_mock_device_fleet()`: Create multiple mock devices

### Mock Database (`fixtures/mock_database.py`)
- `MockDatabase`: Mock database with query tracking
- `MockSQLiteDatabase`: Temporary SQLite database for tests
- `create_mock_database_with_data()`: Create database with sample data

## Writing Tests

### Test File Template

```python
"""
Test module for [component name].

This module contains tests for [brief description].
"""

import pytest
from unittest.mock import Mock, patch
from ethoscope_node.component import ComponentToTest


class TestComponentToTest:
    """Test class for ComponentToTest."""
    
    def test_basic_functionality(self):
        """Test basic functionality works correctly."""
        component = ComponentToTest()
        result = component.do_something()
        assert result == expected_value
    
    def test_edge_case(self):
        """Test edge case handling."""
        component = ComponentToTest()
        with pytest.raises(ValueError):
            component.do_something_invalid()
    
    @pytest.mark.slow
    def test_performance_intensive(self):
        """Test that takes a long time to run."""
        pass
    
    @pytest.mark.integration
    def test_integration_with_other_component(self):
        """Test integration with other components."""
        pass
```

### Using Fixtures

```python
def test_with_mock_device(mock_ethoscope_device):
    """Test using a mock device fixture."""
    device = mock_ethoscope_device
    assert device.id == "test_device_001"
    assert device.status == "running"

def test_with_mock_database(mock_database):
    """Test using a mock database fixture."""
    db = mock_database
    db.connect()
    result = db.fetchone()
    assert result is not None
```

## Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit
def test_unit_functionality():
    """Unit test example."""
    pass

@pytest.mark.integration
def test_integration_functionality():
    """Integration test example."""
    pass

@pytest.mark.functional
def test_functional_workflow():
    """Functional test example."""
    pass

@pytest.mark.slow
def test_slow_operation():
    """Slow test example."""
    pass
```

## Coverage

The node package aims for:
- Overall coverage: 70%
- Unit tests: 85%
- Integration tests: 60%
- Critical components: 90%

Generate coverage reports:
```bash
pytest --cov=ethoscope_node --cov-report=html
```

## Best Practices

1. **Keep tests independent**: Each test should be able to run in isolation
2. **Use descriptive names**: Test names should explain what is being tested
3. **Mock external dependencies**: Use mocks for databases, networks, hardware
4. **Clean up resources**: Use fixtures to ensure proper cleanup
5. **Test edge cases**: Include tests for error conditions and boundary cases
6. **Keep tests fast**: Unit tests should run quickly
7. **Use appropriate test types**: Unit for components, integration for interactions, functional for workflows

## Troubleshooting

### Common Issues

1. **Import errors**: Make sure the package is installed in development mode
   ```bash
   pip install -e .
   ```

2. **Fixture not found**: Check that fixtures are defined in `conftest.py`

3. **Database connection issues**: Use mock database fixtures for testing

4. **Network timeouts**: Mock network calls or increase timeout values

### Debugging

```bash
# Drop into debugger on failure
pytest --pdb

# Verbose output
pytest -vv

# Show local variables
pytest -l
```

## Adding New Tests

When adding new tests:

1. Choose the appropriate test type (unit/integration/functional)
2. Place the test in the correct directory
3. Use existing fixtures where possible
4. Add new fixtures to `conftest.py` if needed
5. Include appropriate markers
6. Write clear docstrings
7. Test both success and failure cases

Remember: Good tests make development faster and more reliable!