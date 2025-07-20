"""
Multi-stimulator system for sequential stimulator activation.
Allows multiple stimulators with individual date/time ranges within a single experiment.
"""

__author__ = 'giorgio'

import logging
from ethoscope.stimulators.stimulators import BaseStimulator, HasInteractedVariable, DefaultStimulator
from ethoscope.hardware.interfaces.interfaces import DefaultInterface
from ethoscope.utils.scheduler import Scheduler

# Global flag to track if MultiStimulator has been logged before
_MULTISTIMULATOR_LOGGED = set()


class MultiStimulator(BaseStimulator):
    """
    A meta-stimulator that manages multiple stimulators with individual date/time ranges.
    Allows sequential activation of different stimulator types during an experiment.
    """
    
    _description = {
        "overview": "A meta-stimulator that manages multiple stimulators with individual date/time ranges",
        "arguments": [
            {
                "type": "stimulator_sequence", 
                "name": "stimulator_sequence",
                "description": "Sequence of stimulators with their configurations and date ranges",
                "hidden": True,
                "default": []
            }
        ]
    }
    
    _HardwareInterfaceClass = DefaultInterface
    
    def __init__(self, hardware_connection, stimulator_sequence=None, roi_template_config=None):
        """
        Initialize MultiStimulator with a sequence of stimulator configurations.
        
        Args:
            hardware_connection: The hardware interface connection
            stimulator_sequence: List of stimulator configurations, each containing:
                - class_name: Name of the stimulator class
                - arguments: Dictionary of arguments for the stimulator
                - date_range: Date/time range when this stimulator should be active
            roi_template_config: ROI template configuration
        """
        # Initialize with empty date_range since we manage our own scheduling
        super(MultiStimulator, self).__init__(hardware_connection, date_range="", roi_template_config=roi_template_config)
        
        self._stimulator_configs = stimulator_sequence or []
        self._active_stimulators = []
        self._hardware_connection = hardware_connection
        self._roi_template_config = roi_template_config
        self._stimulators = []
        self._initialized = False
        
        # Initialize all stimulators
        self._initialize_stimulators()
        
        # Track last active stimulator for logging
        self._last_active_stimulator = None
        
    def _initialize_stimulators(self):
        """
        Initialize all stimulators from the configuration sequence.
        """
        if self._initialized:
            logging.debug("Stimulators already initialized, skipping")
            return
        
        # Create a unique key for this configuration to prevent duplicate logging
        config_key = str(sorted([(c.get('class_name', ''), c.get('date_range', '')) for c in self._stimulator_configs]))
        
        if config_key not in _MULTISTIMULATOR_LOGGED:
            logging.info(f"Initializing MultiStimulator with {len(self._stimulator_configs)} stimulator(s)")
            _MULTISTIMULATOR_LOGGED.add(config_key)
        else:
            logging.debug(f"MultiStimulator with same config already logged, creating instance silently")
        from ethoscope.stimulators.sleep_depriver_stimulators import (
            SleepDepStimulator, OptomotorSleepDepriver, MiddleCrossingStimulator,
            ExperimentalSleepDepStimulator, OptomotorSleepDepriverSystematic, mAGO, AGO
        )
        from ethoscope.stimulators.odour_stimulators import (
            DynamicOdourSleepDepriver, MiddleCrossingOdourStimulator, 
            MiddleCrossingOdourStimulatorFlushed
        )
        from ethoscope.stimulators.optomotor_stimulators import OptoMidlineCrossStimulator
        from ethoscope.stimulators.stimulators import DefaultStimulator
        
        # Map class names to actual classes
        stimulator_classes = {
            'DefaultStimulator': DefaultStimulator,
            'SleepDepStimulator': SleepDepStimulator,
            'OptomotorSleepDepriver': OptomotorSleepDepriver,
            'MiddleCrossingStimulator': MiddleCrossingStimulator,
            'ExperimentalSleepDepStimulator': ExperimentalSleepDepStimulator,
            'DynamicOdourSleepDepriver': DynamicOdourSleepDepriver,
            'OptoMidlineCrossStimulator': OptoMidlineCrossStimulator,
            'OptomotorSleepDepriverSystematic': OptomotorSleepDepriverSystematic,
            'MiddleCrossingOdourStimulator': MiddleCrossingOdourStimulator,
            'MiddleCrossingOdourStimulatorFlushed': MiddleCrossingOdourStimulatorFlushed,
            'mAGO': mAGO,
            'AGO': AGO
        }
        
        # Reset stimulators list
        self._stimulators = []
        
        for config in self._stimulator_configs:
            class_name = config.get('class_name', '')
            arguments = config.get('arguments', {})
            date_range = config.get('date_range', '')
            
            if class_name not in stimulator_classes:
                logging.error(f"Unknown stimulator class: {class_name}")
                continue
                
            StimulatorClass = stimulator_classes[class_name]
            
            try:
                # Create stimulator instance with its specific date_range
                stimulator = StimulatorClass(
                    hardware_connection=self._hardware_connection,
                    date_range=date_range,
                    roi_template_config=self._roi_template_config,
                    **arguments
                )
                
                self._stimulators.append({
                    'instance': stimulator,
                    'class_name': class_name,
                    'date_range': date_range,
                    'scheduler': Scheduler(date_range)
                })
                
                # Only log individual stimulator initialization if this is the first instance for this config
                if config_key not in _MULTISTIMULATOR_LOGGED or len(_MULTISTIMULATOR_LOGGED) == 1:
                    logging.info(f"Initialized stimulator {class_name} with date_range: {date_range}")
                logging.debug(f"Stimulator config: {config}")
                
            except Exception as e:
                logging.error(f"Failed to initialize stimulator {class_name}: {e}")
                continue
        
        self._initialized = True
        # Only log completion message for the first instance of this configuration
        if config_key not in _MULTISTIMULATOR_LOGGED or len(_MULTISTIMULATOR_LOGGED) == 1:
            logging.info(f"MultiStimulator initialization complete: {len(self._stimulators)} stimulator(s) ready")
    
    def bind_tracker(self, tracker):
        """
        Bind tracker to all managed stimulators.
        
        Args:
            tracker: The tracker object to bind
        """
        super(MultiStimulator, self).bind_tracker(tracker)
        
        # Bind tracker to all individual stimulators
        for stimulator_info in self._stimulators:
            stimulator_info['instance'].bind_tracker(tracker)
    
    def _decide(self):
        """
        Decide which stimulator(s) should be active and delegate to them.
        
        Returns:
            tuple: (interaction_result, result_dict)
        """
        if not self._stimulators:
            return HasInteractedVariable(False), {}
        
        # Find currently active stimulators based on their date ranges
        active_stimulators = []
        for stimulator_info in self._stimulators:
            if stimulator_info['scheduler'].check_time_range():
                active_stimulators.append(stimulator_info)
        
        # Log stimulator transitions
        current_active_names = [s['class_name'] for s in active_stimulators]
        if current_active_names != self._last_active_stimulator:
            if current_active_names:
                logging.info(f"Active stimulators: {', '.join(current_active_names)}")
            else:
                logging.info("No stimulators currently active")
            self._last_active_stimulator = current_active_names.copy()
        
        # If no stimulators are active, return no interaction
        if not active_stimulators:
            return HasInteractedVariable(False), {}
        
        # If multiple stimulators are active, use the first one (could be enhanced to support parallel execution)
        # For now, we implement a "first wins" policy when ranges overlap
        active_stimulator = active_stimulators[0]['instance']
        
        # Delegate decision to the active stimulator
        try:
            interaction_result, result_dict = active_stimulator._decide()
            
            # Add metadata about which stimulator made the decision
            if isinstance(result_dict, dict):
                result_dict['active_stimulator'] = active_stimulators[0]['class_name']
            
            return interaction_result, result_dict
            
        except Exception as e:
            logging.error(f"Error in stimulator {active_stimulators[0]['class_name']}: {e}")
            return HasInteractedVariable(False), {}
    
    def _deliver(self, **kwargs):
        """
        Deliver stimulation using the hardware connection.
        
        Args:
            **kwargs: Arguments to pass to hardware interface
        """
        if self._hardware_connection is not None:
            # Remove metadata before sending to hardware
            hardware_kwargs = {k: v for k, v in kwargs.items() if k != 'active_stimulator'}
            self._hardware_connection.send_instruction(hardware_kwargs)
    
    def get_active_stimulators(self):
        """
        Get list of currently active stimulator names.
        
        Returns:
            list: Names of currently active stimulators
        """
        active = []
        for stimulator_info in self._stimulators:
            if stimulator_info['scheduler'].check_time_range():
                active.append(stimulator_info['class_name'])
        return active
    
    def get_stimulator_info(self):
        """
        Get information about all configured stimulators.
        
        Returns:
            list: List of stimulator information dictionaries
        """
        info = []
        for stimulator_info in self._stimulators:
            info.append({
                'class_name': stimulator_info['class_name'],
                'date_range': stimulator_info['date_range'],
                'is_active': stimulator_info['scheduler'].check_time_range()
            })
        return info