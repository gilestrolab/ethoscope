# Camera Timeout and Failsafe Tests

This document describes the unit tests for camera initialization timeout mechanisms implemented to prevent ethoscope devices from hanging indefinitely during camera initialization.

## Problem Solved

The ethoscope occasionally encountered the error:
```
AttributeError: 'Picamera2' object has no attribute 'allocator'
```

This picamera2 compatibility issue caused the ethoscope to hang in "initialising" state indefinitely, requiring manual intervention.

## Solutions Implemented

### 1. Camera Timeout and Retry Mechanism (`cameras.py`)
- **30-second timeout** for camera frame acquisition
- **2-attempt retry mechanism** with automatic fallback from picamera2 to legacy picamera
- **Enhanced error detection** for specific picamera2 allocator errors
- **Detailed debugging logs** for troubleshooting

### 2. Process-Level Failsafe (`tracking.py`)
- **2-minute watchdog timer** that monitors initialization status
- **Automatic process termination** if stuck in "initialising" state
- **Graceful error reporting** before termination

## Test Coverage

### TestCameraTimeoutMechanisms
- `test_timeout_handler_basic_functionality()`: Verifies timeout handler sets error state correctly
- `test_timeout_handler_no_trigger_when_not_initialising()`: Ensures timeout only triggers during initialization
- `test_picamera2_allocator_error_detection()`: Tests error classification logic
- `test_camera_retry_mechanism_logic()`: Verifies fallback from picamera2 to picamera

### TestCameraLogicIntegration
- `test_frame_grabber_error_handling_structure()`: Tests error categorization for different exception types
- `test_initialization_sequence_structure()`: Verifies initialization retry sequence logic

## Key Test Features

1. **Mock-based Testing**: Uses simplified mocks to test logic without hardware dependencies
2. **Error Type Testing**: Tests both error message content and exception type checking
3. **Retry Logic Testing**: Verifies automatic fallback mechanisms work correctly
4. **Timeout Logic Testing**: Ensures timeout handlers work as expected

## Benefits

- **No Hardware Dependencies**: Tests run without requiring actual camera hardware
- **Fast Execution**: All tests complete in under 2 seconds
- **Comprehensive Coverage**: Tests both normal and error conditions
- **Maintainable**: Simple, focused tests that are easy to understand and modify

## Usage

Run the camera timeout tests:
```bash
# Run just these tests
python -m pytest src/ethoscope/ethoscope/tests/unit/test_camera_timeout.py -v

# Run all unit tests
python -m pytest src/ethoscope/ethoscope/tests/unit/ -v
```

These tests ensure the timeout and failsafe mechanisms work correctly, preventing ethoscopes from getting stuck in initialization loops and improving system reliability.
