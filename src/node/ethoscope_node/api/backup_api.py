"""
Backup API Module

Handles backup system management by aggregating basic status information
from MySQL (port 8090) and rsync (port 8093) backup services.
"""

import json
import urllib.request
import time
from typing import Dict, Any
from .base import BaseAPI, error_decorator


class BackupAPI(BaseAPI):
    """API endpoints for backup system management."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Simple cache for backup status with 60 second TTL
        self._backup_cache = {
            'data': None,
            'timestamp': 0,
            'ttl': 60  # Cache for 60 seconds
        }
    
    def register_routes(self):
        """Register backup-related routes."""
        self.app.route('/backup/status', method='GET')(self._get_backup_status)
    
    @error_decorator
    def _get_backup_status(self):
        """Get basic backup status aggregated from backup services."""
        self.set_json_response()
        
        # Check cache first
        current_time = time.time()
        if (self._backup_cache['data'] is not None and 
            current_time - self._backup_cache['timestamp'] < self._backup_cache['ttl']):
            return self._backup_cache['data']
        
        # Fetch basic status from both backup services
        mysql_status = self._fetch_backup_service_status(8090, "MySQL")
        rsync_status = self._fetch_backup_service_status(8093, "Rsync")
        
        # Create simple aggregated response
        aggregated_status = {
            "services": {
                "mysql_backup": {
                    "available": "error" not in mysql_status,
                    "current_device": self._extract_current_device(mysql_status),
                    "current_file": self._extract_current_file(mysql_status)
                },
                "rsync_backup": {
                    "available": "error" not in rsync_status,
                    "current_device": self._extract_current_device(rsync_status),
                    "current_file": self._extract_current_file(rsync_status)
                }
            },
            "processing_devices": self._get_processing_devices(mysql_status, rsync_status),
            "timestamp": current_time
        }
        
        # Cache the result
        result = json.dumps(aggregated_status, indent=2)
        self._backup_cache = {
            'data': result,
            'timestamp': current_time,
            'ttl': 60
        }
        
        return result
    
    def _fetch_backup_service_status(self, port: int, service_name: str):
        """Fetch basic status from a backup daemon."""
        try:
            backup_url = f'http://localhost:{port}/status'
            with urllib.request.urlopen(backup_url, timeout=5) as response:
                data = response.read().decode('utf-8')
                return json.loads(data)
        except Exception as e:
            self.logger.debug(f"Failed to get {service_name} backup status from port {port}: {e}")
            return {"error": f"{service_name} backup service unavailable"}
    
    def _extract_current_device(self, service_status):
        """Extract currently processing device from service status."""
        if "error" in service_status:
            return None
            
        # Check if this is the simplified format (from reverted backup tools)
        if "current_device" in service_status:
            return service_status["current_device"]
            
        # Check for processing devices in the array format
        if "processing_devices" in service_status:
            processing = service_status["processing_devices"]
            if processing and len(processing) > 0:
                return processing[0].get("device_name")
        
        # Legacy format - look for processing devices in full status
        if isinstance(service_status, dict):
            for device_id, device_data in service_status.items():
                if isinstance(device_data, dict) and device_data.get("processing", False):
                    return device_data.get("name", device_id)
        
        return None
    
    def _extract_current_file(self, service_status):
        """Extract currently processing file from service status."""
        if "error" in service_status:
            return None
            
        # Check if this is the simplified format (from reverted backup tools)
        if "current_file" in service_status:
            return service_status["current_file"]
            
        # Check for processing devices in the array format
        if "processing_devices" in service_status:
            processing = service_status["processing_devices"]
            if processing and len(processing) > 0:
                return processing[0].get("current_file")
        
        # Legacy format - look for current file in progress data
        if isinstance(service_status, dict):
            for device_id, device_data in service_status.items():
                if isinstance(device_data, dict) and device_data.get("processing", False):
                    progress = device_data.get("progress", {})
                    return progress.get("current_file", progress.get("backup_filename"))
        
        return None
    
    def _get_processing_devices(self, mysql_status, rsync_status):
        """Get list of all currently processing devices."""
        processing = []
        
        # Extract from MySQL service
        mysql_device = self._extract_current_device(mysql_status)
        mysql_file = self._extract_current_file(mysql_status)
        if mysql_device:
            processing.append({
                "service": "mysql",
                "device": mysql_device,
                "current_file": mysql_file
            })
        
        # Extract from rsync service
        rsync_device = self._extract_current_device(rsync_status)
        rsync_file = self._extract_current_file(rsync_status)
        if rsync_device:
            processing.append({
                "service": "rsync",
                "device": rsync_device,
                "current_file": rsync_file
            })
        
        return processing