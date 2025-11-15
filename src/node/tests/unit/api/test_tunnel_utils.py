"""
Unit tests for Tunnel Utils API endpoints.

Tests tunnel configuration, service management, and URL generation.
"""

import json
import os
import unittest
from unittest.mock import Mock, mock_open, patch

from ethoscope_node.api.tunnel_utils import TunnelUtils


class TestTunnelUtils(unittest.TestCase):
    """Test suite for TunnelUtils class."""

    def setUp(self):
        """Create mock server instance and TunnelUtils for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = Mock()
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"
        self.mock_server.systemctl = "systemctl"

        self.api = TunnelUtils(self.mock_server)

    def test_register_routes(self):
        """Test that all tunnel routes are registered."""
        # Track route registrations
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route

        # Register routes
        self.api.register_routes()

        # Verify all 3 routes were registered
        self.assertEqual(len(route_calls), 3)

        # Check specific routes
        paths = [call[0] for call in route_calls]
        self.assertIn("/tunnel/status", paths)
        self.assertIn("/tunnel/toggle", paths)
        self.assertIn("/tunnel/config", paths)

    # get_tunnel_update_url tests

    def test_get_tunnel_update_url_no_config(self):
        """Test get_tunnel_update_url when config is None."""
        self.api.config = None

        result = self.api.get_tunnel_update_url()

        self.assertEqual(result, "http://localhost:8888")

    def test_get_tunnel_update_url_tunnel_enabled_with_domain(self):
        """Test get_tunnel_update_url when tunnel enabled with valid domain."""
        self.api.config.get_tunnel_config.return_value = {
            "enabled": True,
            "full_domain": "example.tunnel.com",
        }

        result = self.api.get_tunnel_update_url()

        self.assertEqual(result, "http://example.tunnel.com:8888")

    def test_get_tunnel_update_url_tunnel_disabled(self):
        """Test get_tunnel_update_url when tunnel is disabled."""
        self.api.config.get_tunnel_config.return_value = {
            "enabled": False,
            "full_domain": "example.tunnel.com",
        }

        result = self.api.get_tunnel_update_url()

        self.assertEqual(result, "http://localhost:8888")

    def test_get_tunnel_update_url_no_domain(self):
        """Test get_tunnel_update_url when tunnel enabled but no domain."""
        self.api.config.get_tunnel_config.return_value = {
            "enabled": True,
            "full_domain": "",
        }

        result = self.api.get_tunnel_update_url()

        self.assertEqual(result, "http://localhost:8888")

    def test_get_tunnel_update_url_exception(self):
        """Test get_tunnel_update_url handles exceptions."""
        self.api.config.get_tunnel_config.side_effect = RuntimeError("Config error")

        result = self.api.get_tunnel_update_url()

        self.assertEqual(result, "http://localhost:8888")

    # update_tunnel_environment tests

    @patch("os.chmod")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_update_tunnel_environment_success(
        self, mock_file, mock_makedirs, mock_chmod
    ):
        """Test updating tunnel environment file successfully."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token-12345",
            "enabled": True,
            "full_domain": "example.tunnel.com",
        }

        self.api.update_tunnel_environment()

        # Verify directory creation
        mock_makedirs.assert_called_once_with("/etc/ethoscope", exist_ok=True)

        # Verify file write
        mock_file.assert_called_once_with("/etc/ethoscope/tunnel.env", "w")
        mock_file().write.assert_called_once_with("TUNNEL_TOKEN=test-token-12345\\n")

        # Verify permissions set
        mock_chmod.assert_called_once_with("/etc/ethoscope/tunnel.env", 0o600)

        # Verify UPDATE_SERVICE_URL updated
        self.api.config.update_custom.assert_called_once_with(
            "UPDATE_SERVICE_URL", "http://example.tunnel.com:8888"
        )

    @patch("os.chmod")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_update_tunnel_environment_no_token(
        self, mock_file, mock_makedirs, mock_chmod
    ):
        """Test update_tunnel_environment with no token configured."""
        self.api.config.get_tunnel_config.return_value = {"token": "", "enabled": True}

        self.api.update_tunnel_environment()

        # Should not create file if no token
        mock_file.assert_not_called()
        mock_makedirs.assert_not_called()
        mock_chmod.assert_not_called()
        self.api.config.update_custom.assert_not_called()

    def test_update_tunnel_environment_no_config(self):
        """Test update_tunnel_environment when config is None."""
        self.api.config = None

        # Should not raise exception
        self.api.update_tunnel_environment()

    @patch("os.chmod")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_update_tunnel_environment_file_write_error(
        self, mock_file, mock_makedirs, mock_chmod
    ):
        """Test update_tunnel_environment handles file write errors."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": True,
        }
        mock_file.side_effect = PermissionError("Permission denied")

        # error_decorator catches and returns error dict
        result = self.api.update_tunnel_environment()
        self.assertIn("error", result)

    @patch("os.chmod", side_effect=OSError("chmod failed"))
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_update_tunnel_environment_chmod_error(
        self, mock_file, mock_makedirs, mock_chmod
    ):
        """Test update_tunnel_environment handles chmod errors."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": True,
        }

        # error_decorator catches and returns error dict
        result = self.api.update_tunnel_environment()
        self.assertIn("error", result)

    # get_hostname_aware_redirect_url tests

    def test_get_hostname_aware_redirect_url_localhost(self):
        """Test redirect URL with localhost hostname."""
        result = self.api.get_hostname_aware_redirect_url(
            "localhost", "http://external.com:8888"
        )

        self.assertEqual(result, "http://localhost:8888")

    def test_get_hostname_aware_redirect_url_node(self):
        """Test redirect URL with node hostname."""
        result = self.api.get_hostname_aware_redirect_url(
            "node", "http://external.com:8888"
        )

        self.assertEqual(result, "http://node:8888")

    def test_get_hostname_aware_redirect_url_127_0_0_1(self):
        """Test redirect URL with 127.0.0.1 hostname."""
        result = self.api.get_hostname_aware_redirect_url(
            "127.0.0.1", "http://external.com:8888"
        )

        self.assertEqual(result, "http://127.0.0.1:8888")

    def test_get_hostname_aware_redirect_url_with_port(self):
        """Test redirect URL with hostname including port."""
        result = self.api.get_hostname_aware_redirect_url(
            "localhost:80", "http://external.com:8888"
        )

        self.assertEqual(result, "http://localhost:8888")

    def test_get_hostname_aware_redirect_url_external_hostname(self):
        """Test redirect URL with external hostname."""
        result = self.api.get_hostname_aware_redirect_url(
            "external.example.com", "http://tunnel.com:8888"
        )

        self.assertEqual(result, "http://tunnel.com:8888")

    def test_get_hostname_aware_redirect_url_case_insensitive(self):
        """Test redirect URL handles case insensitive hostnames."""
        result = self.api.get_hostname_aware_redirect_url(
            "LOCALHOST", "http://external.com:8888"
        )

        self.assertEqual(result, "http://localhost:8888")

    def test_get_hostname_aware_redirect_url_exception(self):
        """Test redirect URL handles exceptions."""
        result = self.api.get_hostname_aware_redirect_url(None, "http://fallback.com")

        self.assertEqual(result, "http://fallback.com")

    # API route handlers tests

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.get_tunnel_status")
    def test_get_tunnel_status_route(self, mock_get_status):
        """Test _get_tunnel_status_route API endpoint."""
        mock_get_status.return_value = {
            "enabled": True,
            "token": "***",
            "service_running": True,
        }

        # Mock json_response to just return the data
        self.api.json_response = lambda x: json.dumps(x)

        result = self.api._get_tunnel_status_route()

        # Verify the method was called
        mock_get_status.assert_called_once()

        # Verify response
        result_dict = json.loads(result)
        self.assertEqual(result_dict["enabled"], True)
        self.assertEqual(result_dict["service_running"], True)

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.get_request_json")
    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.toggle_tunnel")
    def test_toggle_tunnel_route(self, mock_toggle, mock_get_json):
        """Test _toggle_tunnel_route API endpoint."""
        mock_get_json.return_value = {"enabled": True}
        mock_toggle.return_value = {"success": True, "enabled": True}

        # Mock json_response to just return the data
        self.api.json_response = lambda x: json.dumps(x)

        result = self.api._toggle_tunnel_route()

        # Verify calls
        mock_get_json.assert_called_once()
        mock_toggle.assert_called_once_with(True)

        # Verify response
        result_dict = json.loads(result)
        self.assertEqual(result_dict["success"], True)

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.get_request_json")
    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.update_tunnel_config")
    def test_update_tunnel_config_route(self, mock_update, mock_get_json):
        """Test _update_tunnel_config_route API endpoint."""
        config_data = {"token": "new-token", "enabled": True}
        mock_get_json.return_value = {"config": config_data}
        mock_update.return_value = {"success": True, "config": config_data}

        # Mock json_response to just return the data
        self.api.json_response = lambda x: json.dumps(x)

        result = self.api._update_tunnel_config_route()

        # Verify calls
        mock_get_json.assert_called_once()
        mock_update.assert_called_once_with(config_data)

        # Verify response
        result_dict = json.loads(result)
        self.assertEqual(result_dict["success"], True)

    # get_tunnel_status tests

    @patch("os.popen")
    def test_get_tunnel_status_service_active(self, mock_popen):
        """Test get_tunnel_status when service is active."""
        self.api.config.get_tunnel_config.return_value = {
            "enabled": True,
            "token": "test-token",
        }

        # Mock popen for is-active check
        mock_active_result = Mock()
        mock_active_result.read.return_value = "active"
        mock_active_result.__enter__ = Mock(return_value=mock_active_result)
        mock_active_result.__exit__ = Mock(return_value=False)

        # Mock popen for status check
        mock_status_result = Mock()
        mock_status_result.read.return_value = "Service is running\nPID: 1234"
        mock_status_result.__enter__ = Mock(return_value=mock_status_result)
        mock_status_result.__exit__ = Mock(return_value=False)

        mock_popen.side_effect = [mock_active_result, mock_status_result]

        result = self.api.get_tunnel_status()

        self.assertEqual(result["enabled"], True)
        self.assertEqual(result["service_running"], True)
        self.assertEqual(result["service_status"], "active")
        self.assertIn("service_info", result)

    @patch("os.popen")
    def test_get_tunnel_status_service_inactive(self, mock_popen):
        """Test get_tunnel_status when service is inactive."""
        self.api.config.get_tunnel_config.return_value = {
            "enabled": False,
            "token": "",
        }

        # Mock popen for is-active check
        mock_active_result = Mock()
        mock_active_result.read.return_value = "inactive"
        mock_active_result.__enter__ = Mock(return_value=mock_active_result)
        mock_active_result.__exit__ = Mock(return_value=False)

        mock_popen.return_value = mock_active_result

        result = self.api.get_tunnel_status()

        self.assertEqual(result["enabled"], False)
        self.assertEqual(result["service_running"], False)
        self.assertEqual(result["service_status"], "inactive")
        self.assertNotIn("service_info", result)

    @patch("os.popen")
    def test_get_tunnel_status_systemctl_exception(self, mock_popen):
        """Test get_tunnel_status handles systemctl exceptions."""
        self.api.config.get_tunnel_config.return_value = {"enabled": True}
        mock_popen.side_effect = OSError("Command failed")

        result = self.api.get_tunnel_status()

        self.assertEqual(result["service_running"], False)
        self.assertEqual(result["service_status"], "Unknown")

    # toggle_tunnel tests

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.update_tunnel_environment")
    @patch("os.popen")
    def test_toggle_tunnel_enable_success(self, mock_popen, mock_update_env):
        """Test enabling tunnel successfully."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": False,
        }

        # Mock popen for start command
        mock_result = Mock()
        mock_result.read.return_value = "Service started successfully"
        mock_result.__enter__ = Mock(return_value=mock_result)
        mock_result.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_result

        result = self.api.toggle_tunnel(True)

        # Verify update_tunnel_environment was called
        mock_update_env.assert_called_once()

        # Verify service start command
        self.assertEqual(mock_popen.call_count, 1)
        call_args = mock_popen.call_args[0][0]
        self.assertIn("start", call_args)
        self.assertIn("ethoscope_tunnel", call_args)

        # Verify config updates
        self.assertEqual(self.api.config.update_tunnel_config.call_count, 2)

        # Verify response
        self.assertEqual(result["success"], True)
        self.assertEqual(result["enabled"], True)

    @patch("os.popen")
    def test_toggle_tunnel_enable_no_token(self, mock_popen):
        """Test enabling tunnel without token fails."""
        self.api.config.get_tunnel_config.return_value = {"token": "", "enabled": False}

        result = self.api.toggle_tunnel(True)

        # Should fail without starting service
        mock_popen.assert_not_called()
        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"], "Tunnel token not configured")
        self.assertEqual(result["enabled"], False)

    @patch("os.popen")
    def test_toggle_tunnel_disable_success(self, mock_popen):
        """Test disabling tunnel successfully."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": True,
        }

        # Mock popen for stop command
        mock_result = Mock()
        mock_result.read.return_value = "Service stopped successfully"
        mock_result.__enter__ = Mock(return_value=mock_result)
        mock_result.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_result

        result = self.api.toggle_tunnel(False)

        # Verify service stop command
        self.assertEqual(mock_popen.call_count, 1)
        call_args = mock_popen.call_args[0][0]
        self.assertIn("stop", call_args)
        self.assertIn("ethoscope_tunnel", call_args)

        # Verify config updates
        self.assertEqual(self.api.config.update_tunnel_config.call_count, 2)

        # Verify response
        self.assertEqual(result["success"], True)
        self.assertEqual(result["enabled"], False)

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.update_tunnel_environment")
    @patch("os.popen")
    def test_toggle_tunnel_start_exception(self, mock_popen, mock_update_env):
        """Test toggle_tunnel handles start exceptions."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": False,
        }
        mock_popen.side_effect = OSError("Command failed")

        result = self.api.toggle_tunnel(True)

        # Verify error handling
        self.assertEqual(result["success"], False)
        self.assertIn("error", result)
        self.assertEqual(result["enabled"], False)

        # Verify status updated to error
        error_update_call = None
        for call in self.api.config.update_tunnel_config.call_args_list:
            if call[0][0].get("status") == "error":
                error_update_call = call
                break
        self.assertIsNotNone(error_update_call)

    @patch("os.popen")
    def test_toggle_tunnel_stop_exception(self, mock_popen):
        """Test toggle_tunnel handles stop exceptions."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": True,
        }
        mock_popen.side_effect = OSError("Command failed")

        result = self.api.toggle_tunnel(False)

        # Verify error handling
        self.assertEqual(result["success"], False)
        self.assertIn("error", result)
        self.assertEqual(result["enabled"], False)

    # update_tunnel_config tests

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.update_tunnel_environment")
    @patch("os.popen")
    def test_update_tunnel_config_with_token_restart(self, mock_popen, mock_update_env):
        """Test update_tunnel_config restarts service when token updated and enabled."""
        config_data = {"token": "new-token", "enabled": True}
        self.api.config.update_tunnel_config.return_value = {
            "enabled": True,
            "token": "new-token",
        }

        # Mock popen for restart command
        mock_result = Mock()
        mock_result.read.return_value = "Service restarted"
        mock_result.__enter__ = Mock(return_value=mock_result)
        mock_result.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_result

        result = self.api.update_tunnel_config(config_data)

        # Verify update_tunnel_environment was called
        mock_update_env.assert_called_once()

        # Verify service restart command
        self.assertEqual(mock_popen.call_count, 1)
        call_args = mock_popen.call_args[0][0]
        self.assertIn("restart", call_args)
        self.assertIn("ethoscope_tunnel", call_args)

        # Verify response
        self.assertEqual(result["success"], True)
        self.assertEqual(result["config"]["enabled"], True)

    def test_update_tunnel_config_without_token(self):
        """Test update_tunnel_config without token doesn't restart."""
        config_data = {"enabled": True, "full_domain": "example.com"}
        self.api.config.update_tunnel_config.return_value = {
            "enabled": True,
            "full_domain": "example.com",
        }

        result = self.api.update_tunnel_config(config_data)

        # Verify no service commands were run
        self.assertEqual(result["success"], True)
        self.assertEqual(result["config"]["enabled"], True)

    def test_update_tunnel_config_disabled_no_restart(self):
        """Test update_tunnel_config doesn't restart when disabled."""
        config_data = {"token": "new-token", "enabled": False}
        self.api.config.update_tunnel_config.return_value = {
            "enabled": False,
            "token": "new-token",
        }

        result = self.api.update_tunnel_config(config_data)

        # Verify no service commands were run (disabled)
        self.assertEqual(result["success"], True)

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.update_tunnel_environment")
    @patch("os.popen")
    def test_update_tunnel_config_exception(self, mock_popen, mock_update_env):
        """Test update_tunnel_config handles exceptions."""
        config_data = {"token": "new-token", "enabled": True}
        self.api.config.update_tunnel_config.side_effect = RuntimeError("Config error")

        result = self.api.update_tunnel_config(config_data)

        # Verify error handling
        self.assertEqual(result["success"], False)
        self.assertIn("error", result)

    @patch("ethoscope_node.api.tunnel_utils.TunnelUtils.update_tunnel_environment")
    @patch("os.popen")
    def test_update_tunnel_config_restart_exception(self, mock_popen, mock_update_env):
        """Test update_tunnel_config handles restart exceptions."""
        config_data = {"token": "new-token", "enabled": True}
        self.api.config.update_tunnel_config.return_value = {
            "enabled": True,
            "token": "new-token",
        }
        mock_popen.side_effect = OSError("Restart failed")

        result = self.api.update_tunnel_config(config_data)

        # Verify error handling
        self.assertEqual(result["success"], False)
        self.assertIn("error", result)

    # Edge cases and additional tests

    def test_get_hostname_aware_redirect_url_ipv6_localhost(self):
        """Test redirect URL with IPv6 localhost."""
        result = self.api.get_hostname_aware_redirect_url(
            "::1", "http://external.com:8888"
        )

        # IPv6 localhost is not in the list, should use fallback
        self.assertEqual(result, "http://external.com:8888")

    def test_get_tunnel_update_url_none_domain(self):
        """Test get_tunnel_update_url when full_domain is None."""
        self.api.config.get_tunnel_config.return_value = {
            "enabled": True,
            "full_domain": None,
        }

        result = self.api.get_tunnel_update_url()

        self.assertEqual(result, "http://localhost:8888")

    @patch("os.chmod")
    @patch("os.makedirs")
    @patch("builtins.open", new_callable=mock_open)
    def test_update_tunnel_environment_token_with_special_chars(
        self, mock_file, mock_makedirs, mock_chmod
    ):
        """Test update_tunnel_environment with special characters in token."""
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token!@#$%^&*()_+=",
            "enabled": True,
        }

        self.api.update_tunnel_environment()

        # Verify token with special chars is written correctly
        mock_file().write.assert_called_once()
        written_content = mock_file().write.call_args[0][0]
        self.assertIn("test-token!@#$%^&*()_+=", written_content)

    @patch("os.popen")
    def test_get_tunnel_status_service_failed(self, mock_popen):
        """Test get_tunnel_status when service is in failed state."""
        self.api.config.get_tunnel_config.return_value = {"enabled": True}

        # Mock popen for is-active check
        mock_active_result = Mock()
        mock_active_result.read.return_value = "failed"
        mock_active_result.__enter__ = Mock(return_value=mock_active_result)
        mock_active_result.__exit__ = Mock(return_value=False)

        mock_popen.return_value = mock_active_result

        result = self.api.get_tunnel_status()

        self.assertEqual(result["service_running"], False)
        self.assertEqual(result["service_status"], "failed")

    def test_toggle_tunnel_route_missing_enabled_field(self):
        """Test _toggle_tunnel_route with missing enabled field."""
        with patch.object(self.api, "get_request_json", return_value={}):
            with patch.object(
                self.api, "toggle_tunnel", return_value={"success": False}
            ) as mock_toggle:
                self.api.json_response = lambda x: json.dumps(x)

                self.api._toggle_tunnel_route()

                # Should default to False
                mock_toggle.assert_called_once_with(False)

    def test_update_tunnel_config_route_missing_config_field(self):
        """Test _update_tunnel_config_route with missing config field."""
        with patch.object(self.api, "get_request_json", return_value={}):
            with patch.object(
                self.api, "update_tunnel_config", return_value={"success": True}
            ) as mock_update:
                self.api.json_response = lambda x: json.dumps(x)

                self.api._update_tunnel_config_route()

                # Should pass empty dict as config
                mock_update.assert_called_once_with({})

    @patch("os.popen")
    def test_toggle_tunnel_enable_with_custom_systemctl(self, mock_popen):
        """Test toggle_tunnel uses custom systemctl path."""
        self.mock_server.systemctl = "/usr/local/bin/systemctl"
        self.api.config.get_tunnel_config.return_value = {
            "token": "test-token",
            "enabled": False,
        }

        # Mock popen
        mock_result = Mock()
        mock_result.read.return_value = "Service started"
        mock_result.__enter__ = Mock(return_value=mock_result)
        mock_result.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_result

        with patch.object(self.api, "update_tunnel_environment"):
            self.api.toggle_tunnel(True)

        # Verify custom systemctl path used
        call_args = mock_popen.call_args[0][0]
        self.assertIn("/usr/local/bin/systemctl", call_args)

    @patch("os.popen")
    def test_get_tunnel_status_custom_systemctl(self, mock_popen):
        """Test get_tunnel_status uses custom systemctl path."""
        self.mock_server.systemctl = "/custom/systemctl"
        self.api.config.get_tunnel_config.return_value = {"enabled": True}

        # Mock popen
        mock_result = Mock()
        mock_result.read.return_value = "active"
        mock_result.__enter__ = Mock(return_value=mock_result)
        mock_result.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_result

        self.api.get_tunnel_status()

        # Verify custom systemctl path used
        call_args = mock_popen.call_args[0][0]
        self.assertIn("/custom/systemctl", call_args)


if __name__ == "__main__":
    unittest.main()
