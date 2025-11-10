# Sleep Restriction System Usage Guide

## Overview

The Ethoscope sleep restriction system provides precise temporal control over sleep deprivation experiments through daily time-limited operation. This system extends the existing mAGO hardware capabilities to operate only during specified time windows each day.

## Key Components

### 1. DailyScheduler
Enhanced scheduler class for daily time-restricted operations.

**Features:**
- Configurable daily duration (N hours per day)
- Flexible intervals (daily, twice daily, etc.)
- State persistence across system restarts
- Real-time status monitoring

### 2. mAGOSleepRestriction
Main sleep restriction stimulator inheriting from mAGO.

**Features:**
- Inherits all mAGO motor/valve capabilities
- Daily time window enforcement
- ROI-specific state tracking
- Comprehensive status reporting

### 3. SimpleTimeRestrictedStimulator
User-friendly stimulator with preset patterns.

**Features:**
- 5 preset restriction patterns
- Custom pattern support
- Simplified configuration

## Usage Examples

### Basic Sleep Restriction (8 hours per day)

```python
from ethoscope.stimulators.sleep_restriction_stimulators import mAGOSleepRestriction
from ethoscope.hardware.interfaces.interfaces import HardwareConnection
from ethoscope.hardware.interfaces.optomotor import OptoMotor

# Initialize hardware connection
hardware = HardwareConnection(OptoMotor)

# Create sleep restriction stimulator
stimulator = mAGOSleepRestriction(
    hardware_connection=hardware,
    daily_duration_hours=8,          # 8 hours active per day
    interval_hours=24,               # Every 24 hours (daily)
    daily_start_time="09:00:00",     # Start at 9 AM
    stimulus_type=1,                 # Use motors (1) or valves (2)
    min_inactive_time=120,           # Stimulate after 2 min inactivity
    stimulus_probability=1.0         # 100% stimulus probability
)

# Bind to tracker (done automatically by system)
# stimulator.bind_tracker(tracker)

# Check status
status = stimulator.get_schedule_status()
print(f"Currently active: {status['fully_active']}")
print(f"Status: {status['status']}")
```

### Intensive Sleep Restriction (4 hours every 8 hours)

```python
# Twice-daily restriction pattern
stimulator = mAGOSleepRestriction(
    hardware_connection=hardware,
    daily_duration_hours=4,          # 4 hours active per period
    interval_hours=8,                # Every 8 hours (3x daily)
    daily_start_time="06:00:00",     # First period at 6 AM
    stimulus_type=2                  # Use air valves
)

# Active periods: 06:00-10:00, 14:00-18:00, 22:00-02:00
```

### Simple Preset Patterns

```python
from ethoscope.stimulators.sleep_restriction_stimulators import SimpleTimeRestrictedStimulator

# Pattern 1: 8 hours per day
stimulator = SimpleTimeRestrictedStimulator(
    hardware_connection=hardware,
    restriction_pattern=1,           # Preset pattern 1-5
    daily_start_time="09:00:00"
)

# Available patterns:
# 1: 8 hours active per day
# 2: 12 hours active per day  
# 3: 6 hours active twice per day
# 4: 4 hours active three times per day
# 5: Custom pattern (specify custom_duration_hours, custom_interval_hours)
```

### Custom Pattern

```python
# Custom 6-hour restriction every 16 hours
stimulator = SimpleTimeRestrictedStimulator(
    hardware_connection=hardware,
    restriction_pattern=5,           # Custom pattern
    custom_duration_hours=6,
    custom_interval_hours=16,
    daily_start_time="08:00:00"
)
```

## Web Interface Configuration

The sleep restriction stimulators are automatically available in the Ethoscope web interface:

### Via Device Web Interface

1. Navigate to your Ethoscope device web interface
2. Go to **Configuration** → **Interactor**
3. Select from available options:
   - **mAGOSleepRestriction**: Full configuration control
   - **SimpleTimeRestrictedStimulator**: Preset patterns

