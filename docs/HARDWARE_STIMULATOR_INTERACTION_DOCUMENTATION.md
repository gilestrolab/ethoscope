# Hardware Interface and Stimulator Interaction System Documentation

## Overview

The Ethoscope system implements a sophisticated real-time feedback loop for behavioral experiments through the interaction between stimulators and hardware interfaces. This document describes the temporal regulation and execution flow of this system.

## Architecture Components

### 1. Base Stimulator (`BaseStimulator`)
Located in `src/ethoscope/ethoscope/stimulators/stimulators.py:20`

**Core Responsibilities:**
- Manages temporal scheduling through `Scheduler` class
- Interfaces with tracking data via bound tracker
- Coordinates decision-making and hardware delivery
- Handles ROI template configuration and channel mappings

**Key Methods:**
- `apply()`: Main execution method that orchestrates the stimulation pipeline
- `_decide()`: Abstract method implemented by derived classes for stimulus decisions
- `_deliver()`: Hardware instruction delivery method
- `bind_tracker()`: Links tracker data to stimulator

### 2. Hardware Connection (`HardwareConnection`)
Located in `src/ethoscope/ethoscope/hardware/interfaces/interfaces.py:69`

**Core Responsibilities:**
- Provides asynchronous hardware communication via dedicated thread
- Maintains instruction queue for sequential processing
- Manages hardware interface lifecycle

**Thread-Based Execution:**
- Runs continuous loop checking for pending instructions
- Processes instructions at 10Hz (100ms intervals)
- Handles hardware communication errors gracefully

### 3. Hardware Interfaces
Located in `src/ethoscope/ethoscope/hardware/interfaces/`

**Base Interface (`SimpleSerialInterface`):**
- Serial communication management
- Device discovery and connection
- Port detection and configuration

**Specialized Interfaces:**
- `SleepDepriverInterface`: Servo motor control for tube rotation
- `LynxMotionInterface`: SSC-32U servo controller communication
- `OptoMotor`: Combined optogenetic and motor stimulation

## Temporal Regulation System

### Scheduling (`Scheduler`)
Located in `src/ethoscope/ethoscope/utils/scheduler.py:9`

**Time Range Management:**
- Parses date range strings (format: "YYYY-MM-DD HH:MM:SS > YYYY-MM-DD HH:MM:SS")
- Supports multiple time ranges separated by commas
- Validates non-overlapping ranges
- Provides real-time validation via `check_time_range()`

**Integration with Stimulators:**
```python
if self._scheduler.check_time_range() is False:
    return HasInteractedVariable(False), {}
```

### Execution Flow

#### 1. Initialization Phase
1. Stimulator instantiated with hardware interface class
2. `HardwareConnection` thread started with interface instance
3. Scheduler configured with date range string
4. Tracker bound to stimulator for data access

#### 2. Real-Time Execution Cycle
**Location**: `src/ethoscope/ethoscope/stimulators/stimulators.py:47-66`

```python
def apply(self):
    # 1. Validate tracker binding
    if self._tracker is None:
        raise ValueError("No tracker bound")
        
    # 2. Check temporal scheduling
    if self._scheduler.check_time_range() is False:
        return HasInteractedVariable(False), {}
        
    # 3. Make stimulation decision
    interact, result = self._decide()
    
    # 4. Deliver hardware instruction if required
    if interact > 0:
        self._deliver(**result)
        
    return interact, result
```

#### 3. Hardware Instruction Delivery
**Location**: `src/ethoscope/ethoscope/hardware/interfaces/interfaces.py:104-115`

**Asynchronous Processing:**
1. Instructions queued via `send_instruction()`
2. Background thread processes queue sequentially
3. Interface-specific `send()` method handles hardware communication
4. Error handling prevents system crashes

## Timing Characteristics

### Decision Timing
- **Sleep Deprivation**: Checks for inactivity periods (default: 120 seconds)
- **Movement Detection**: Real-time velocity calculations with correction coefficients
- **Refractory Periods**: Prevents rapid repeated stimulations

