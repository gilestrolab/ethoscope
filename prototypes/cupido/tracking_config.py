#!/usr/bin/env python3
"""
Tracking Configuration for Cupido Offline Tracking

This module provides configuration management for different tracking scenarios,
including tracker parameters, genotype-specific settings, and machine-specific adjustments.

Usage:
    from tracking_config import TrackingConfig
    
    config = TrackingConfig()
    params = config.get_tracking_params('CS', 'trained')
    tracker_class = params['tracker_class']
    tracker_kwargs = params['tracker_kwargs']
"""

import json
import os
import sys
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Add ethoscope to path
sys.path.insert(0, '/home/gg/Data/ethoscope_project/ethoscope/src/ethoscope')

from ethoscope.trackers.adaptive_bg_tracker import AdaptiveBGModel

# Try to import optional trackers
try:
    from ethoscope.trackers.multi_fly_tracker import MultiFlyTracker
    MULTIFLY_AVAILABLE = True
except ImportError as e:
    print(f"Warning: MultiFlyTracker not available: {e}")
    MultiFlyTracker = None
    MULTIFLY_AVAILABLE = False


@dataclass
class TrackerParams:
    """Data class for tracker parameters."""
    tracker_class: type
    tracker_kwargs: Dict[str, Any]
    description: str = ""


