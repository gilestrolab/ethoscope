"""
Unit tests for base API infrastructure.

Tests decorators, BaseAPI class, and common API utilities.
"""

import json
import logging
import unittest
from unittest.mock import Mock, patch

import bottle
import pytest

from ethoscope_node.api.base import BaseAPI, error_decorator, warning_decorator


class AbortError(Exception):
    """Custom exception for testing abort scenarios."""

    pass


class TestErrorDecorator(unittest.TestCase):
    """Test suite for error_decorator."""

    def test_error_decorator_success(self):
        """Test decorator passes through successful function calls."""

        @error_decorator
        def successful_function():
            return {"result": "success"}

        result = successful_function()
        self.assertEqual(result, {"result": "success"})

    def test_error_decorator_catches_exception(self):
        """Test decorator catches exceptions and returns error dict."""

        @error_decorator
        def failing_function():
            raise ValueError("Test error")

        with patch("logging.error") as mock_log:
            result = failing_function()

            # Should return error dict
            self.assertIn("error", result)
            self.assertIn("ValueError: Test error", result["error"])
            # Should log the error
            mock_log.assert_called_once()

    def test_error_decorator_preserves_function_metadata(self):
        """Test decorator preserves function name and docstring."""

        @error_decorator
        def test_function():
            """Test docstring."""
            pass

        self.assertEqual(test_function.__name__, "test_function")
        self.assertEqual(test_function.__doc__, "Test docstring.")

    def test_error_decorator_with_arguments(self):
        """Test decorator works with functions that have arguments."""

        @error_decorator
        def function_with_args(a, b, c=None):
            return {"a": a, "b": b, "c": c}

        result = function_with_args(1, 2, c=3)
        self.assertEqual(result, {"a": 1, "b": 2, "c": 3})

    def test_error_decorator_full_traceback(self):
        """Test decorator includes full traceback in error."""

        @error_decorator
        def nested_error():
            def inner():
                raise RuntimeError("Inner error")

            inner()

        with patch("logging.error"):
            result = nested_error()
            # Should contain traceback with function names
            self.assertIn("error", result)
            self.assertIn("inner", result["error"])
            self.assertIn("RuntimeError", result["error"])


class TestWarningDecorator(unittest.TestCase):
    """Test suite for warning_decorator."""

    def test_warning_decorator_success(self):
        """Test decorator passes through successful function calls."""

        @warning_decorator
        def successful_function():
            return {"result": "success"}

        result = successful_function()
        self.assertEqual(result, {"result": "success"})

    def test_warning_decorator_catches_exception(self):
        """Test decorator catches exceptions and returns warning dict."""

        @warning_decorator
        def failing_function():
            raise ValueError("Test warning")

        with patch("logging.error") as mock_log:
            result = failing_function()

            # Should return error dict with string message (not traceback)
            self.assertEqual(result, {"error": "Test warning"})
            # Should log the error
            mock_log.assert_called_once()

    def test_warning_decorator_vs_error_decorator(self):
        """Test warning_decorator returns str(e) vs error_decorator's traceback."""

        @warning_decorator
        def warning_func():
            raise ValueError("Short message")

        @error_decorator
        def error_func():
            raise ValueError("Short message")

        with patch("logging.error"):
            warning_result = warning_func()
            error_result = error_func()

            # Warning should have just the message
            self.assertEqual(warning_result["error"], "Short message")
            # Error should have full traceback
            self.assertIn("Traceback", error_result["error"])
            self.assertIn("Short message", error_result["error"])

    def test_warning_decorator_preserves_function_metadata(self):
        """Test decorator preserves function name and docstring."""

        @warning_decorator
        def test_function():
            """Test docstring."""
            pass

        self.assertEqual(test_function.__name__, "test_function")
        self.assertEqual(test_function.__doc__, "Test docstring.")


