# Multi-Stimulator Feature

## Overview

The Multi-Stimulator feature allows experiments to use multiple stimulators with individual date/time ranges during a single experiment session. This enables complex experimental designs where different stimulation protocols are applied sequentially over time.

## Key Features

- **Sequential Stimulator Activation**: Multiple stimulators can be scheduled with specific date/time ranges
- **Individual Configuration**: Each stimulator in the sequence has its own parameters and schedule
- **Backward Compatibility**: Existing single-stimulator experiments continue to work without changes
- **Dynamic Switching**: Active stimulators are determined in real-time based on current time
- **Comprehensive Logging**: All stimulator transitions are logged for analysis

## Architecture

### New Components

1. **MultiStimulator Class** (`src/ethoscope/ethoscope/stimulators/multi_stimulator.py`)
   - Meta-stimulator that manages multiple stimulator instances
   - Handles scheduling and delegation to active stimulators
   - Provides monitoring and logging capabilities

2. **Enhanced ControlThread** (`src/ethoscope/ethoscope/control/tracking.py`)
   - Updated to include MultiStimulator in available stimulator classes
   - No breaking changes to existing functionality

### Configuration Format

Multi-stimulator experiments use the `MultiStimulator` class with a `stimulator_sequence` parameter:

```python
{
  "interactor": {
    "name": "MultiStimulator",
    "arguments": {
      "stimulator_sequence": [
        {
          "class_name": "OptoMidlineCrossStimulator",
          "arguments": {"p": 0.8},
          "date_range": "2023-01-01 10:00:00>2023-01-02 10:00:00"
        },
        {
          "class_name": "SleepDepStimulator", 
          "arguments": {"min_inactive_time": 120},
          "date_range": "2023-01-03 10:00:00>2023-01-04 10:00:00"
        }
      ]
    }
  }
}
```

### Date/Time Format

Date ranges use the standard Ethoscope scheduler format:
- Format: `YYYY-MM-DD HH:MM:SS>YYYY-MM-DD HH:MM:SS`
- Example: `2023-01-01 10:00:00>2023-01-02 10:00:00`
- Supports multiple comma-separated ranges per stimulator

## Usage Examples

### Example 1: Optomotor + Sleep Deprivation Sequence

```python
stimulator_sequence = [
    {
        "class_name": "OptoMidlineCrossStimulator",
        "arguments": {"p": 1.0},
        "date_range": "2023-01-01 09:00:00>2023-01-01 21:00:00"  # Day 1, 9 AM to 9 PM
    },
    {
        "class_name": "SleepDepStimulator",
        "arguments": {
            "min_inactive_time": 120,
            "stimulus_probability": 0.8
        },
        "date_range": "2023-01-03 09:00:00>2023-01-04 09:00:00"  # Day 3, 24 hours
    }
]
```

### Example 2: Multiple Daily Sessions

```python
stimulator_sequence = [
    {
        "class_name": "MiddleCrossingStimulator",
        "arguments": {"p": 0.5},
        "date_range": "2023-01-01 10:00:00>2023-01-01 12:00:00,2023-01-01 14:00:00>2023-01-01 16:00:00"
    }
]
```

## Implementation Details

### Stimulator Selection Logic

When multiple stimulators have overlapping active periods, the MultiStimulator uses a "first wins" policy:
- The first stimulator in the sequence that is currently active takes precedence
- Future versions could support parallel execution or priority-based selection

### Hardware Interface Handling

- Each stimulator in the sequence shares the same hardware connection
- Hardware interface class is determined by the first stimulator in the sequence
- Stimulation commands are passed through unchanged to the hardware interface

### Logging and Monitoring

- Stimulator transitions are logged with timestamps
- Active stimulator information is included in tracking data
- `get_active_stimulators()` method provides real-time status
- `get_stimulator_info()` provides complete configuration overview

## Backward Compatibility

Existing experiments using single stimulators continue to work unchanged:
- All existing stimulator classes remain available
- Configuration format is unchanged for single-stimulator experiments
- No performance impact on existing functionality

## Testing

Comprehensive unit tests are provided in `test_multi_stimulator.py`:

```bash
cd src/ethoscope
python -m pytest ethoscope/tests/unittests/test_multi_stimulator.py -v
```

Tests cover:
- Initialization with various configurations
- Stimulator scheduling and activation
- Tracker binding
- Edge cases and error handling

## API Reference

### MultiStimulator Class

#### Constructor
```python
MultiStimulator(hardware_connection, stimulator_sequence=None, roi_template_config=None)
```

#### Key Methods
- `get_active_stimulators()`: Returns list of currently active stimulator names
- `get_stimulator_info()`: Returns detailed information about all configured stimulators
- `bind_tracker(tracker)`: Binds tracker to all managed stimulators

#### Configuration Schema
```python
stimulator_sequence = [
    {
        "class_name": str,      # Name of stimulator class
        "arguments": dict,      # Arguments for stimulator constructor
        "date_range": str       # Date/time range in scheduler format
    },
    ...
]
```

## Future Enhancements

Potential future improvements:
- **Parallel Stimulation**: Support for multiple simultaneous stimulators
- **Priority-Based Selection**: Configure priority when stimulators overlap
- **Conditional Activation**: Activate stimulators based on experimental conditions
- **Frontend Integration**: Web interface support for multi-stimulator configuration

## Examples for Common Use Cases

### Circadian Rhythm Studies
```python
# Light/dark cycle with periodic stimulation
stimulator_sequence = [
    {
        "class_name": "OptoMidlineCrossStimulator", 
        "arguments": {"p": 0.3},
        "date_range": "2023-01-01 08:00:00>2023-01-01 20:00:00"  # Light phase
    },
    {
        "class_name": "DefaultStimulator",
        "arguments": {},
        "date_range": "2023-01-01 20:00:00>2023-01-02 08:00:00"  # Dark phase
    }
]
```

### Sleep Deprivation Recovery
```python
# Baseline -> Deprivation -> Recovery
stimulator_sequence = [
    {
        "class_name": "DefaultStimulator",
        "arguments": {},
        "date_range": "2023-01-01 00:00:00>2023-01-02 00:00:00"  # Baseline day
    },
    {
        "class_name": "SleepDepStimulator",
        "arguments": {"min_inactive_time": 60},
        "date_range": "2023-01-02 00:00:00>2023-01-03 00:00:00"  # Deprivation day
    },
    {
        "class_name": "DefaultStimulator",
        "arguments": {},
        "date_range": "2023-01-03 00:00:00>2023-01-04 00:00:00"  # Recovery day
    }
]
```

This feature significantly expands the experimental capabilities of the Ethoscope platform while maintaining simplicity and backward compatibility.