class TrackingConfig:
    """
    Configuration manager for Cupido offline tracking.
    
    Provides different tracking configurations based on:
    - Genotype (CS, etc.)
    - Treatment group (trained, untrained)
    - Machine characteristics
    - Video quality parameters
    """
    
    def __init__(self, config_file: str = None):
        """
        Initialize tracking configuration.
        
        Args:
            config_file: Optional path to custom configuration JSON file
        """
        self.config_file = config_file
        self.config_data = self._load_config()
        
    def _load_config(self) -> Dict:
        """Load configuration from file or use defaults."""
        if self.config_file and os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load config file {self.config_file}: {e}")
                
        return self._get_default_config()
        
    def _get_default_config(self) -> Dict:
        """Get default tracking configuration."""
        return {
            "genotype_configs": {
                "CS": {
                    "description": "Canton-S wild type strain",
                    "default_tracker": "adaptive_bg",
                    "movement_threshold": 0.04,  # Optimized for mating behavior
                    "adaptive_alpha": 0.05,
                    "roi_specific": {
                        "trained": {
                            "movement_threshold": 0.04,
                            "adaptive_alpha": 0.06
                        },
                        "untrained": {
                            "movement_threshold": 0.05,
                            "adaptive_alpha": 0.05
                        }
                    }
                }
            },
            "tracker_configs": {
                "adaptive_bg": {
                    "class": "AdaptiveBGModel", 
                    "description": "Adaptive background subtraction tracker",
                    "default_params": {
                        "adaptive_alpha": 0.05,
                        "minimal_movement": 0.05,
                        "fg_data": {
                            "sample_size": 400,
                            "normal_limits": [50, 200],
                            "tolerance": 0.8
                        }
                    },
                    "optimizations": {
                        "high_activity": {
                            "adaptive_alpha": 0.08,
                            "minimal_movement": 0.03
                        },
                        "low_activity": {
                            "adaptive_alpha": 0.03,
                            "minimal_movement": 0.08
                        }
                    }
                },
                "multi_fly": {
                    "class": "MultiFlyTracker",
                    "description": "Multiple flies per ROI tracker",
                    "default_params": {
                        "maxN": 5,
                        "visualise": False,
                        "fg_data": {
                            "sample_size": 400,
                            "normal_limits": [50, 200],
                            "tolerance": 0.8
                        }
                    }
                }
            },
            "machine_configs": {
                "76": {
                    "description": "Ethoscope 76 specific settings",
                    "video_quality_adjustments": {
                        "brightness_correction": 0.0,
                        "contrast_multiplier": 1.0
                    }
                },
                "145": {
                    "description": "Ethoscope 145 specific settings", 
                    "video_quality_adjustments": {
                        "brightness_correction": 0.0,
                        "contrast_multiplier": 1.0
                    }
                },
                "139": {
                    "description": "Ethoscope 139 specific settings",
                    "video_quality_adjustments": {
                        "brightness_correction": 0.0,
                        "contrast_multiplier": 1.0
                    }
                },
                "268": {
                    "description": "Ethoscope 268 specific settings",
                    "video_quality_adjustments": {
                        "brightness_correction": 0.0,
                        "contrast_multiplier": 1.0
                    }
                }
            },
            "video_configs": {
                "1920x1088": {
                    "description": "Standard HD video resolution",
                    "preprocessing": {
                        "resize_factor": 1.0,
                        "gaussian_blur": 0
                    }
                }
            }
        }
        
    def save_config(self, filename: str = None):
        """Save current configuration to file."""
        if filename is None:
            filename = self.config_file or "cupido_tracking_config.json"
            
        try:
            with open(filename, 'w') as f:
                json.dump(self.config_data, f, indent=2)
            print(f"Configuration saved to {filename}")
        except Exception as e:
            print(f"Failed to save configuration: {e}")
            
    def get_tracker_class_by_name(self, tracker_name: str) -> type:
        """Get tracker class object by name."""
        tracker_classes = {
            'adaptive_bg': AdaptiveBGModel,
            'AdaptiveBGModel': AdaptiveBGModel,
        }
        
        # Add multi-fly tracker if available
        if MULTIFLY_AVAILABLE and MultiFlyTracker is not None:
            tracker_classes.update({
                'multi_fly': MultiFlyTracker,
                'MultiFlyTracker': MultiFlyTracker,
            })
        
        return tracker_classes.get(tracker_name, AdaptiveBGModel)
        
    def get_tracking_params(self, genotype: str, group: str = None, 
                           machine_name: str = None, 
                           tracker_override: str = None) -> TrackerParams:
        """
        Get tracking parameters for specific conditions.
        
        Args:
            genotype: Genotype identifier (e.g., 'CS')
            group: Treatment group (e.g., 'trained', 'untrained')
            machine_name: Machine identifier (e.g., '76')
            tracker_override: Force specific tracker
            
        Returns:
            TrackerParams object with tracker class and parameters
        """
        # Get genotype configuration
        genotype_config = self.config_data['genotype_configs'].get(genotype, {})
        
        # Determine tracker to use
        tracker_name = tracker_override or genotype_config.get('default_tracker', 'adaptive_bg')
        tracker_config = self.config_data['tracker_configs'].get(tracker_name, {})
        
        # Get base tracker parameters
        tracker_kwargs = tracker_config.get('default_params', {}).copy()
        
        # Apply genotype-specific adjustments
        if group and 'roi_specific' in genotype_config and group in genotype_config['roi_specific']:
            group_adjustments = genotype_config['roi_specific'][group]
            tracker_kwargs.update(group_adjustments)
            
        # Apply machine-specific adjustments
        if machine_name and machine_name in self.config_data['machine_configs']:
            machine_config = self.config_data['machine_configs'][machine_name]
            # Machine adjustments could modify tracker parameters here if needed
            
        # Get tracker class
        tracker_class = self.get_tracker_class_by_name(tracker_name)
        
        description = f"{genotype} genotype"
        if group:
            description += f", {group} group"
        if machine_name:
            description += f", machine {machine_name}"
        description += f", using {tracker_name} tracker"
        
        return TrackerParams(
            tracker_class=tracker_class,
            tracker_kwargs=tracker_kwargs,
            description=description
        )
        
    def get_available_trackers(self) -> Dict[str, str]:
        """Get list of available tracker configurations."""
        trackers = {}
        for name, config in self.config_data['tracker_configs'].items():
            trackers[name] = config.get('description', name)
        return trackers
        
    def get_available_genotypes(self) -> Dict[str, str]:
        """Get list of available genotype configurations."""
        genotypes = {}
        for name, config in self.config_data['genotype_configs'].items():
            genotypes[name] = config.get('description', name)
        return genotypes
        
    def get_machine_info(self, machine_name: str) -> Dict:
        """Get configuration information for a specific machine."""
        return self.config_data['machine_configs'].get(machine_name, {})
        
    def optimize_for_activity_level(self, params: TrackerParams, 
                                   activity_level: str) -> TrackerParams:
        """
        Optimize tracker parameters for specific activity level.
        
        Args:
            params: Base tracker parameters
            activity_level: 'high_activity', 'low_activity', or 'normal'
            
        Returns:
            Optimized TrackerParams
        """
        if activity_level == 'normal':
            return params
            
        # Find matching tracker configuration
        tracker_name = None
        for name, config in self.config_data['tracker_configs'].items():
            if self.get_tracker_class_by_name(name) == params.tracker_class:
                tracker_name = name
                break
                
        if not tracker_name:
            return params
            
        tracker_config = self.config_data['tracker_configs'][tracker_name]
        optimizations = tracker_config.get('optimizations', {})
        
        if activity_level in optimizations:
            optimized_kwargs = params.tracker_kwargs.copy()
            optimized_kwargs.update(optimizations[activity_level])
            
            return TrackerParams(
                tracker_class=params.tracker_class,
                tracker_kwargs=optimized_kwargs,
                description=params.description + f" (optimized for {activity_level})"
            )
            
        return params
        
    def print_summary(self):
        """Print configuration summary."""
        print(f"\n📋 Tracking Configuration Summary")
        
        print(f"\n🧬 Available Genotypes:")
        for genotype, desc in self.get_available_genotypes().items():
            print(f"   {genotype}: {desc}")
            
        print(f"\n🎯 Available Trackers:")
        for tracker, desc in self.get_available_trackers().items():
            print(f"   {tracker}: {desc}")
            
        print(f"\n🖥️  Configured Machines:")
        for machine, config in self.config_data['machine_configs'].items():
            desc = config.get('description', 'No description')
            print(f"   {machine}: {desc}")
            
    def create_experiment_config(self, genotype: str, group: str, 
                               machine_name: str) -> Dict:
        """
        Create a complete experiment configuration dictionary.
        
        Args:
            genotype: Genotype identifier
            group: Treatment group
            machine_name: Machine identifier
            
        Returns:
            Dictionary with complete experiment configuration
        """
        params = self.get_tracking_params(genotype, group, machine_name)
        
        return {
            'genotype': genotype,
            'group': group,
            'machine_name': machine_name,
            'tracker_class_name': params.tracker_class.__name__,
            'tracker_kwargs': params.tracker_kwargs,
            'description': params.description,
            'machine_config': self.get_machine_info(machine_name)
        }


