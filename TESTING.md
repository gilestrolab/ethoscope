# Testing Guide for Ethoscope Project

This document provides comprehensive guidelines for testing the Ethoscope project, including both the device and node packages.

## Table of Contents

1. [Overview](#overview)
2. [Test Structure](#test-structure)
3. [Running Tests](#running-tests)
4. [Writing Tests](#writing-tests)
5. [Test Types](#test-types)
6. [Coverage Reports](#coverage-reports)
7. [CI/CD Integration](#cicd-integration)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

## Overview

The Ethoscope project uses pytest as the primary testing framework with comprehensive test coverage for both device and node packages. The testing infrastructure supports:

- Unit tests for individual components
- Integration tests for component interactions
- Functional tests for end-to-end workflows
- Coverage analysis and reporting
- Automated test execution
- Mock hardware and network components

## Test Structure

### Directory Layout

```
ethoscope/
├── src/
│   ├── ethoscope/                 # Device package
│   │   └── ethoscope/tests/
│   │       ├── conftest.py        # Test configuration and fixtures
│   │       ├── fixtures/          # Test utilities and mock objects
│   │       ├── unittests/         # Unit tests
│   │       ├── integration_api_tests/  # API integration tests
│   │       ├── integration_server_tests/  # Server integration tests
│   │       └── static_files/      # Test data (images, videos)
│   └── node/                      # Node package
│       └── tests/
│           ├── conftest.py        # Test configuration and fixtures
│           ├── fixtures/          # Test utilities and mock objects
│           ├── unit/              # Unit tests
│           ├── integration/       # Integration tests
│           └── functional/        # Functional tests
├── test-requirements.txt          # Test dependencies
├── run_tests.py                   # Main test runner
└── TESTING.md                     # This document
```

### Test Files

- `conftest.py`: Contains pytest fixtures and configuration
- `fixtures/`: Mock objects, test utilities, and helper functions
- `test_*.py`: Individual test files following pytest conventions

## Running Tests

### Quick Start

```bash
# Install test dependencies
pip install -r test-requirements.txt

# Run all tests
python run_tests.py

# Run specific package tests
python run_tests.py --package device
python run_tests.py --package node

# Run with coverage
python run_tests.py --coverage
```

### Device Package Tests

```bash
# Using the device package Makefile
cd src/ethoscope/
make test                # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only

# Using pytest directly
cd src/ethoscope/
python -m pytest ethoscope/tests/
python -m pytest ethoscope/tests/unittests/
python -m pytest ethoscope/tests/integration_api_tests/

# Using the shell script
cd src/ethoscope/ethoscope/tests/
./run_all_tests.sh
```

### Node Package Tests

```bash
# Using the node package Makefile
cd src/node/
make test                # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make test-functional    # Run functional tests only

# Using pytest directly
cd src/node/
python -m pytest tests/
python -m pytest tests/unit/
python -m pytest tests/integration/
python -m pytest tests/functional/

# Using the shell script
cd src/node/
./run_tests.sh
```

### Test Options

#### Pytest Markers

```bash
# Run only unit tests
pytest -m "unit"

# Run only integration tests
pytest -m "integration"

# Skip slow tests
pytest -m "not slow"

# Run only slow tests
pytest -m "slow"

# Run only hardware tests (device package)
pytest -m "hardware"
```

#### Verbosity and Output

```bash
# Verbose output
pytest -v

# Very verbose output
pytest -vv

# Show local variables in tracebacks
pytest -l

# Stop on first failure
pytest -x

# Show N slowest tests
pytest --durations=10
```

## Writing Tests

### Test File Structure

```python
"""
Test module for [component name].

This module contains tests for [brief description].
"""

import pytest
from unittest.mock import Mock, patch
from ethoscope.component import ComponentToTest


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
        # Mark slow tests for optional exclusion
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

def test_with_temp_directory(temp_dir):
    """Test using a temporary directory."""
    test_file = temp_dir / "test.txt"
    test_file.write_text("test content")
    assert test_file.exists()
```

### Mocking Guidelines

```python
# Mock external dependencies
@patch('ethoscope.hardware.camera.PiCamera')
def test_camera_interface(mock_camera):
    mock_camera.return_value.resolution = (640, 480)
    # Test code here

# Mock network calls
@patch('requests.get')
def test_api_call(mock_get):
    mock_get.return_value.json.return_value = {"status": "ok"}
    # Test code here

# Use provided mock objects
def test_with_mock_hardware(mock_camera, mock_stimulator):
    # Test code using mock hardware
    pass
```

## Test Types

### Unit Tests

Test individual functions, methods, and classes in isolation.

**Location**: `tests/unit/` or `tests/unittests/`

**Characteristics**:
- Fast execution (< 1 second per test)
- No external dependencies
- High coverage of edge cases
- Mock all dependencies

**Example**:
```python
def test_calculate_distance():
    """Test distance calculation function."""
    point1 = (0, 0)
    point2 = (3, 4)
    distance = calculate_distance(point1, point2)
    assert distance == 5.0
```

### Integration Tests

Test interactions between components and external systems.

**Location**: `tests/integration/` or `tests/integration_api_tests/`

**Characteristics**:
- Test component interactions
- May use real databases or services
- Moderate execution time
- Test data flows

**Example**:
```python
def test_device_scanner_integration():
    """Test device scanner with real network."""
    scanner = DeviceScanner()
    devices = scanner.scan_network()
    assert isinstance(devices, list)
```

### Functional Tests

Test complete workflows and user scenarios.

**Location**: `tests/functional/`

**Characteristics**:
- End-to-end testing
- User-focused scenarios
- Longer execution time
- Real or realistic data

**Example**:
```python
def test_complete_experiment_workflow():
    """Test complete experiment from start to finish."""
    # Setup experiment
    # Run tracking
    # Collect data
    # Verify results
    pass
```

## Coverage Reports

### Generating Coverage Reports

```bash
# HTML report (recommended for development)
pytest --cov=ethoscope --cov-report=html

# Terminal report
pytest --cov=ethoscope --cov-report=term-missing

# XML report (for CI/CD)
pytest --cov=ethoscope --cov-report=xml

# Combined reports
pytest --cov=ethoscope --cov-report=html --cov-report=xml --cov-report=term-missing
```

### Coverage Thresholds

The project aims for:
- **Overall coverage**: 70%
- **Unit tests**: 85%
- **Integration tests**: 60%
- **Critical components**: 90%

### Viewing Coverage Reports

```bash
# Open HTML report in browser
firefox htmlcov/index.html

# View terminal report
cat coverage-report.txt
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.8
    - name: Install dependencies
      run: |
        pip install -r test-requirements.txt
        pip install -e src/ethoscope/
        pip install -e src/node/
    - name: Run tests
      run: python run_tests.py --coverage
    - name: Upload coverage
      uses: codecov/codecov-action@v1
```

### Pre-commit Hooks

```bash
# Install pre-commit
pip install pre-commit

# Setup pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

## Best Practices

### Test Organization

1. **One test file per module**: `test_module_name.py`
2. **Group related tests**: Use test classes
3. **Descriptive test names**: Explain what is being tested
4. **Arrange-Act-Assert**: Structure tests clearly

### Test Data

1. **Use fixtures**: For reusable test data
2. **Small test data**: Keep test data minimal
3. **Realistic data**: Use realistic values
4. **Clean up**: Remove test data after tests

### Performance

1. **Fast unit tests**: Keep unit tests under 1 second
2. **Mark slow tests**: Use `@pytest.mark.slow`
3. **Parallel execution**: Use `pytest-xdist` for parallel runs
4. **Profile tests**: Use `pytest --durations=10`

### Reliability

1. **Independent tests**: Tests should not depend on each other
2. **Deterministic tests**: Avoid random behavior
3. **Clean state**: Reset state between tests
4. **Handle failures**: Graceful failure handling

### Documentation

1. **Test docstrings**: Explain what is being tested
2. **Comment complex logic**: Explain non-obvious test logic
3. **Update documentation**: Keep docs in sync with tests

## Troubleshooting

### Common Issues

#### Import Errors

```bash
# Solution: Install packages in development mode
pip install -e src/ethoscope/
pip install -e src/node/

# Or add to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:src/ethoscope:src/node"
```

#### Hardware Dependencies

```bash
# Mock hardware for testing
pytest -m "not hardware"

# Install hardware dependencies
pip install RPi.GPIO picamera
```

#### Database Issues

```bash
# Use in-memory database for tests
pytest --db-url=sqlite:///:memory:

# Clean test database
rm test_database.db
```

#### Slow Tests

```bash
# Skip slow tests
pytest -m "not slow"

# Run tests in parallel
pytest -n auto
```

### Debug Mode

```bash
# Drop into debugger on failure
pytest --pdb

# Drop into debugger on first failure
pytest -x --pdb

# Show local variables
pytest -l

# Verbose output
pytest -vv
```

### Performance Analysis

```bash
# Show slowest tests
pytest --durations=10

# Profile test execution
pytest --profile

# Memory usage analysis
pytest --memory-profile
```

## Getting Help

- **Documentation**: Check this file and inline docstrings
- **Issue Tracker**: Report bugs and request features
- **pytest Documentation**: https://docs.pytest.org/
- **Coverage.py Documentation**: https://coverage.readthedocs.io/

## Contributing

When adding new tests:

1. Follow the existing test structure
2. Use appropriate test types (unit/integration/functional)
3. Add proper documentation
4. Ensure tests are reliable and fast
5. Update this documentation if needed

Remember: Good tests are the foundation of maintainable code!