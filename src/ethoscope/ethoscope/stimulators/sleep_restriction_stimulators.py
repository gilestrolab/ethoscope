"""
Sleep Restriction Stimulators

This module contains stimulators designed for sleep restriction experiments,
providing daily time-limited operation with flexible scheduling.
"""

__author__ = 'giorgio'

import logging
import os
from ethoscope.stimulators.sleep_depriver_stimulators import mAGO
from ethoscope.stimulators.stimulators import HasInteractedVariable
from ethoscope.utils.scheduler import DailyScheduler, DailyScheduleError


class mAGOSleepRestriction(mAGO):
    """
    Sleep restriction stimulator using mAGO hardware with daily time limitations.
    
    This stimulator extends mAGO functionality to operate only N hours per day
    at user-specified intervals, designed for controlled sleep restriction experiments.
    
    Key features:
    - Daily time windows (e.g., 8 hours active per day)
    - Flexible scheduling (e.g., twice daily for 4 hours each)
    - State persistence across system restarts
    - Inherits all mAGO motor/valve capabilities
    """
    
    _description = {
        "overview": "Sleep restriction using mAGO hardware - operates N hours per day at specified intervals",
        "arguments": [
            # Inherit mAGO base arguments
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.0001, "name": "velocity_correction_coef", 
             "description": "Velocity correction coefficient", "default": 3.0e-3},
            {"type": "number", "min": 1, "max": 3600*12, "step": 1, "name": "min_inactive_time", 
             "description": "Minimal time after which inactive animal is stimulated (s)", "default": 120},
            {"type": "number", "min": 50, "max": 10000, "step": 50, "name": "pulse_duration", 
             "description": "Duration of stimulus delivery (ms)", "default": 1000},
            {"type": "number", "min": 1, "max": 2, "step": 1, "name": "stimulus_type", 
             "description": "1 = motor, 2 = valves", "default": 1},
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.1, "name": "stimulus_probability", 
             "description": "Probability the stimulus will happen", "default": 1.0},
            
            # Sleep restriction specific arguments
            {"type": "number", "min": 1, "max": 24, "step": 0.5, "name": "daily_duration_hours", 
             "description": "Hours active per day", "default": 8},
            {"type": "number", "min": 1, "max": 168, "step": 0.5, "name": "interval_hours", 
             "description": "Hours between active periods", "default": 24},
            {"type": "time", "name": "daily_start_time", 
             "description": "Daily start time (HH:MM:SS)", "default": "09:00:00"},
            
            # Standard date range for overall experiment duration
            {"type": "date_range", "name": "date_range",
             "description": "Overall experiment time period", 
             "default": ""}
        ]
    }
    
    def __init__(self, 
                 hardware_connection,
                 velocity_correction_coef=3.0e-3,
                 min_inactive_time=120,
                 pulse_duration=1000,
                 stimulus_type=1,  # 1 = motor, 2 = valves
                 stimulus_probability=1.0,
                 daily_duration_hours=8,
                 interval_hours=24,
                 daily_start_time="09:00:00",
                 date_range="",
                 roi_template_config=None,
                 state_dir="/tmp/ethoscope_sleep_restriction"):
        """
        Initialize sleep restriction stimulator based on mAGO.
        
        Args:
            hardware_connection: mAGO hardware interface
            velocity_correction_coef (float): Velocity correction coefficient
            min_inactive_time (int): Seconds of inactivity before stimulation
            pulse_duration (int): Stimulus duration in milliseconds
            stimulus_type (int): 1 for motor, 2 for valves
            stimulus_probability (float): Probability of stimulus delivery (0-1)
            daily_duration_hours (float): Hours active per day
            interval_hours (float): Hours between active periods
            daily_start_time (str): Daily start time in HH:MM:SS format
            date_range (str): Overall experiment date range
            roi_template_config (dict): ROI template configuration
            state_dir (str): Directory for state persistence files
        """
        
        # Initialize parent mAGO stimulator
        super(mAGOSleepRestriction, self).__init__(
            hardware_connection=hardware_connection,
            velocity_correction_coef=velocity_correction_coef,
            min_inactive_time=min_inactive_time,
            pulse_duration=pulse_duration,
            stimulus_type=stimulus_type,  
            stimulus_probability=stimulus_probability,
            date_range=date_range,
            roi_template_config=roi_template_config
        )
        
        # Store sleep restriction parameters
        self._daily_duration_hours = daily_duration_hours
        self._interval_hours = interval_hours
        self._daily_start_time = daily_start_time
        self._state_dir = state_dir
        
        # Initialize daily scheduler
        try:
            # Create state file path (will be unique per ROI when tracker is bound)
            os.makedirs(state_dir, exist_ok=True)
            self._state_file_path = None  # Will be set when tracker is bound
            
            self._daily_scheduler = DailyScheduler(
                daily_duration_hours=daily_duration_hours,
                interval_hours=interval_hours,
                daily_start_time=daily_start_time,
                state_file_path=self._state_file_path  # Initially None
            )
            
            logging.info(f"mAGOSleepRestriction initialized: {daily_duration_hours}h/{interval_hours}h "
                        f"starting at {daily_start_time}, stimulus_type={stimulus_type}")
                        
        except DailyScheduleError as e:
            logging.error(f"Invalid daily schedule configuration: {e}")
            raise
    
    def bind_tracker(self, tracker):
        """
        Bind tracker and set up ROI-specific state file.
        
        Args:
            tracker: Tracker object providing animal position data
        """
        # Call parent bind_tracker first
        super(mAGOSleepRestriction, self).bind_tracker(tracker)
        
        # Set up ROI-specific state file
        if tracker and hasattr(tracker, '_roi') and tracker._roi:
            roi_id = tracker._roi.idx
            self._state_file_path = os.path.join(
                self._state_dir, 
                f"sleep_restriction_roi_{roi_id}.json"
            )
            
            # Update daily scheduler with state file path
            self._daily_scheduler._state_file_path = self._state_file_path
            self._daily_scheduler._state = self._daily_scheduler._load_state()
            
            logging.info(f"Sleep restriction state file set for ROI {roi_id}: {self._state_file_path}")
    
    def apply(self):
        """
        Apply sleep restriction stimulation with daily time limits.
        
        This method extends the base mAGO apply() method by adding daily
        scheduling constraints before executing standard sleep deprivation logic.
        
        Returns:
            tuple: (HasInteractedVariable, result_dict) indicating stimulation outcome
        """
        # First check overall experiment date range (from base Scheduler)
        if self._scheduler.check_time_range() is False:
            return HasInteractedVariable(False), {}
        
        # Then check daily scheduling constraints
        if not self._daily_scheduler.is_active_period():
            return HasInteractedVariable(False), {}
        
        # Execute normal mAGO stimulation logic during active periods
        return super(mAGOSleepRestriction, self).apply()
    
    def get_schedule_status(self):
        """
        Get current schedule status information.
        
        Returns:
            dict: Comprehensive scheduling information including:
                - Overall experiment schedule status
                - Daily restriction schedule status  
                - Time until next active period
                - Remaining time in current period
        """
        overall_active = self._scheduler.check_time_range()
        daily_info = self._daily_scheduler.get_schedule_info()
        
        status = {
            'overall_experiment_active': overall_active,
            'daily_schedule': daily_info,
            'fully_active': overall_active and daily_info['currently_active']
        }
        
        # Add human-readable status
        if not overall_active:
            status['status'] = 'Experiment not in active date range'
        elif not daily_info['currently_active']:
            next_period_hours = daily_info['seconds_until_next_period'] / 3600
            status['status'] = f'Waiting for next active period in {next_period_hours:.1f} hours'
        else:
            remaining_hours = daily_info['remaining_active_seconds'] / 3600
            status['status'] = f'Active - {remaining_hours:.1f} hours remaining'
        
        return status
    
    def get_daily_activity_log(self):
        """
        Get log of daily activity periods.
        
        Returns:
            dict: Activity log with period information
        """
        if not hasattr(self._daily_scheduler, '_state'):
            return {}
            
        return {
            'state_file': self._state_file_path,
            'activity_periods': self._daily_scheduler._state
        }