### Configuration Parameters

#### mAGOSleepRestriction Parameters:
- **daily_duration_hours** (1-24): Hours active per day
- **interval_hours** (1-168): Hours between active periods
- **daily_start_time** (HH:MM:SS): Daily start time
- **stimulus_type** (1-2): Motor (1) or valves (2)
- **min_inactive_time** (1-43200s): Inactivity threshold
- **stimulus_probability** (0-1): Stimulation probability

#### SimpleTimeRestrictedStimulator Parameters:
- **restriction_pattern** (1-5): Preset pattern selection
- **daily_start_time** (HH:MM:SS): Daily start time
- **custom_duration_hours** (1-24): For pattern 5 only
- **custom_interval_hours** (1-168): For pattern 5 only

## Monitoring and Status

### Real-time Status Checking

```python
# Get comprehensive status
status = stimulator.get_schedule_status()

print(f"Overall experiment active: {status['overall_experiment_active']}")
print(f"Daily schedule active: {status['daily_schedule']['currently_active']}")
print(f"Fully active: {status['fully_active']}")
print(f"Status message: {status['status']}")

# Get detailed schedule info
daily_info = stimulator._daily_scheduler.get_schedule_info()
print(f"Next period: {daily_info['next_period_start']}")
print(f"Time until next: {daily_info.get('seconds_until_next_period', 0) / 3600:.1f}h")
```

### Activity Logging

```python
# Get activity log
log = stimulator.get_daily_activity_log()
print(f"State file: {log['state_file']}")
print(f"Activity periods: {len(log['activity_periods'])}")
```

## State Persistence

The system automatically maintains state across restarts:

- **State files**: Stored in `/tmp/ethoscope_sleep_restriction/`
- **ROI-specific**: Each ROI gets its own state file
- **Activity tracking**: Records when each restriction period begins
- **Recovery**: Automatically resumes schedules after system restart

### State File Example
```json
{
  "period_1721840400": {
    "start_time": 1721840400,
    "end_time": 1721869200,
    "first_activity": 1721840450
  }
}
```

## Common Use Cases

### 1. Standard Sleep Deprivation Protocol
- **Configuration**: 8h active per day starting at 9 AM
- **Pattern**: mAGOSleepRestriction(8, 24, "09:00:00")
- **Use case**: General sleep deprivation studies

### 2. Chronic Sleep Restriction
- **Configuration**: 4h active every 8h starting at 6 AM  
- **Pattern**: mAGOSleepRestriction(4, 8, "06:00:00")
- **Use case**: Chronic sleep restriction studies

### 3. Circadian Disruption
- **Configuration**: 6h active every 12h starting at varying times
- **Pattern**: Multiple mAGOSleepRestriction instances
- **Use case**: Circadian rhythm disruption studies

### 4. Recovery Studies
- **Configuration**: Variable patterns with preset switches
- **Pattern**: SimpleTimeRestrictedStimulator with pattern changes
- **Use case**: Sleep recovery and consolidation studies

## Error Handling

The system includes comprehensive error handling:

### Configuration Validation
```python
try:
    stimulator = mAGOSleepRestriction(
        hardware_connection=hardware,
        daily_duration_hours=25  # Invalid: > 24 hours
    )
except DailyScheduleError as e:
    print(f"Configuration error: {e}")
```

### Common Errors and Solutions

1. **Duration > 24 hours**: Reduce daily_duration_hours to ≤ 24
2. **Duration > interval**: Ensure daily_duration_hours ≤ interval_hours
3. **Invalid time format**: Use HH:MM:SS format (e.g., "09:30:00")
4. **State file permissions**: Ensure write access to state directory

## Integration with Existing Workflows

### Database Logging
The system integrates seamlessly with existing Ethoscope logging:
- All stimulation events logged with timestamps
- Schedule adherence tracked in activity logs
- Compatible with existing analysis pipelines

