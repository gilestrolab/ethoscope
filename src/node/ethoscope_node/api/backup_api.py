"""
Backup API Module

Handles backup system management including status aggregation from multiple
backup services (MySQL and rsync) and structured backup information.
"""

import json
import urllib.request
import subprocess
import os
import time
from typing import Dict, Any
from .base import BaseAPI, error_decorator


class BackupAPI(BaseAPI):
    """API endpoints for backup system management."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Cache for backup status to improve performance
        self._backup_cache = {
            'data': None,
            'timestamp': 0,
            'ttl': 30  # Cache for 30 seconds
        }
    
    def register_routes(self):
        """Register backup-related routes."""
        self.app.route('/backup/status', method='GET')(self._get_backup_status)
    
    @error_decorator
    def _get_backup_status(self):
        """Get structured backup status for MySQL, SQLite, and Video backups."""
        self.set_json_response()
        
        # Check cache first
        current_time = time.time()
        if (self._backup_cache['data'] is not None and 
            current_time - self._backup_cache['timestamp'] < self._backup_cache['ttl']):
            return self._backup_cache['data']
        
        # Fetch status from both backup services
        mysql_status = self._fetch_backup_service_status(8090, "MySQL")
        rsync_status = self._fetch_backup_service_status(8093, "Rsync")
        
        # Create structured response with clear backup type separation
        structured_status = {
            "devices": self._create_structured_backup_status(mysql_status, rsync_status),
            "summary": self._create_backup_summary(mysql_status, rsync_status)
        }
        
        # Cache the result
        result = json.dumps(structured_status, indent=2)
        self._backup_cache = {
            'data': result,
            'timestamp': current_time,
            'ttl': 30
        }
        
        return result
    
    def _fetch_backup_service_status(self, port: int, service_name: str):
        """Fetch backup status from a backup daemon running on specified port."""
        try:
            backup_url = f'http://localhost:{port}/status'
            with urllib.request.urlopen(backup_url, timeout=5) as response:
                data = response.read().decode('utf-8')
                return json.loads(data)
        except Exception as e:
            # Commented out warning to reduce log noise
            # self.logger.warning(f"Failed to get {service_name} backup status from port {port}: {e}")
            return {"error": f"{service_name} backup service unavailable", "service": service_name.lower().replace(" ", "_")}
    
    def _extract_devices_from_status(self, mysql_status, rsync_status):
        """Extract device information from both backup services."""
        mysql_devices = mysql_status.get("devices", mysql_status) if "error" not in mysql_status else {}
        rsync_devices = rsync_status.get("devices", rsync_status) if "error" not in rsync_status else {}
        all_device_ids = set(mysql_devices.keys()) | set(rsync_devices.keys())
        
        return mysql_devices, rsync_devices, all_device_ids
    
    def _create_structured_backup_status(self, mysql_status, rsync_status):
        """Create structured backup status with clear MySQL, SQLite, and Video separation."""
        structured_devices = {}
        
        mysql_devices, rsync_devices, all_device_ids = self._extract_devices_from_status(mysql_status, rsync_status)
        
        for device_id in all_device_ids:
            mysql_device = mysql_devices.get(device_id, {})
            rsync_device = rsync_devices.get(device_id, {})
            
            # Extract synced information to determine backup types
            mysql_synced = mysql_device.get("synced", {})
            rsync_synced = rsync_device.get("synced", {})
            
            # Determine what types of data are being backed up
            mysql_backup_info = self._extract_backup_info("mysql", mysql_device)
            sqlite_backup_info = self._extract_backup_info("sqlite", rsync_device, rsync_synced, device_id)
            video_backup_info = self._extract_backup_info("video", rsync_device, rsync_synced, device_id)
            
            # Create structured device status
            device_status = {
                "name": mysql_device.get("name") or rsync_device.get("name", f"DEVICE_{device_id[:8]}"),
                "device_status": mysql_device.get("status") or rsync_device.get("status", "unknown"),
                "last_seen": max(
                    mysql_device.get("ended", 0) or 0,
                    rsync_device.get("ended", 0) or 0
                ),
                "backup_types": {
                    "mysql": mysql_backup_info,
                    "sqlite": sqlite_backup_info, 
                    "video": video_backup_info
                },
                "overall_status": self._determine_overall_backup_status(
                    mysql_backup_info, sqlite_backup_info, video_backup_info
                )
            }
            
            # Pass through enhanced individual_files data from rsync service
            if rsync_device and 'individual_files' in rsync_device:
                device_status['individual_files'] = rsync_device['individual_files']
            
            # Pass through enhanced backup_types from rsync service if available
            if rsync_device and 'backup_types' in rsync_device:
                # Merge the enhanced backup_types data from rsync service
                rsync_backup_types = rsync_device['backup_types']
                if 'sqlite' in rsync_backup_types and rsync_backup_types['sqlite'].get('available'):
                    device_status['backup_types']['sqlite'] = rsync_backup_types['sqlite']
                if 'video' in rsync_backup_types and rsync_backup_types['video'].get('available'):
                    device_status['backup_types']['video'] = rsync_backup_types['video']
            
            structured_devices[device_id] = device_status
        
        return structured_devices
    
    def _extract_backup_info(self, backup_type: str, device_data: dict, synced_data: dict = None, device_id: str = None):
        """Generic method to extract backup information for any backup type."""
        if not device_data:
            return self._get_empty_backup_info(backup_type)
        
        progress = device_data.get("progress", {})
        
        # Base backup info common to all types
        base_info = {
            "available": True,
            "status": progress.get("status", "unknown"),
            "last_backup": device_data.get("ended"),
            "processing": device_data.get("processing", False),
            "message": progress.get("message", ""),
            "time_since_backup": progress.get("time_since_backup")
        }
        
        # Add type-specific information
        if backup_type == "mysql":
            base_info.update({
                "size": progress.get("backup_size", 0),
                "records": device_data.get("count", 0)
            })
        
        elif backup_type == "sqlite":
            # Look for SQLite database info in synced data
            sqlite_info = self._find_sqlite_info(synced_data or {})
            if not sqlite_info:
                return self._get_empty_backup_info(backup_type)
            
            # Calculate device-specific SQLite size and file count instead of using total directory stats
            device_sqlite_size, device_sqlite_size_human, device_sqlite_files = self._calculate_device_backup_stats(device_data, device_id, "sqlite")
            
            base_info.update({
                "size": device_sqlite_size,
                "size_human": device_sqlite_size_human,
                "files": device_sqlite_files,
                "directory": sqlite_info.get("directory", "")
            })
        
        elif backup_type == "video":
            # Look for video info in synced data
            video_info = (synced_data or {}).get("videos", {})
            if not video_info:
                return self._get_empty_backup_info(backup_type)
            
            # Calculate device-specific video size and file count instead of using total directory stats
            device_video_size, device_video_size_human, device_video_files = self._calculate_device_backup_stats(device_data, device_id, "video")
            
            base_info.update({
                "size": device_video_size,
                "size_human": device_video_size_human,
                "files": device_video_files,
                "directory": video_info.get("directory", "")
            })
        
        return base_info
    
    def _get_empty_backup_info(self, backup_type: str):
        """Get empty backup info structure for unavailable backups."""
        base_empty = {
            "available": False,
            "status": "not_available",
            "last_backup": None,
            "size": 0
        }
        
        if backup_type == "mysql":
            base_empty["records"] = 0
        else:  # sqlite and video
            base_empty["files"] = 0
            if backup_type == "video":
                base_empty["size_human"] = "0 B"
        
        return base_empty
    
    def _find_sqlite_info(self, synced_data: dict):
        """Find SQLite database info in synced data."""
        # SQLite databases are stored in the 'results' directory by the rsync backup tool
        if 'results' in synced_data:
            return synced_data['results']
        
        # Fallback: search for keys that might contain database info
        for key, value in synced_data.items():
            if (key.lower().endswith('.db') or 
                'sqlite' in key.lower() or 
                'database' in key.lower()):
                return value
        return {}
    
    def _calculate_device_backup_stats(self, device_data: dict, device_id: str = None, backup_type: str = "video"):
        """Calculate the actual directory size and file count for a specific device and backup type."""
        try:
            # Get device name from device data
            device_name = device_data.get("name", "") if device_data else ""
            
            if not device_id or not device_name:
                self.logger.warning(f"Could not determine device ID ({device_id}) or name ({device_name}) for {backup_type} stats calculation")
                return 0, "0 B", 0
            
            # Build the device-specific path based on backup type
            if backup_type == "sqlite":
                # Path structure: /ethoscope_data/results/{device_id}/{device_name}/
                device_path = f"/ethoscope_data/results/{device_id}/{device_name}"
            else:  # video
                # Path structure: /ethoscope_data/videos/{device_id}/{device_name}/
                device_path = f"/ethoscope_data/videos/{device_id}/{device_name}"
            
            if not os.path.exists(device_path):
                # Commented out warning to reduce log noise
                # self.logger.warning(f"Device {backup_type} path does not exist: {device_path}")
                return 0, "0 B", 0
            
            self.logger.debug(f"Calculating {backup_type} stats for device {device_name} ({device_id}) at path: {device_path}")
            
            # Calculate directory size using du command
            size_result = subprocess.run(
                ['du', '-sb', device_path], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            # Count files in directory using find command
            files_result = subprocess.run(
                ['find', device_path, '-type', 'f'], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            size_bytes = 0
            size_human = "0 B"
            file_count = 0
            
            if size_result.returncode == 0:
                size_bytes = int(size_result.stdout.split()[0])
                size_human = self._human_readable_size(size_bytes)
            else:
                self.logger.error(f"Failed to calculate size for {device_path}: {size_result.stderr}")
            
            if files_result.returncode == 0:
                # Count lines in output (each line is a file)
                file_count = len([line for line in files_result.stdout.strip().split('\\n') if line.strip()])
            else:
                self.logger.error(f"Failed to count files for {device_path}: {files_result.stderr}")
            
            return size_bytes, size_human, file_count
                
        except Exception as e:
            self.logger.error(f"Error calculating device {backup_type} stats: {e}")
            return 0, "0 B", 0
    
    def _human_readable_size(self, size_bytes: int) -> str:
        """Convert bytes to human readable format."""
        if size_bytes == 0:
            return "0 B"
        
        units = ['B', 'K', 'M', 'G', 'T']
        unit_index = 0
        size = float(size_bytes)
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.1f}{units[unit_index]}"
    
    def _determine_overall_backup_status(self, mysql_info, sqlite_info, video_info):
        """Determine overall backup status based on all backup types."""
        statuses = []
        
        if mysql_info["available"]:
            statuses.append(mysql_info["status"])
        if sqlite_info["available"]:
            statuses.append(sqlite_info["status"])
        if video_info["available"]:
            statuses.append(video_info["status"])
        
        if not statuses:
            return "no_backups"
        
        # All successful
        if all(status in ["success", "completed"] for status in statuses):
            return "success"
        
        # Any failed
        if any(status in ["error", "failed"] for status in statuses):
            return "error"
        
        # Any processing
        if any(status in ["processing", "running"] for status in statuses):
            return "processing"
        
        # Partial success
        if any(status in ["success", "completed"] for status in statuses):
            return "partial"
        
        return "unknown"
    
    def _get_service_availability(self, service_status):
        """Check if a backup service is available based on its status."""
        return "error" not in service_status
    
    def _create_backup_summary(self, mysql_status, rsync_status):
        """Create summary statistics for backup services."""
        mysql_available = self._get_service_availability(mysql_status)
        rsync_available = self._get_service_availability(rsync_status)
        
        mysql_devices, rsync_devices, all_device_ids = self._extract_devices_from_status(mysql_status, rsync_status)
        
        return {
            "services": {
                "mysql_service_available": mysql_available,
                "rsync_service_available": rsync_available,
                "mysql_service_status": "online" if mysql_available else "offline",
                "rsync_service_status": "online" if rsync_available else "offline"
            },
            "devices": {
                "total_devices": len(all_device_ids),
                "mysql_backed_up": len(mysql_devices),
                "rsync_backed_up": len(rsync_devices),
                "both_services": len(set(mysql_devices.keys()) & set(rsync_devices.keys()))
            }
        }