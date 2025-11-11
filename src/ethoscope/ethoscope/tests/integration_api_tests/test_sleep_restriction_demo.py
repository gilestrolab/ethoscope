#!/usr/bin/env python3
# flake8: noqa: E402
"""
Demonstration script for the new sleep restriction functionality.

This script shows how to use the new DailyScheduler and mAGOSleepRestriction classes.
"""

import datetime
import os
import sys
import time
from unittest.mock import Mock

# Add the ethoscope package to the path
sys.path.insert(0, "src/ethoscope")

from ethoscope.stimulators.sleep_restriction_stimulators import (
    SimpleTimeRestrictedStimulator,
)
from ethoscope.stimulators.sleep_restriction_stimulators import mAGOSleepRestriction
from ethoscope.utils.scheduler import DailyScheduleError
from ethoscope.utils.scheduler import DailyScheduler


def demo_daily_scheduler():
    """Demonstrate DailyScheduler functionality."""
    print("=" * 60)
    print("DAILY SCHEDULER DEMONSTRATION")
    print("=" * 60)

    # Example 1: 8 hours active per day starting at 9 AM
    print("\n1. Daily Schedule: 8 hours active starting at 9 AM")
    print("-" * 50)

    scheduler = DailyScheduler(
        daily_duration_hours=8, interval_hours=24, daily_start_time="09:00:00"
    )

    info = scheduler.get_schedule_info()
    print(
        f"Configuration: {info['daily_duration_hours']}h active every {info['interval_hours']}h"
    )
    print(f"Daily start time: {info['daily_start_time']}")
    print(f"Currently active: {info['currently_active']}")
    print(f"Next period: {info['next_period_start']} - {info['next_period_end']}")

    if info["currently_active"]:
        print(f"Time remaining: {info['remaining_active_seconds'] / 3600:.1f} hours")
    else:
        print(
            f"Time until next period: {info['seconds_until_next_period'] / 3600:.1f} hours"
        )

    # Example 2: Twice daily schedule (12-hour intervals)
    print("\n2. Twice Daily Schedule: 6 hours active every 12 hours starting at 6 AM")
    print("-" * 70)

    scheduler2 = DailyScheduler(
        daily_duration_hours=6, interval_hours=12, daily_start_time="06:00:00"
    )

    info2 = scheduler2.get_schedule_info()
    print(
        f"Configuration: {info2['daily_duration_hours']}h active every {info2['interval_hours']}h"
    )
    print(f"Currently active: {info2['currently_active']}")
    print(f"Next period: {info2['next_period_start']} - {info2['next_period_end']}")

    # Test specific times
    print("\n3. Testing Specific Times")
    print("-" * 30)

    # Create test times for today
    now = datetime.datetime.now()
    today_base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    test_times = [
        ("8:00 AM", today_base.replace(hour=8)),
        ("9:00 AM", today_base.replace(hour=9)),
        ("12:00 PM", today_base.replace(hour=12)),
        ("5:00 PM", today_base.replace(hour=17)),
        ("6:00 PM", today_base.replace(hour=18)),
    ]

    for time_name, test_time in test_times:
        timestamp = test_time.timestamp()
        is_active = scheduler.is_active_period(timestamp)
        print(f"{time_name:10} -> {'ACTIVE' if is_active else 'inactive'}")


def demo_sleep_restriction_stimulator():
    """Demonstrate mAGOSleepRestriction stimulator."""
    print("\n" + "=" * 60)
    print("SLEEP RESTRICTION STIMULATOR DEMONSTRATION")
    print("=" * 60)

    # Create mock hardware connection
    mock_hardware = Mock()
    print("Created mock hardware connection")

    # Example 1: Standard sleep restriction (8 hours per day)
    print("\n1. Standard Sleep Restriction (8h/day starting at 9 AM)")
    print("-" * 55)

    stimulator = mAGOSleepRestriction(
        hardware_connection=mock_hardware,
        daily_duration_hours=8,
        interval_hours=24,
        daily_start_time="09:00:00",
        stimulus_type=1,  # motor
        state_dir="/tmp/ethoscope_demo",
    )

    status = stimulator.get_schedule_status()
    print(f"Overall experiment active: {status['overall_experiment_active']}")
    print(f"Daily schedule active: {status['daily_schedule']['currently_active']}")
    print(f"Fully active: {status['fully_active']}")
    print(f"Status: {status['status']}")

    # Example 2: Intensive restriction (4 hours every 8 hours)
    print("\n2. Intensive Sleep Restriction (4h every 8h starting at 6 AM)")
    print("-" * 58)

    stimulator2 = mAGOSleepRestriction(
        hardware_connection=mock_hardware,
        daily_duration_hours=4,
        interval_hours=8,
        daily_start_time="06:00:00",
        stimulus_type=2,  # valves
        state_dir="/tmp/ethoscope_demo",
    )

    status2 = stimulator2.get_schedule_status()
    print("Configuration: 4h active every 8h")
    print(f"Fully active: {status2['fully_active']}")
    print(f"Status: {status2['status']}")


