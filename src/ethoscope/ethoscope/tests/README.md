# Device Package Tests

This directory contains all tests for the Ethoscope device package.

## Structure

```
tests/
├── conftest.py                    # Test configuration and fixtures
├── fixtures/                     # Test utilities and mock objects
│   ├── mock_hardware.py          # Mock hardware implementations
│   └── __init__.py
├── unittests/                    # Unit tests
│   ├── test_target_roi_builder.py
│   ├── test_utils.py
│   ├── test_monitor.py           # Monitor class tests
│   ├── test_trackers.py          # Tracking algorithm tests
│   └── __init__.py
├── integration_api_tests/        # API integration tests
│   ├── test_whole_api.py
│   └── old/                      # Legacy test files
├── integration_server_tests/     # Server integration tests
│   ├── *.json                    # Test configuration files
│   └── *.sh                      # Shell test scripts
├── static_files/                 # Test data
│   ├── img/                      # Test images
│   └── videos/                   # Test videos
├── run_all_tests.sh              # Test runner script
└── README.md                     # This file
```

## Test Types

### Unit Tests (`unittests/`)
- Test individual functions and classes in isolation
- Fast execution (< 1 second per test)
- Mock all external dependencies (hardware, network, etc.)
- High coverage of edge cases and error conditions

### Integration Tests (`integration_api_tests/`)
- Test API endpoints and component interactions
- Test with mock or real hardware when possible
- Moderate execution time
- Test data flows between components

### Server Integration Tests (`integration_server_tests/`)
- Test complete server functionality
- Configuration-based tests using JSON files
- Test realistic scenarios and workflows
- May require longer execution time

## Running Tests

### Using Make
```bash
# From the device package directory
make test                # Run all tests
make test-unit          # Run unit tests only
make test-integration   # Run integration tests only
make check              # Run tests + quality checks
```

### Using pytest directly
```bash
# From the device package directory
python -m pytest ethoscope/tests/
python -m pytest ethoscope/tests/unittests/
python -m pytest ethoscope/tests/integration_api_tests/
```

### Using the shell script
```bash
# From the tests directory
./run_all_tests.sh
```

## Test Fixtures

Available fixtures (defined in `conftest.py`):

### Basic Fixtures
- `temp_dir`: Temporary directory for test files
- `mock_hardware_config`: Mock hardware configuration
- `cleanup_test_files`: Automatic cleanup of test files

### Hardware Fixtures
- `mock_camera`: Mock camera interface
- `mock_stimulator`: Mock stimulator interface
- `mock_sensor`: Mock sensor interface
- `mock_gpio`: Mock GPIO interface
- `mock_serial_port`: Mock serial port interface

### Data Fixtures
- `mock_frame`: Mock video frame with test patterns
- `mock_roi`: Single mock ROI (Region of Interest)
- `mock_roi_list`: List of mock ROIs
- `sample_tracking_results`: Sample tracking data
- `mock_experiment_config`: Mock experiment configuration

### File Fixtures
- `test_images`: Paths to test images
- `test_videos`: Paths to test videos
- `mock_video_file`: Mock video file object

## Mock Objects

### Mock Hardware (`fixtures/mock_hardware.py`)
- `MockCamera`: Complete camera implementation with test patterns
- `MockStimulator`: Stimulator with activation tracking
- `MockSensor`: Sensor with configurable readings
- `MockGPIO`: GPIO interface with pin state tracking
- `MockSerialPort`: Serial communication with buffer management
- `create_mock_hardware_setup()`: Create complete hardware setup

### Hardware Simulation
Mock hardware components simulate real behavior:
- Camera generates test frames with patterns for tracking
- Stimulators track activation count and timing
- Sensors provide realistic readings with noise
- GPIO maintains pin state and direction
- Serial ports handle communication with buffers

## Writing Tests

### Test File Template

```python
"""
Test module for [component name].

This module contains tests for [brief description].
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch
from ethoscope.component import ComponentToTest


class TestComponentToTest:
    """Test class for ComponentToTest."""
    
    def test_basic_functionality(self):
        """Test basic functionality works correctly."""
        component = ComponentToTest()
        result = component.do_something()
        assert result == expected_value
    
    def test_with_mock_hardware(self, mock_camera):
        """Test using mock hardware."""
        component = ComponentToTest(camera=mock_camera)
        result = component.capture_frame()
        assert result is not None
    
    @pytest.mark.hardware
    def test_hardware_integration(self):
        """Test that requires real hardware."""
        # Only runs with real hardware available
        pass
    
    @pytest.mark.slow
    def test_performance_test(self):
        """Test that takes time to run."""
        # Marked as slow test
        pass
```

### Using Hardware Fixtures

```python
def test_with_mock_camera(mock_camera):
    """Test camera interface."""
    assert mock_camera.resolution == (640, 480)
    frame = mock_camera.capture()
    assert frame is not None
    assert frame.shape == (480, 640, 3)

def test_with_mock_stimulator(mock_stimulator):
    """Test stimulator interface."""
    mock_stimulator.activate(duration=1.0)
    assert mock_stimulator.is_active == False  # Should deactivate after duration
    assert mock_stimulator.activation_count == 1

def test_with_test_images(test_images):
    """Test with real test images."""
    bright_img_path = test_images["bright_targets"]
    assert bright_img_path.exists()
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

@pytest.mark.hardware
def test_hardware_functionality():
    """Hardware test example (requires real hardware)."""
    pass

@pytest.mark.slow
def test_slow_operation():
    """Slow test example."""
    pass
```

## Coverage

The device package aims for:
- Overall coverage: 70%
- Unit tests: 85%
- Integration tests: 60%
- Core components (Monitor, Trackers): 90%

Generate coverage reports:
```bash
pytest --cov=ethoscope --cov-report=html
```

## Hardware Testing

### Mock Hardware
- Use mock hardware for most tests
- Provides consistent, predictable behavior
- Enables testing error conditions
- Fast execution

### Real Hardware
- Mark tests with `@pytest.mark.hardware`
- Test actual hardware integration
- May require specific hardware setup
- Slower execution

### Running Hardware Tests
```bash
# Skip hardware tests (default)
pytest -m "not hardware"

# Run only hardware tests
pytest -m "hardware"

# Run all tests including hardware
pytest
```

## Performance Testing

### Tracking Performance
- Test tracking algorithms with realistic data
- Measure frames per second (FPS)
- Test memory usage over time
- Verify real-time performance

### Video Processing
- Test with actual video files
- Measure processing speed
- Test memory management
- Verify output quality

## Best Practices

1. **Mock External Dependencies**: Always mock cameras, sensors, network calls
2. **Use Realistic Data**: Test with data similar to real usage
3. **Test Edge Cases**: Include boundary conditions and error cases
4. **Keep Tests Independent**: Each test should run in isolation
5. **Use Descriptive Names**: Test names should explain what is being tested
6. **Test Performance**: Include performance tests for critical paths
7. **Clean Up Resources**: Ensure proper cleanup of hardware resources

## Troubleshooting

### Common Issues

1. **Hardware not available**: Use `@pytest.mark.hardware` and mock objects
2. **Import errors**: Install package in development mode: `pip install -e .`
3. **Missing test data**: Ensure test images/videos are present
4. **Slow tests**: Use `pytest -m "not slow"` to skip slow tests

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

1. Choose appropriate test type (unit/integration)
2. Place in correct directory
3. Use existing fixtures where possible
4. Add new fixtures to `conftest.py` if needed
5. Include appropriate markers
6. Test both success and failure cases
7. Update this README if needed

Remember: Good tests make hardware development safer and more reliable!