### Hardware Timing
- **Servo Motors**: Configurable duration (default: 350-800ms)
- **Instruction Queue**: 100ms processing intervals
- **Serial Communication**: 115200 baud rate, 2-second timeout

### Example: Sleep Deprivation Timing
**Location**: `src/ethoscope/ethoscope/stimulators/sleep_depriver_stimulators.py:124-153`

```python
def _decide(self):
    # Track time since last movement
    if not has_moved:
        if float(now - self._t0) > self._inactivity_time_threshold_ms:
            # Deliver stimulus after inactivity threshold
            return HasInteractedVariable(1), {"channel": channel}
    else:
        # Reset timer on movement detection
        self._t0 = now
```

## Hardware Interface Implementations

### Sleep Depriver Interface
**Location**: `src/ethoscope/ethoscope/hardware/interfaces/sleep_depriver_interface.py`

**Servo Movement Pattern:**
1. Move to starting position (margin degrees from minimum)
2. Rotate to maximum angle over specified duration
3. Return to minimum angle
4. Return to neutral position

**Continuous Rotation Version:**
- Speed-based control (-100 to +100)
- Bidirectional rotation patterns
- Automatic stop commands

### Lynx Motion Interface
**Location**: `src/ethoscope/ethoscope/hardware/interfaces/lynx_motion.py`

**Servo Control:**
- Angle-to-pulse conversion (535-2500 pulse range)
- 10-channel support
- Configurable movement duration
- Speed control for continuous rotation servos

## ROI-to-Channel Mapping

### Standard Mapping (Sleep Deprivation)
```python
_roi_to_channel = {
    1:1,   3:2,   5:3,   7:4,   9:5,
    12:6,  14:7,  16:8,  18:9,  20:10
}
```

### mAGO System Mapping
**Motor Channels (odd):** `{1:1, 3:3, 5:5, 7:7, 9:9, 12:11, 14:13, 16:15, 18:17, 20:19}`
**Valve Channels (even):** `{1:0, 3:2, 5:4, 7:6, 9:8, 11:10, 13:12, 15:14, 17:16, 19:18}`

## Data Logging and Monitoring

### Interaction Variables
**Location**: `src/ethoscope/ethoscope/stimulators/stimulators.py:10-16`

```python
class HasInteractedVariable(BaseIntVariable):
    functional_type = "interaction"
    header_name = "has_interacted"
```

**Values:**
- `0`: No interaction
- `1`: Real stimulation delivered
- `2`: Ghost stimulation (probability-based false positive)

### Logging Integration
- Hardware connection errors logged via Python logging
- Stimulation events logged with channel information
- Serial communication diagnostics available

## Error Handling and Robustness

### Hardware Disconnection
- Graceful degradation when hardware unavailable
- Default interface provides no-op functionality
- Connection state tracking and recovery

### Instruction Queue Management
- FIFO queue prevents instruction loss
- Thread-safe operations
- Bounded queue prevents memory issues

### Timing Validation
- Date range validation prevents invalid schedules
- Overlap detection for multiple time ranges
- Real-time clock synchronization

## Performance Characteristics

### Latency Sources
1. **Decision Making**: ~1ms (tracker data processing)
2. **Queue Processing**: Up to 100ms (thread polling interval)
3. **Serial Communication**: 2-10ms (hardware dependent)
4. **Servo Movement**: 350-800ms (configurable duration)

### Throughput
- **Maximum Stimulation Rate**: Limited by refractory periods and movement duration
- **Instruction Processing**: 10 instructions/second theoretical maximum
- **Multiple ROI Support**: Parallel processing across channels

## Thread Safety and Concurrency

### Thread Model
- **Main Thread**: Tracking and decision making
- **Hardware Thread**: Asynchronous instruction processing
- **No Shared State**: Communication via thread-safe queue

### Synchronization
- Queue-based communication eliminates race conditions
- Hardware interface lifecycle managed safely
- Graceful shutdown procedures implemented
