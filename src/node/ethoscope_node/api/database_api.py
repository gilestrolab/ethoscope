"""
Database API Module

Handles database queries for runs and experiments and cached database information.
"""

import json
import logging
from .base import BaseAPI, error_decorator


class DatabaseAPI(BaseAPI):
    """API endpoints for database queries."""
    
    def register_routes(self):
        """Register database-related routes."""
        self.app.route('/runs_list', method='GET')(self._runs_list)
        self.app.route('/experiments_list', method='GET')(self._experiments_list)
        self.app.route('/cached_databases/<device_name>', method='GET')(self._cached_databases)
    
    @error_decorator
    def _runs_list(self):
        """Get all runs from database."""
        return json.dumps(self.database.getRun('all', asdict=True))
    
    @error_decorator
    def _experiments_list(self):
        """Get all experiments from database."""
        return json.dumps(self.database.getExperiment('all', asdict=True))
    
    @error_decorator
    def _cached_databases(self, device_name):
        """
        Get database information from a specific ethoscope device.
        
        Returns database list formatted for frontend dropdowns with 'name' and 'active' properties.
        This gets the database information directly from the ethoscope device via the scanner.
        """
        self.set_json_response()
        
        try:
            # Get the specific ethoscope device from the scanner
            device_info = None
            for device_id, device_data in self.devices.items():
                if device_data.get('name') == device_name:
                    device_info = device_data
                    break
            
            if not device_info:
                self.logger.warning(f"Device {device_name} not found in scanner")
                return json.dumps([])
            
            # Get databases information from the device data
            databases_info = device_info.get("databases", {})
            
            # Format database list for frontend compatibility
            db_list = []
            
            # Add SQLite databases that exist and have data
            if databases_info.get("SQLite"):
                for db_name, db_info in databases_info["SQLite"].items():
                    # Only include databases that actually exist and have data
                    if db_info.get("file_exists", False) and db_info.get("filesize", 0) > 32768:  # > 32KB
                        db_list.append({
                            "name": db_name,
                            "active": True,
                            "size": db_info.get("filesize", 0),
                            "status": db_info.get("db_status", "unknown"),
                            "type": "SQLite"
                        })
            
            # Add MariaDB databases
            if databases_info.get("MariaDB"):
                for db_name, db_info in databases_info["MariaDB"].items():
                    db_list.append({
                        "name": db_name,
                        "active": True,
                        "size": db_info.get("db_size_bytes", 0),
                        "status": db_info.get("db_status", "unknown"),
                        "type": "MariaDB"
                    })
            
            # Sort by name (newest first)
            db_list.sort(key=lambda x: x["name"], reverse=True)
            
            self.logger.debug(f"Found {len(db_list)} databases for device {device_name}")
            return json.dumps(db_list)
            
        except Exception as e:
            self.logger.error(f"Failed to get databases for device {device_name}: {e}")
            return json.dumps([])  # Return empty list on error