class TestBaseAPI(unittest.TestCase):
    """Test suite for BaseAPI class."""

    def setUp(self):
        """Create mock server instance and BaseAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = {"test": "config"}
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"

        self.api = BaseAPI(self.mock_server)

    def test_initialization(self):
        """Test BaseAPI initialization with server instance."""
        self.assertEqual(self.api.server, self.mock_server)
        self.assertEqual(self.api.app, self.mock_server.app)
        self.assertEqual(self.api.config, {"test": "config"})
        self.assertEqual(self.api.device_scanner, self.mock_server.device_scanner)
        self.assertEqual(self.api.database, self.mock_server.database)

    def test_logger_creation(self):
        """Test that logger is created with class name."""
        self.assertIsInstance(self.api.logger, logging.Logger)
        self.assertEqual(self.api.logger.name, "BaseAPI")

    def test_directories_initialized(self):
        """Test that directory paths are initialized from server."""
        self.assertEqual(self.api.results_dir, "/tmp/results")
        self.assertEqual(self.api.sensors_dir, "/tmp/sensors")
        self.assertEqual(self.api.roi_templates_dir, "/tmp/templates")
        self.assertEqual(self.api.tmp_imgs_dir, "/tmp/imgs")

    def test_register_routes_default(self):
        """Test register_routes default implementation does nothing."""
        # Should not raise, just pass
        self.api.register_routes()

    @patch("bottle.request")
    def test_get_request_data(self, mock_request):
        """Test getting raw request data."""
        mock_request.body.read.return_value = b"test data"
        result = self.api.get_request_data()
        self.assertEqual(result, b"test data")

    @patch("bottle.request")
    def test_get_request_json(self, mock_request):
        """Test getting request data as JSON."""
        mock_request.json = {"key": "value"}
        result = self.api.get_request_json()
        self.assertEqual(result, {"key": "value"})

    @patch("bottle.request")
    def test_get_request_json_none(self, mock_request):
        """Test getting request JSON when None returns empty dict."""
        mock_request.json = None
        result = self.api.get_request_json()
        self.assertEqual(result, {})

    @patch("bottle.request")
    def test_get_query_param(self, mock_request):
        """Test getting query parameter."""
        mock_request.query.get.return_value = "param_value"
        result = self.api.get_query_param("test_param")
        self.assertEqual(result, "param_value")
        mock_request.query.get.assert_called_once_with("test_param", None)

    @patch("bottle.request")
    def test_get_query_param_with_default(self, mock_request):
        """Test getting query parameter with default value."""
        mock_request.query.get.return_value = "default_value"
        self.api.get_query_param("missing", default="default_value")
        mock_request.query.get.assert_called_once_with("missing", "default_value")

    @patch("bottle.response")
    def test_set_json_response(self, mock_response):
        """Test setting JSON response content type."""
        self.api.set_json_response()
        self.assertEqual(mock_response.content_type, "application/json")

    @patch("bottle.response")
    def test_json_response(self, mock_response):
        """Test JSON response with formatting."""
        data = {"key": "value", "number": 42}
        result = self.api.json_response(data)

        # Should set content type
        self.assertEqual(mock_response.content_type, "application/json")
        # Should return JSON string with indentation
        parsed = json.loads(result)
        self.assertEqual(parsed, data)
        self.assertIn("\n", result)  # Has indentation

    @patch("bottle.abort")
    def test_abort_with_error(self, mock_abort):
        """Test aborting request with error."""
        self.api.abort_with_error(404, "Not found")
        mock_abort.assert_called_once_with(404, "Not found")

    def test_validate_device_exists_no_scanner(self):
        """Test validate_device_exists when scanner not available."""
        self.api.device_scanner = None

        with patch.object(
            self.api, "abort_with_error", side_effect=AbortError("Aborted")
        ) as mock_abort:
            with self.assertRaises(AbortError):
                self.api.validate_device_exists("device123")
            mock_abort.assert_called_once_with(503, "Device scanner not available")

    def test_validate_device_exists_device_not_found(self):
        """Test validate_device_exists when device not found."""
        self.api.device_scanner.get_device.return_value = None

        with patch.object(
            self.api, "abort_with_error", side_effect=AbortError("Aborted")
        ) as mock_abort:
            with self.assertRaises(AbortError):
                self.api.validate_device_exists("device123")
            mock_abort.assert_called_once_with(404, "Device device123 not found")

    def test_validate_device_exists_success(self):
        """Test validate_device_exists returns device when found."""
        mock_device = Mock()
        mock_device.id = "device123"
        self.api.device_scanner.get_device.return_value = mock_device

        result = self.api.validate_device_exists("device123")
        self.assertEqual(result, mock_device)
        self.api.device_scanner.get_device.assert_called_once_with("device123")

    def test_safe_file_operation_success(self):
        """Test safe_file_operation with successful operation."""

        def mock_operation(path):
            return f"result: {path}"

        result = self.api.safe_file_operation(mock_operation, "/test/path")
        self.assertEqual(result, "result: /test/path")

    def test_safe_file_operation_os_error(self):
        """Test safe_file_operation catches OSError."""

        def failing_operation():
            raise OSError("Permission denied")

        with patch.object(self.api, "abort_with_error") as mock_abort:
            self.api.safe_file_operation(failing_operation)
            mock_abort.assert_called_once()
            args = mock_abort.call_args[0]
            self.assertEqual(args[0], 500)
            self.assertIn("Permission denied", args[1])

    def test_safe_file_operation_generic_exception(self):
        """Test safe_file_operation catches generic exceptions."""

        def failing_operation():
            raise ValueError("Unexpected error")

        with patch.object(self.api, "abort_with_error") as mock_abort:
            self.api.safe_file_operation(failing_operation)
            mock_abort.assert_called_once()
            args = mock_abort.call_args[0]
            self.assertEqual(args[0], 500)
            self.assertIn("Unexpected error", args[1])

    def test_safe_file_operation_with_kwargs(self):
        """Test safe_file_operation passes through kwargs."""

        def operation_with_kwargs(path, mode="r", encoding="utf-8"):
            return {"path": path, "mode": mode, "encoding": encoding}

        result = self.api.safe_file_operation(
            operation_with_kwargs, "/test", mode="w", encoding="latin1"
        )
        self.assertEqual(result, {"path": "/test", "mode": "w", "encoding": "latin1"})


if __name__ == "__main__":
    unittest.main()
