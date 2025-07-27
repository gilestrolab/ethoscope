"""
Target Detection Analysis Module for Node

This module provides node-side analysis capabilities for target detection data
collected from ethoscope devices, including failure pattern analysis, dataset
management, and reporting functionality.
"""

__author__ = 'giorgio'

import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import numpy as np


class TargetDetectionAnalyzer:
    """
    Analyzes collected target detection data from multiple ethoscope devices.
    
    This class processes diagnostic data collected by ethoscope devices to identify
    failure patterns, generate reports, and manage the diagnostic dataset.
    """
    
    def __init__(self, base_path: str = "/ethoscope_data/various/target_detection_logs"):
        """
        Initialize analyzer with path to diagnostic data.
        
        Args:
            base_path: Base directory containing diagnostic data from devices
        """
        self.base_path = Path(base_path)
        self.logger = logging.getLogger(__name__)
        
        # Ensure analysis directory exists
        self.reports_dir = self.base_path / "analysis_reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
    
    def analyze_detection_logs(self, days_back: int = 30) -> Dict[str, Any]:
        """
        Analyze detection logs from the last N days.
        
        Args:
            days_back: Number of days to analyze (default: 30)
            
        Returns:
            Dictionary containing comprehensive analysis results
        """
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        failed_data = self._load_detection_data("failed", cutoff_date)
        success_data = self._load_detection_data("success", cutoff_date)
        
        analysis = {
            "analysis_period": {
                "start_date": cutoff_date.isoformat(),
                "end_date": datetime.now().isoformat(),
                "days_analyzed": days_back
            },
            "summary": self._generate_summary_stats(failed_data, success_data),
            "failure_patterns": self._analyze_failure_patterns(failed_data),
            "device_performance": self._analyze_device_performance(failed_data, success_data),
            "lighting_analysis": self._analyze_lighting_conditions(failed_data, success_data),
            "recommendations": self._generate_recommendations(failed_data, success_data)
        }
        
        self.logger.info(f"Analyzed {len(failed_data)} failed and {len(success_data)} successful detections")
        return analysis
    
    def _load_detection_data(self, subdir: str, cutoff_date: datetime) -> List[Dict[str, Any]]:
        """Load detection metadata from specified subdirectory."""
        data_dir = self.base_path / subdir
        detection_data = []
        
        if not data_dir.exists():
            return detection_data
        
        for metadata_file in data_dir.glob("*_metadata.json"):
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                # Parse timestamp
                timestamp = datetime.fromisoformat(metadata.get("timestamp", ""))
                if timestamp >= cutoff_date:
                    metadata["parsed_timestamp"] = timestamp
                    detection_data.append(metadata)
                    
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                self.logger.warning(f"Skipping invalid metadata file {metadata_file}: {e}")
        
        return detection_data
    
    def _generate_summary_stats(self, failed_data: List[Dict], success_data: List[Dict]) -> Dict[str, Any]:
        """Generate overall summary statistics."""
        total_attempts = len(failed_data) + len(success_data)
        success_rate = len(success_data) / total_attempts if total_attempts > 0 else 0
        
        # Device counts
        failed_devices = set(d.get("device_id", "unknown") for d in failed_data)
        success_devices = set(d.get("device_id", "unknown") for d in success_data)
        all_devices = failed_devices | success_devices
        
        return {
            "total_detection_attempts": total_attempts,
            "successful_detections": len(success_data),
            "failed_detections": len(failed_data),
            "overall_success_rate": success_rate,
            "devices_with_failures": len(failed_devices),
            "devices_with_successes": len(success_devices),
            "total_devices": len(all_devices),
            "devices_analyzed": sorted(list(all_devices))
        }
    
    def _analyze_failure_patterns(self, failed_data: List[Dict]) -> Dict[str, Any]:
        """Analyze patterns in detection failures."""
        if not failed_data:
            return {"no_failures": True}
        
        # Failure reasons analysis
        targets_found_counts = {}
        brightness_ranges = {"very_dark": 0, "dark": 0, "normal": 0, "bright": 0, "very_bright": 0}
        contrast_issues = 0
        
        for failure in failed_data:
            targets_found = failure.get("targets_found", 0)
            targets_found_counts[targets_found] = targets_found_counts.get(targets_found, 0) + 1
            
            image_quality = failure.get("image_quality", {})
            brightness = image_quality.get("mean_brightness", 128)
            contrast = image_quality.get("contrast_rms", 0)
            
            # Categorize brightness
            if brightness < 30:
                brightness_ranges["very_dark"] += 1
            elif brightness < 80:
                brightness_ranges["dark"] += 1
            elif brightness < 180:
                brightness_ranges["normal"] += 1
            elif brightness < 220:
                brightness_ranges["bright"] += 1
            else:
                brightness_ranges["very_bright"] += 1
            
            # Check for contrast issues
            if contrast < 20:
                contrast_issues += 1
        
        # Most common failure types
        most_common_targets_found = max(targets_found_counts.items(), key=lambda x: x[1]) if targets_found_counts else (0, 0)
        
        return {
            "total_failures": len(failed_data),
            "targets_found_distribution": targets_found_counts,
            "most_common_targets_found": most_common_targets_found[0],
            "brightness_distribution": brightness_ranges,
            "low_contrast_failures": contrast_issues,
            "low_contrast_percentage": contrast_issues / len(failed_data) * 100
        }
    
    def _analyze_device_performance(self, failed_data: List[Dict], success_data: List[Dict]) -> Dict[str, Any]:
        """Analyze performance by individual device."""
        device_stats = {}
        
        # Process all data
        for data_list, result_type in [(failed_data, "failed"), (success_data, "success")]:
            for record in data_list:
                device_id = record.get("device_id", "unknown")
                
                if device_id not in device_stats:
                    device_stats[device_id] = {"failed": 0, "success": 0}
                
                device_stats[device_id][result_type] += 1
        
        # Calculate success rates and identify problematic devices
        device_performance = {}
        problematic_devices = []
        
        for device_id, stats in device_stats.items():
            total = stats["failed"] + stats["success"]
            success_rate = stats["success"] / total if total > 0 else 0
            
            device_performance[device_id] = {
                "total_attempts": total,
                "successful": stats["success"],
                "failed": stats["failed"],
                "success_rate": success_rate
            }
            
            # Flag devices with low success rates (< 80%) and sufficient data (>= 5 attempts)
            if success_rate < 0.8 and total >= 5:
                problematic_devices.append({
                    "device_id": device_id,
                    "success_rate": success_rate,
                    "total_attempts": total
                })
        
        return {
            "device_performance": device_performance,
            "problematic_devices": sorted(problematic_devices, key=lambda x: x["success_rate"]),
            "total_devices_analyzed": len(device_stats)
        }
    
    def _analyze_lighting_conditions(self, failed_data: List[Dict], success_data: List[Dict]) -> Dict[str, Any]:
        """Analyze lighting conditions in successful vs failed detections."""
        def extract_lighting_stats(data_list):
            brightness_values = []
            contrast_values = []
            
            for record in data_list:
                image_quality = record.get("image_quality", {})
                brightness = image_quality.get("mean_brightness")
                contrast = image_quality.get("contrast_rms")
                
                if brightness is not None:
                    brightness_values.append(brightness)
                if contrast is not None:
                    contrast_values.append(contrast)
            
            return {
                "brightness": {
                    "mean": np.mean(brightness_values) if brightness_values else 0,
                    "std": np.std(brightness_values) if brightness_values else 0,
                    "min": np.min(brightness_values) if brightness_values else 0,
                    "max": np.max(brightness_values) if brightness_values else 0,
                    "count": len(brightness_values)
                },
                "contrast": {
                    "mean": np.mean(contrast_values) if contrast_values else 0,
                    "std": np.std(contrast_values) if contrast_values else 0,
                    "min": np.min(contrast_values) if contrast_values else 0,
                    "max": np.max(contrast_values) if contrast_values else 0,
                    "count": len(contrast_values)
                }
            }
        
        success_lighting = extract_lighting_stats(success_data)
        failed_lighting = extract_lighting_stats(failed_data)
        
        # Identify optimal ranges
        optimal_brightness_range = None
        optimal_contrast_range = None
        
        if success_lighting["brightness"]["count"] > 0:
            brightness_mean = success_lighting["brightness"]["mean"]
            brightness_std = success_lighting["brightness"]["std"]
            optimal_brightness_range = {
                "min": max(0, brightness_mean - brightness_std),
                "max": min(255, brightness_mean + brightness_std)
            }
        
        if success_lighting["contrast"]["count"] > 0:
            contrast_mean = success_lighting["contrast"]["mean"]
            contrast_std = success_lighting["contrast"]["std"]
            optimal_contrast_range = {
                "min": max(0, contrast_mean - contrast_std),
                "max": contrast_mean + contrast_std
            }
        
        return {
            "successful_detections": success_lighting,
            "failed_detections": failed_lighting,
            "optimal_brightness_range": optimal_brightness_range,
            "optimal_contrast_range": optimal_contrast_range
        }
    
    def _generate_recommendations(self, failed_data: List[Dict], success_data: List[Dict]) -> List[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []
        
        if not failed_data:
            recommendations.append("No failures detected in the analyzed period - system performing well")
            return recommendations
        
        total_attempts = len(failed_data) + len(success_data)
        failure_rate = len(failed_data) / total_attempts if total_attempts > 0 else 0
        
        # High failure rate
        if failure_rate > 0.3:
            recommendations.append(f"High failure rate detected ({failure_rate:.1%}). Consider systematic review of lighting setup")
        
        # Brightness issues
        dark_failures = sum(1 for f in failed_data 
                          if f.get("image_quality", {}).get("mean_brightness", 128) < 80)
        bright_failures = sum(1 for f in failed_data 
                            if f.get("image_quality", {}).get("mean_brightness", 128) > 200)
        
        if dark_failures > len(failed_data) * 0.3:
            recommendations.append("Many failures due to low lighting. Increase illumination or check for obstructions")
        
        if bright_failures > len(failed_data) * 0.3:
            recommendations.append("Many failures due to excessive brightness. Reduce illumination or add diffusion")
        
        # Contrast issues
        low_contrast_failures = sum(1 for f in failed_data 
                                  if f.get("image_quality", {}).get("contrast_rms", 0) < 20)
        
        if low_contrast_failures > len(failed_data) * 0.3:
            recommendations.append("Low contrast contributing to failures. Check target visibility and arena cleanliness")
        
        # Partial detection patterns
        partial_detections = sum(1 for f in failed_data if 0 < f.get("targets_found", 0) < 3)
        if partial_detections > len(failed_data) * 0.5:
            recommendations.append("Many partial detections (1-2 targets found). Check target placement and visibility")
        
        # Zero detections
        zero_detections = sum(1 for f in failed_data if f.get("targets_found", 0) == 0)
        if zero_detections > len(failed_data) * 0.3:
            recommendations.append("Many complete detection failures. Verify targets are present and properly positioned")
        
        return recommendations
    
    def generate_failure_report(self, days_back: int = 7) -> str:
        """
        Generate a comprehensive failure report.
        
        Args:
            days_back: Number of days to include in report
            
        Returns:
            Path to generated report file
        """
        analysis = self.analyze_detection_logs(days_back)
        
        report_filename = f"target_detection_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path = self.reports_dir / report_filename
        
        with open(report_path, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        
        self.logger.info(f"Generated failure report: {report_path}")
        return str(report_path)
    
    def cleanup_old_logs(self, days_to_keep: int = 30) -> Dict[str, int]:
        """
        Clean up old diagnostic logs to manage storage space.
        
        Args:
            days_to_keep: Number of days of data to retain
            
        Returns:
            Dictionary with cleanup statistics
        """
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cleanup_stats = {"files_removed": 0, "bytes_freed": 0}
        
        for subdir in ["failed", "success"]:
            subdir_path = self.base_path / subdir
            if not subdir_path.exists():
                continue
            
            for file_path in subdir_path.iterdir():
                try:
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_mtime < cutoff_date:
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        cleanup_stats["files_removed"] += 1
                        cleanup_stats["bytes_freed"] += file_size
                        
                except (OSError, ValueError) as e:
                    self.logger.warning(f"Error cleaning up {file_path}: {e}")
        
        self.logger.info(f"Cleanup completed: {cleanup_stats['files_removed']} files removed, "
                        f"{cleanup_stats['bytes_freed']} bytes freed")
        return cleanup_stats
    
    def export_dataset_for_training(self, output_dir: str, 
                                  max_samples_per_class: int = 1000) -> Dict[str, int]:
        """
        Export a balanced dataset for machine learning analysis.
        
        Args:
            output_dir: Directory to export dataset to
            max_samples_per_class: Maximum samples per class (success/failure)
            
        Returns:
            Dictionary with export statistics
        """
        export_path = Path(output_dir)
        export_path.mkdir(parents=True, exist_ok=True)
        
        stats = {"success_exported": 0, "failed_exported": 0}
        
        for subdir, stat_key in [("success", "success_exported"), ("failed", "failed_exported")]:
            source_dir = self.base_path / subdir
            target_dir = export_path / subdir
            target_dir.mkdir(exist_ok=True)
            
            if not source_dir.exists():
                continue
            
            # Get all image files
            image_files = list(source_dir.glob("*_original.png"))
            
            # Limit samples
            if len(image_files) > max_samples_per_class:
                image_files = image_files[:max_samples_per_class]
            
            # Copy files
            for image_file in image_files:
                # Copy image
                target_image = target_dir / image_file.name
                shutil.copy2(image_file, target_image)
                
                # Copy corresponding metadata
                metadata_file = image_file.with_name(image_file.name.replace("_original.png", "_metadata.json"))
                if metadata_file.exists():
                    target_metadata = target_dir / metadata_file.name
                    shutil.copy2(metadata_file, target_metadata)
                
                stats[stat_key] += 1
        
        # Create dataset info file
        dataset_info = {
            "export_date": datetime.now().isoformat(),
            "source_path": str(self.base_path),
            "export_stats": stats,
            "max_samples_per_class": max_samples_per_class
        }
        
        with open(export_path / "dataset_info.json", 'w') as f:
            json.dump(dataset_info, f, indent=2)
        
        self.logger.info(f"Dataset exported to {export_path}: {stats}")
        return stats