### Hardware Compatibility
Fully compatible with existing mAGO hardware:
- Uses same channel mappings as mAGO
- Supports both motor and valve stimulation
- ROI template configuration supported

### Experiment Management
Works with existing experiment management:
- Date range constraints from base Scheduler
- Multi-ROI support with individual state tracking
- Integration with node-based experiment control

## Best Practices

### 1. Planning Experiments
- **Test schedules**: Verify time windows before starting experiments
- **State directory**: Ensure adequate disk space for state files
- **Hardware testing**: Test mAGO hardware before restriction experiments

### 2. Monitoring During Experiments
- **Regular status checks**: Monitor schedule adherence
- **Log analysis**: Review activity logs for unexpected behavior
- **Backup state files**: Consider backing up state files for long experiments

### 3. Data Analysis
- **Schedule validation**: Verify actual vs. intended schedules in analysis
- **Activity correlation**: Correlate animal activity with restriction periods
- **Statistical considerations**: Account for time-restricted sampling in statistics

## Troubleshooting

### Schedule Not Active
1. Check current time vs. configured schedule
2. Verify date_range parameter (overall experiment window)
3. Check state file permissions and directory access

### Hardware Not Responding
1. Verify mAGO hardware connection and configuration
2. Check stimulus_type parameter (1=motor, 2=valves)
3. Test with standard mAGO stimulator first

### State File Issues
1. Ensure write permissions to state directory
2. Check disk space availability
3. Verify JSON format if manually editing state files

### Performance Issues
1. Monitor state file sizes (cleanup old periods if needed)
2. Check system clock accuracy for timing precision
3. Verify adequate CPU resources for real-time processing

## Migration from Existing Systems

### From Standard mAGO
```python
# Old mAGO configuration
old_stimulator = mAGO(
    hardware_connection=hardware,
    stimulus_type=1,
    min_inactive_time=120
)

# New sleep restriction version
new_stimulator = mAGOSleepRestriction(
    hardware_connection=hardware,
    stimulus_type=1,
    min_inactive_time=120,
    daily_duration_hours=8,      # NEW: time restriction
    interval_hours=24,           # NEW: daily schedule
    daily_start_time="09:00:00"  # NEW: start time
)
```

### Preserving Existing Parameters
All existing mAGO parameters are preserved:
- `velocity_correction_coef`
- `min_inactive_time`  
- `pulse_duration`
- `stimulus_type`
- `stimulus_probability`
- `date_range`
- `roi_template_config`

## Future Extensions

The architecture supports future enhancements:

### Planned Features
- **Dynamic schedule adjustment**: Runtime schedule modifications
- **Multi-phase experiments**: Different restriction patterns over time
- **Group coordination**: Synchronized schedules across multiple devices
- **Advanced patterns**: Non-uniform daily schedules

### API Extensions
- **REST API**: Web-based schedule management
- **Real-time adjustments**: Dynamic parameter updates
- **Status broadcasting**: Network-wide status monitoring

## Support and Resources

### Documentation
- **System architecture**: `HARDWARE_STIMULATOR_INTERACTION_DOCUMENTATION.md`
- **Test examples**: `src/ethoscope/ethoscope/tests/unit/test_sleep_restriction.py`
- **Demo script**: `test_sleep_restriction_demo.py`

### Code Locations
- **DailyScheduler**: `src/ethoscope/ethoscope/utils/scheduler.py`
- **Stimulators**: `src/ethoscope/ethoscope/stimulators/sleep_restriction_stimulators.py`
- **Web integration**: `src/ethoscope/ethoscope/control/tracking.py`

### Getting Help
1. **Check logs**: Review system logs for detailed error messages
2. **Test configuration**: Use demo script to validate setup
3. **Hardware verification**: Test with standard stimulators first
4. **Community support**: Ethoscope user community and documentation