class SimpleTimeRestrictedStimulator(mAGOSleepRestriction):
    """
    Simplified version of sleep restriction stimulator with preset configurations.
    
    This class provides common sleep restriction patterns as presets for ease of use.
    """
    
    _description = {
        "overview": "Simplified sleep restriction with preset patterns",
        "arguments": [
            {"type": "number", "min": 0.0, "max": 1.0, "step": 0.0001, "name": "velocity_correction_coef", 
             "description": "Velocity correction coefficient", "default": 3.0e-3},
            {"type": "number", "min": 1, "max": 3600*12, "step": 1, "name": "min_inactive_time", 
             "description": "Minimal time after which inactive animal is stimulated (s)", "default": 120},
            {"type": "number", "min": 1, "max": 2, "step": 1, "name": "stimulus_type", 
             "description": "1 = motor, 2 = valves", "default": 1},
            
            # Preset patterns
            {"type": "number", "min": 1, "max": 5, "step": 1, "name": "restriction_pattern",
             "description": "1=8h/day, 2=12h/day, 3=6h twice/day, 4=4h three times/day, 5=custom", "default": 1},
            {"type": "time", "name": "daily_start_time", 
             "description": "Daily start time (HH:MM:SS)", "default": "09:00:00"},
             
            # Custom pattern (only used if restriction_pattern=5)
            {"type": "number", "min": 1, "max": 24, "step": 0.5, "name": "custom_duration_hours", 
             "description": "Custom hours active per day (pattern 5 only)", "default": 8},
            {"type": "number", "min": 1, "max": 168, "step": 0.5, "name": "custom_interval_hours", 
             "description": "Custom hours between periods (pattern 5 only)", "default": 24},
             
            {"type": "date_range", "name": "date_range",
             "description": "Overall experiment time period", "default": ""}
        ]
    }
    
    # Preset patterns: (duration_hours, interval_hours, description)
    _PATTERNS = {
        1: (8, 24, "8 hours active per day"),
        2: (12, 24, "12 hours active per day"), 
        3: (6, 12, "6 hours active twice per day"),
        4: (4, 8, "4 hours active three times per day"),
        5: (None, None, "Custom pattern")  # Will use custom parameters
    }
    
    def __init__(self,
                 hardware_connection,
                 velocity_correction_coef=3.0e-3,
                 min_inactive_time=120,
                 stimulus_type=1,
                 restriction_pattern=1,
                 daily_start_time="09:00:00",
                 custom_duration_hours=8,
                 custom_interval_hours=24,
                 date_range="",
                 roi_template_config=None,
                 **kwargs):
        """
        Initialize simplified sleep restriction stimulator.
        
        Args:
            restriction_pattern (int): Preset pattern (1-5)
            custom_duration_hours (float): Used only if pattern=5
            custom_interval_hours (float): Used only if pattern=5
            Other args: Same as mAGOSleepRestriction
        """
        
        # Get pattern configuration
        if restriction_pattern not in self._PATTERNS:
            raise ValueError(f"Invalid restriction_pattern: {restriction_pattern}. Must be 1-5.")
        
        duration, interval, description = self._PATTERNS[restriction_pattern]
        
        if restriction_pattern == 5:  # Custom pattern
            duration = custom_duration_hours
            interval = custom_interval_hours
            description = f"Custom: {duration}h every {interval}h"
        
        logging.info(f"Using restriction pattern {restriction_pattern}: {description}")
        
        # Initialize parent with pattern parameters
        super(SimpleTimeRestrictedStimulator, self).__init__(
            hardware_connection=hardware_connection,
            velocity_correction_coef=velocity_correction_coef,
            min_inactive_time=min_inactive_time,
            pulse_duration=1000,  # Fixed default
            stimulus_type=stimulus_type,
            stimulus_probability=1.0,  # Fixed default
            daily_duration_hours=duration,
            interval_hours=interval,
            daily_start_time=daily_start_time,
            date_range=date_range,
            roi_template_config=roi_template_config,
            **kwargs
        )
        
        self._pattern_description = description
    
    def get_pattern_info(self):
        """
        Get information about the selected restriction pattern.
        
        Returns:
            dict: Pattern information
        """
        return {
            'pattern_description': self._pattern_description,
            'daily_duration_hours': self._daily_duration_hours,
            'interval_hours': self._interval_hours,
            'daily_start_time': self._daily_start_time
        }