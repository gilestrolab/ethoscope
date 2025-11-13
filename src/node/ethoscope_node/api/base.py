"""
Base API Infrastructure

Provides common utilities, decorators, and base classes for all API modules.
"""

import json
import logging
import traceback
from functools import wraps
from typing import Any, Dict

import bottle


def error_decorator(func):
    """Decorator to return error dict for display in webUI."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logging.error(traceback.format_exc())
            return {"error": traceback.format_exc()}

    return wrapper


def warning_decorator(func):
    """Decorator to return warning dict for display in webUI."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {"error": str(e)}

    return wrapper


class BaseAPI:
    """Base class for all API modules providing common functionality."""

    def __init__(self, server_instance):
        """
        Initialize the API with reference to the main server instance.

        Args:
            server_instance: The main EthoscopeNodeServer instance
        """
        self.server = server_instance
        self.logger = logging.getLogger(self.__class__.__name__)

        # Common server components
        self.app = server_instance.app
        self.config = server_instance.config
        self.device_scanner = server_instance.device_scanner
        self.sensor_scanner = server_instance.sensor_scanner
        self.database = server_instance.database

        # Common directories
        self.results_dir = server_instance.results_dir
        self.sensors_dir = server_instance.sensors_dir
        self.roi_templates_dir = server_instance.roi_templates_dir
        self.tmp_imgs_dir = server_instance.tmp_imgs_dir

    def register_routes(self):
        """Register API routes with the Bottle application. Override in subclasses."""
        pass

    def get_request_data(self) -> bytes:
        """Get raw request data as bytes."""
        return bottle.request.body.read()

    def get_request_json(self) -> Dict[str, Any]:
        """Get request data as JSON."""
        return bottle.request.json or {}

    def get_query_param(self, name: str, default: Any = None) -> str:
        """Get query parameter value."""
        return bottle.request.query.get(name, default)

    def set_json_response(self):
        """Set response content type to JSON."""
        bottle.response.content_type = "application/json"

    def json_response(self, data: Any) -> str:
        """Return JSON response."""
        self.set_json_response()
        return json.dumps(data, indent=2)

    def abort_with_error(self, status_code: int, message: str):
        """Abort request with error status and message."""
        bottle.abort(status_code, message)

    def validate_device_exists(self, device_id: str):
        """Validate that a device exists and return it."""
        if not self.device_scanner:
            self.abort_with_error(503, "Device scanner not available")

        device = self.device_scanner.get_device(device_id)
        if not device:
            self.abort_with_error(404, f"Device {device_id} not found")

        return device

    def safe_file_operation(self, operation, *args, **kwargs):
        """Safely perform file operations with error handling."""
        try:
            return operation(*args, **kwargs)
        except OSError as e:
            self.logger.error(f"File operation failed: {e}")
            self.abort_with_error(500, f"File operation failed: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in file operation: {e}")
            self.abort_with_error(500, f"Operation failed: {e}")