def demo_simple_time_restricted_stimulator():
    """Demonstrate SimpleTimeRestrictedStimulator with presets."""
    print("\n" + "=" * 60)
    print("SIMPLE TIME RESTRICTED STIMULATOR DEMONSTRATION")
    print("=" * 60)

    mock_hardware = Mock()

    # Test all preset patterns
    patterns = [
        (1, "8 hours active per day"),
        (2, "12 hours active per day"),
        (3, "6 hours active twice per day"),
        (4, "4 hours active three times per day"),
    ]

    for pattern_num, description in patterns:
        print(f"\nPattern {pattern_num}: {description}")
        print("-" * (15 + len(description)))

        stimulator = SimpleTimeRestrictedStimulator(
            hardware_connection=mock_hardware,
            restriction_pattern=pattern_num,
            daily_start_time="09:00:00",
            state_dir="/tmp/ethoscope_demo",
        )

        pattern_info = stimulator.get_pattern_info()
        print(f"Duration: {pattern_info['daily_duration_hours']}h")
        print(f"Interval: {pattern_info['interval_hours']}h")
        print(f"Start time: {pattern_info['daily_start_time']}")
        print(f"Description: {pattern_info['pattern_description']}")

        status = stimulator.get_schedule_status()
        print(f"Currently active: {status['daily_schedule']['currently_active']}")

    # Custom pattern example
    print("\nPattern 5: Custom (10h every 16h)")
    print("-" * 35)

    custom_stimulator = SimpleTimeRestrictedStimulator(
        hardware_connection=mock_hardware,
        restriction_pattern=5,
        custom_duration_hours=10,
        custom_interval_hours=16,
        daily_start_time="08:00:00",
        state_dir="/tmp/ethoscope_demo",
    )

    custom_info = custom_stimulator.get_pattern_info()
    print(f"Custom configuration: {custom_info['pattern_description']}")


def demo_error_handling():
    """Demonstrate error handling and validation."""
    print("\n" + "=" * 60)
    print("ERROR HANDLING DEMONSTRATION")
    print("=" * 60)

    print("\n1. Testing Invalid DailyScheduler Parameters")
    print("-" * 45)

    invalid_configs = [
        (25, 24, "09:00:00", "Duration > 24 hours"),
        (8, 6, "09:00:00", "Duration > interval"),
        (8, 24, "25:00:00", "Invalid time format"),
        (0, 24, "09:00:00", "Zero duration"),
    ]

    for duration, interval, start_time, error_desc in invalid_configs:
        try:
            DailyScheduler(duration, interval, start_time)
            print(f"✗ {error_desc}: Should have failed but didn't!")
        except (DailyScheduleError, ValueError) as e:
            print(f"✓ {error_desc}: Correctly caught - {e}")
        except Exception as e:
            print(f"? {error_desc}: Unexpected error - {e}")


def main():
    """Run all demonstrations."""
    print("Sleep Restriction System Demonstration")
    print("=" * 60)
    print("This script demonstrates the new sleep restriction functionality")
    print("added to the Ethoscope system.")

    # Create demo directory
    os.makedirs("/tmp/ethoscope_demo", exist_ok=True)

    try:
        demo_daily_scheduler()
        demo_sleep_restriction_stimulator()
        demo_simple_time_restricted_stimulator()
        demo_error_handling()

        print("\n" + "=" * 60)
        print("DEMONSTRATION COMPLETE")
        print("=" * 60)
        print("\nKey Features Demonstrated:")
        print("• DailyScheduler with flexible time windows")
        print("• mAGOSleepRestriction inheriting from mAGO")
        print("• SimpleTimeRestrictedStimulator with presets")
        print("• State persistence and error handling")
        print("• Web interface integration ready")

        print("\nDemo state files created in: /tmp/ethoscope_demo/")

    except Exception as e:
        print(f"\nError during demonstration: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Clean up demo directory
        import shutil

        if os.path.exists("/tmp/ethoscope_demo"):
            shutil.rmtree("/tmp/ethoscope_demo")
            print("Cleaned up demo files.")


if __name__ == "__main__":
    main()