def main():
    """Test the tracking configuration system."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Tracking Configuration Manager')
    parser.add_argument('--config', '-c', help='Configuration file path')
    parser.add_argument('--genotype', '-g', default='CS', help='Test genotype')
    parser.add_argument('--group', '-G', default='trained', help='Test group')
    parser.add_argument('--machine', '-m', default='76', help='Test machine')
    parser.add_argument('--save', '-s', help='Save config to file')
    
    args = parser.parse_args()
    
    # Create configuration manager
    config = TrackingConfig(args.config)
    
    # Print summary
    config.print_summary()
    
    # Test parameter generation
    print(f"\n🧪 Testing parameter generation:")
    params = config.get_tracking_params(args.genotype, args.group, args.machine)
    print(f"   Configuration: {params.description}")
    print(f"   Tracker class: {params.tracker_class.__name__}")
    print(f"   Parameters: {json.dumps(params.tracker_kwargs, indent=4)}")
    
    # Test experiment configuration
    print(f"\n⚗️  Complete experiment configuration:")
    exp_config = config.create_experiment_config(args.genotype, args.group, args.machine)
    print(json.dumps(exp_config, indent=2))
    
    # Save configuration if requested
    if args.save:
        config.save_config(args.save)


if __name__ == "__main__":
    main()