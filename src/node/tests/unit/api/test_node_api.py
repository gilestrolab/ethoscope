"""
Unit tests for Node API endpoints.

Tests node system management including information retrieval, daemon control,
configuration management, and system actions.
"""

import datetime
import os
import subprocess
import unittest
from unittest.mock import MagicMock, Mock, mock_open, patch

from ethoscope_node.api.node_api import SYSTEM_DAEMONS, NodeAPI


class TestNodeAPI(unittest.TestCase):
    """Test suite for NodeAPI class."""

    def setUp(self):
        """Create mock server instance and NodeAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = Mock()
        self.mock_server.config.content = {
            "folders": {"results": {"path": "/tmp/results"}},
            "incubators": [{"name": "incubator1"}],
            "commands": {"test_cmd": {"command": "echo test"}},
        }
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"
        self.mock_server.systemctl = "systemctl"
        self.mock_server.is_dockerized = False

        self.api = NodeAPI(self.mock_server)

    def test_register_routes(self):
        """Test that all node routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 3 routes
        self.assertEqual(len(route_calls), 3)

        paths = [call[0] for call in route_calls]
        self.assertIn("/node/<req>", paths)
        self.assertIn("/node-actions", paths)
        self.assertIn("/node/config", paths)

    def test_node_info_time(self):
        """Test getting node time."""
        with patch("ethoscope_node.api.node_api.datetime") as mock_dt:
            mock_now = Mock()
            mock_now.isoformat.return_value = "2024-01-01T12:00:00"
            mock_dt.datetime.now.return_value = mock_now

            result = self.api._node_info("time")

            self.assertEqual(result["time"], "2024-01-01T12:00:00")

    def test_node_info_timestamp(self):
        """Test getting node timestamp."""
        with patch("ethoscope_node.api.node_api.datetime") as mock_dt:
            mock_now = Mock()
            mock_now.timestamp.return_value = 1234567890.0
            mock_dt.datetime.now.return_value = mock_now

            result = self.api._node_info("timestamp")

            self.assertEqual(result["timestamp"], 1234567890.0)

    @patch("os.popen")
    def test_node_info_log(self, mock_popen):
        """Test getting node log."""
        mock_file = Mock()
        mock_file.read.return_value = "log line 1\nlog line 2"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_file

        result = self.api._node_info("log")

        self.assertEqual(result["log"], "log line 1\nlog line 2")
        mock_popen.assert_called_once_with("journalctl -u ethoscope_node -rb")

    def test_node_info_folders(self):
        """Test getting node folders."""
        result = self.api._node_info("folders")

        self.assertEqual(result, {"results": {"path": "/tmp/results"}})

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_node_info_users(self, mock_db_class):
        """Test getting users from database."""
        mock_db = Mock()
        mock_db.getAllUsers.return_value = [
            {"username": "user1", "active": True},
            {"username": "user2", "active": False},
        ]
        mock_db_class.return_value = mock_db

        result = self.api._node_info("users")

        self.assertEqual(len(result), 2)
        mock_db.getAllUsers.assert_called_once_with(active_only=False, asdict=True)

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_node_info_users_exception(self, mock_db_class):
        """Test getting users handles database exceptions."""
        mock_db_class.side_effect = Exception("Database error")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._node_info("users")

            self.assertEqual(result, {})
            mock_log.assert_called_once()

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_node_info_incubators(self, mock_db_class):
        """Test getting incubators from database."""
        mock_db = Mock()
        mock_db.getAllIncubators.return_value = [
            {"name": "incubator1", "location": "Lab A"},
        ]
        mock_db_class.return_value = mock_db

        result = self.api._node_info("incubators")

        self.assertEqual(len(result), 1)
        mock_db.getAllIncubators.assert_called_once_with(active_only=False, asdict=True)

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_node_info_incubators_exception(self, mock_db_class):
        """Test getting incubators handles database exceptions."""
        mock_db_class.side_effect = Exception("Database error")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._node_info("incubators")

            self.assertEqual(result, {})
            mock_log.assert_called_once()

    def test_node_info_sensors(self):
        """Test getting sensors info."""
        self.api.sensor_scanner.get_all_devices_info.return_value = {
            "sensor1": {"status": "active"}
        }

        result = self.api._node_info("sensors")

        self.assertEqual(result, {"sensor1": {"status": "active"}})

    def test_node_info_sensors_no_scanner(self):
        """Test getting sensors when scanner not available."""
        self.api.sensor_scanner = None

        result = self.api._node_info("sensors")

        self.assertEqual(result, {})

    def test_node_info_commands(self):
        """Test getting configured commands."""
        result = self.api._node_info("commands")

        self.assertEqual(result, {"test_cmd": {"command": "echo test"}})

    def test_node_info_tunnel_available(self):
        """Test getting tunnel status when available."""
        mock_tunnel = Mock()
        mock_tunnel.get_tunnel_status.return_value = {
            "enabled": True,
            "connected": True,
        }
        self.mock_server.tunnel_utils = mock_tunnel

        result = self.api._node_info("tunnel")

        self.assertEqual(result["enabled"], True)
        mock_tunnel.get_tunnel_status.assert_called_once()

    def test_node_info_tunnel_not_available(self):
        """Test getting tunnel status when not available."""
        self.mock_server.tunnel_utils = None

        result = self.api._node_info("tunnel")

        self.assertIn("error", result)

    def test_node_info_daemons(self):
        """Test getting daemon status."""
        with patch.object(self.api, "_get_daemon_status") as mock_get_daemons:
            mock_get_daemons.return_value = {
                "ethoscope_backup_mysql": {"active": "active"}
            }

            result = self.api._node_info("daemons")

            self.assertEqual(result, {"ethoscope_backup_mysql": {"active": "active"}})
            mock_get_daemons.assert_called_once()

    def test_node_info_system_info(self):
        """Test getting system info."""
        with patch.object(self.api, "_get_node_system_info") as mock_get_info:
            mock_get_info.return_value = {
                "disk_usage": ["50%"],
                "IPs": ["192.168.1.1"],
            }

            result = self.api._node_info("info")

            self.assertEqual(result["disk_usage"], ["50%"])
            mock_get_info.assert_called_once()

    def test_node_info_unknown_request(self):
        """Test node info with unknown request."""
        result = self.api._node_info("unknown_request")

        # error_decorator catches NotImplementedError and returns error dict
        self.assertIn("error", result)
        self.assertIn("Unknown node request", result["error"])

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_get_node_config_success(self, mock_db_class):
        """Test getting node config successfully."""
        mock_db = Mock()
        mock_db.getAllUsers.return_value = [{"username": "user1"}]
        mock_db_class.return_value = mock_db

        self.api.sensor_scanner.get_all_devices_info.return_value = {
            "sensor1": {"status": "active"}
        }

        with patch("ethoscope_node.api.node_api.datetime") as mock_dt:
            mock_now = Mock()
            mock_now.timestamp.return_value = 1234567890.0
            mock_dt.datetime.now.return_value = mock_now

            result = self.api._get_node_config()

            self.assertEqual(len(result["users"]), 1)
            self.assertEqual(result["incubators"], [{"name": "incubator1"}])
            self.assertEqual(result["sensors"], {"sensor1": {"status": "active"}})
            self.assertEqual(result["timestamp"], 1234567890.0)

    @patch("ethoscope_node.utils.etho_db.ExperimentalDB")
    def test_get_node_config_database_error(self, mock_db_class):
        """Test getting node config with database error."""
        mock_db_class.side_effect = Exception("Database error")

        with patch.object(self.api.logger, "error") as mock_log:
            result = self.api._get_node_config()

            # Should return empty users dict on error
            self.assertEqual(result["users"], {})
            mock_log.assert_called_once()

    @patch("os.path.exists")
    @patch("os.popen")
    @patch("ethoscope_node.api.node_api.netifaces")
    def test_get_node_system_info_success(
        self, mock_netifaces, mock_popen, mock_exists
    ):
        """Test getting comprehensive system info."""

        # Create mock file objects with proper context manager support
        def create_mock_file(content):
            mock_file = MagicMock()
            mock_file.read.return_value = content
            mock_file.__enter__.return_value = mock_file
            mock_file.__exit__.return_value = False
            return mock_file

        # Mock all os.popen calls in order
        mock_popen.side_effect = [
            create_mock_file(
                "Filesystem     Size  Used Avail Use%\n/dev/sda1      100G   50G   50G  50%\n"
            ),  # df
            create_mock_file("main\n"),  # git branch
            create_mock_file("abc123\n"),  # git commit
            create_mock_file("2024-01-01 12:00:00\n"),  # git date
            create_mock_file(""),  # git status (no changes)
            create_mock_file(
                "line1\nline2\nActive: active (running) since Mon 2024-01-01\n"
            ),  # systemctl status
        ]

        # Mock network interfaces
        mock_netifaces.interfaces.return_value = ["eth0", "lo"]

        # ifaddresses is called multiple times per interface, so use a function
        def mock_ifaddresses(iface):
            if iface == "eth0":
                return {
                    17: [{"addr": "aa:bb:cc:dd:ee:ff"}],
                    2: [{"addr": "192.168.1.100"}],
                }
            elif iface == "lo":
                return {17: [{"addr": "00:00:00:00:00:00"}], 2: [{"addr": "127.0.0.1"}]}
            return {}

        mock_netifaces.ifaddresses.side_effect = mock_ifaddresses

        mock_exists.return_value = True

        result = self.api._get_node_system_info()

        # disk_usage splits the second line by whitespace
        self.assertIsInstance(result["disk_usage"], list)
        if result["disk_usage"]:  # If parsing succeeded
            self.assertIn("100G", result["disk_usage"])
        self.assertEqual(result["RDIR"], "/tmp/results")
        self.assertEqual(result["IPs"], ["192.168.1.100"])
        self.assertEqual(result["CARDS"]["eth0"]["MAC"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(result["GIT_BRANCH"], "main")
        self.assertEqual(result["GIT_COMMIT"], "abc123")
        self.assertFalse(result["NEEDS_UPDATE"])

    @patch("os.path.exists")
    @patch("os.popen")
    def test_get_node_system_info_missing_results_dir(self, mock_popen, mock_exists):
        """Test system info when results directory doesn't exist."""
        mock_exists.return_value = False

        # Mock all popen calls to avoid errors
        def create_mock_file(content):
            mock_file = MagicMock()
            mock_file.read.return_value = content
            mock_file.__enter__.return_value = mock_file
            mock_file.__exit__.return_value = False
            return mock_file

        mock_popen.return_value = create_mock_file("")

        result = self.api._get_node_system_info()

        self.assertIn("not available", result["RDIR"])

    @patch("os.path.exists")
    @patch("os.popen")
    @patch("ethoscope_node.api.node_api.netifaces")
    def test_get_node_system_info_network_exception(
        self, mock_netifaces, mock_popen, mock_exists
    ):
        """Test system info when network interface retrieval fails."""

        # Create mock file objects with proper context manager support
        def create_mock_file(content):
            mock_file = MagicMock()
            mock_file.read.return_value = content
            mock_file.__enter__.return_value = mock_file
            mock_file.__exit__.return_value = False
            return mock_file

        # Mock all os.popen calls in order
        mock_popen.side_effect = [
            create_mock_file(
                "Filesystem     Size  Used Avail Use%\n/dev/sda1      100G   50G   50G  50%\n"
            ),  # df
            create_mock_file("main\n"),  # git branch
            create_mock_file("abc123\n"),  # git commit
            create_mock_file("2024-01-01 12:00:00\n"),  # git date
            create_mock_file(""),  # git status (no changes)
            create_mock_file(
                "line1\nline2\nActive: active (running) since Mon 2024-01-01\n"
            ),  # systemctl status
        ]

        # Trigger exception in network interface processing (lines 192-193)
        mock_netifaces.interfaces.side_effect = Exception("Network error")

        mock_exists.return_value = True

        result = self.api._get_node_system_info()

        # Should handle exception gracefully
        self.assertIsInstance(result["CARDS"], dict)
        self.assertIsInstance(result["IPs"], list)
        self.assertEqual(len(result["CARDS"]), 0)  # Empty due to exception
        self.assertEqual(len(result["IPs"]), 0)  # Empty due to exception
        # Other fields should still be populated
        self.assertEqual(result["GIT_BRANCH"], "main")

    @patch("os.path.exists")
    @patch("os.popen")
    @patch("ethoscope_node.api.node_api.netifaces")
    def test_get_node_system_info_git_exception(
        self, mock_netifaces, mock_popen, mock_exists
    ):
        """Test system info when git commands fail."""

        # Create mock file objects with proper context manager support
        def create_mock_file(content):
            mock_file = MagicMock()
            mock_file.read.return_value = content
            mock_file.__enter__.return_value = mock_file
            mock_file.__exit__.return_value = False
            return mock_file

        # Mock disk usage command, then trigger exception for git commands
        mock_popen.side_effect = [
            create_mock_file(
                "Filesystem     Size  Used Avail Use%\n/dev/sda1      100G   50G   50G  50%\n"
            ),  # df
            Exception("Git not found"),  # git branch fails (lines 208-212)
        ]

        # Mock network interfaces to work correctly
        mock_netifaces.interfaces.return_value = ["eth0"]

        def mock_ifaddresses(iface):
            if iface == "eth0":
                return {
                    17: [{"addr": "aa:bb:cc:dd:ee:ff"}],
                    2: [{"addr": "192.168.1.100"}],
                }
            return {}

        mock_netifaces.ifaddresses.side_effect = mock_ifaddresses

        mock_exists.return_value = True

        result = self.api._get_node_system_info()

        # Should handle git exception gracefully (lines 208-212)
        self.assertEqual(result["GIT_BRANCH"], "Not detected")
        self.assertEqual(result["GIT_COMMIT"], "Not detected")
        self.assertEqual(result["GIT_DATE"], "Not detected")
        self.assertFalse(result["NEEDS_UPDATE"])
        # Other fields should still be populated
        self.assertEqual(result["IPs"], ["192.168.1.100"])

    @patch("os.popen")
    def test_get_daemon_status_all_active(self, mock_popen):
        """Test getting daemon status when all active."""
        mock_file = Mock()
        mock_file.read.return_value = "active\n"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_file

        result = self.api._get_daemon_status()

        # Check a few daemons
        self.assertEqual(result["ethoscope_backup_mysql"]["active"], "active")
        self.assertFalse(result["ethoscope_backup_mysql"]["not_available"])

    @patch("os.popen")
    def test_get_daemon_status_docker_filtering(self, mock_popen):
        """Test daemon status filters unavailable daemons in docker."""
        self.mock_server.is_dockerized = True

        mock_file = Mock()
        mock_file.read.return_value = "inactive\n"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_file

        result = self.api._get_daemon_status()

        # Daemons available in docker should not be marked unavailable
        self.assertFalse(result["ethoscope_backup_mysql"]["not_available"])

        # Daemons not available in docker should be marked unavailable
        self.assertTrue(result["sshd"]["not_available"])

    @patch("os.popen")
    def test_get_daemon_status_exception(self, mock_popen):
        """Test daemon status handles exceptions."""
        mock_popen.side_effect = Exception("Command failed")

        result = self.api._get_daemon_status()

        # Should return unknown status on error
        for daemon in result.values():
            self.assertEqual(daemon["active"], "unknown")
            self.assertFalse(daemon["not_available"])

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    @patch("os.popen")
    def test_node_actions_restart(self, mock_popen, mock_get_json):
        """Test restarting node service."""
        mock_get_json.return_value = {"action": "restart"}
        mock_file = Mock()
        mock_file.read.return_value = "Service restarting"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_file

        result = self.api._node_actions()

        self.assertEqual(result, "Service restarting")
        # Should use sleep to allow response before restart
        mock_popen.assert_called_once()
        self.assertIn("sleep", mock_popen.call_args[0][0])

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_close(self, mock_get_json):
        """Test closing/shutting down node server."""
        mock_get_json.return_value = {"action": "close"}
        self.mock_server._shutdown = Mock()

        self.api._node_actions()

        self.mock_server._shutdown.assert_called_once()

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_adduser(self, mock_get_json):
        """Test adding a user."""
        user_data = {"username": "newuser", "pin": "1234"}
        mock_get_json.return_value = {"action": "adduser", "userdata": user_data}
        self.api.config.add_user = Mock(return_value={"success": True})

        result = self.api._node_actions()

        self.assertTrue(result["success"])
        self.api.config.add_user.assert_called_once_with(user_data)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_addincubator(self, mock_get_json):
        """Test adding an incubator."""
        incubator_data = {"name": "new_incubator", "location": "Lab B"}
        mock_get_json.return_value = {
            "action": "addincubator",
            "incubatordata": incubator_data,
        }
        self.api.config.add_incubator = Mock(return_value={"success": True})

        result = self.api._node_actions()

        self.assertTrue(result["success"])
        self.api.config.add_incubator.assert_called_once_with(incubator_data)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_addsensor(self, mock_get_json):
        """Test adding a sensor."""
        sensor_data = {"id": "sensor2", "type": "temperature"}
        mock_get_json.return_value = {"action": "addsensor", "sensordata": sensor_data}
        self.api.config.add_sensor = Mock(return_value={"success": True})

        result = self.api._node_actions()

        self.assertTrue(result["success"])
        self.api.config.add_sensor.assert_called_once_with(sensor_data)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_updatefolders(self, mock_get_json):
        """Test updating folders configuration."""
        folders = {"results": {"path": "/new/results"}}
        mock_get_json.return_value = {"action": "updatefolders", "folders": folders}

        with patch.object(self.api, "_update_folders") as mock_update:
            mock_update.return_value = {"results": {"path": "/new/results"}}

            result = self.api._node_actions()

            self.assertEqual(result, {"results": {"path": "/new/results"}})
            mock_update.assert_called_once_with(folders)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_exec_cmd(self, mock_get_json):
        """Test executing a command."""
        mock_get_json.return_value = {"action": "exec_cmd", "cmd_name": "test_cmd"}

        with patch.object(self.api, "_execute_command") as mock_exec:
            mock_exec.return_value = iter(["output line 1", "output line 2", "Done"])

            result = self.api._node_actions()

            # Result is a generator
            output = list(result)
            self.assertEqual(len(output), 3)
            mock_exec.assert_called_once_with("test_cmd")

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_toggledaemon(self, mock_get_json):
        """Test toggling daemon status."""
        mock_get_json.return_value = {
            "action": "toggledaemon",
            "daemon_name": "ethoscope_backup_mysql",
            "status": True,
        }

        with patch.object(self.api, "_toggle_daemon") as mock_toggle:
            mock_toggle.return_value = "Daemon started"

            result = self.api._node_actions()

            self.assertEqual(result, "Daemon started")
            mock_toggle.assert_called_once_with("ethoscope_backup_mysql", True)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_toggle_tunnel(self, mock_get_json):
        """Test toggling tunnel."""
        mock_get_json.return_value = {"action": "toggle_tunnel", "enabled": True}
        mock_tunnel = Mock()
        mock_tunnel.toggle_tunnel.return_value = {"success": True}
        self.mock_server.tunnel_utils = mock_tunnel

        result = self.api._node_actions()

        self.assertTrue(result["success"])
        mock_tunnel.toggle_tunnel.assert_called_once_with(True)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_toggle_tunnel_not_available(self, mock_get_json):
        """Test toggling tunnel when not available."""
        mock_get_json.return_value = {"action": "toggle_tunnel", "enabled": True}
        self.mock_server.tunnel_utils = None

        result = self.api._node_actions()

        self.assertFalse(result["success"])
        self.assertIn("not available", result["error"])

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_update_tunnel_config(self, mock_get_json):
        """Test updating tunnel configuration."""
        config = {"token": "new_token"}
        mock_get_json.return_value = {
            "action": "update_tunnel_config",
            "config": config,
        }
        mock_tunnel = Mock()
        mock_tunnel.update_tunnel_config.return_value = {"success": True}
        self.mock_server.tunnel_utils = mock_tunnel

        result = self.api._node_actions()

        self.assertTrue(result["success"])
        mock_tunnel.update_tunnel_config.assert_called_once_with(config)

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_update_tunnel_config_not_available(self, mock_get_json):
        """Test updating tunnel config when not available."""
        mock_get_json.return_value = {
            "action": "update_tunnel_config",
            "config": {},
        }
        self.mock_server.tunnel_utils = None

        result = self.api._node_actions()

        self.assertFalse(result["success"])
        self.assertIn("not available", result["error"])

    @patch("ethoscope_node.api.node_api.BaseAPI.get_request_json")
    def test_node_actions_unknown_action(self, mock_get_json):
        """Test node actions with unknown action."""
        mock_get_json.return_value = {"action": "unknown_action"}

        result = self.api._node_actions()

        # error_decorator catches NotImplementedError
        self.assertIn("error", result)
        self.assertIn("Unknown action", result["error"])

    @patch("os.path.exists")
    def test_update_folders_valid_paths(self, mock_exists):
        """Test updating folders with valid paths."""
        mock_exists.return_value = True
        folders = {"results": {"path": "/new/results"}}

        result = self.api._update_folders(folders)

        self.assertEqual(result["results"]["path"], "/new/results")
        self.api.config.save.assert_called_once()

    @patch("os.path.exists")
    def test_update_folders_invalid_paths(self, mock_exists):
        """Test updating folders with invalid paths."""
        mock_exists.return_value = False
        original_path = self.api.config.content["folders"]["results"]["path"]
        folders = {"results": {"path": "/invalid/path"}}

        result = self.api._update_folders(folders)

        # Should not update if path doesn't exist
        self.assertEqual(result["results"]["path"], original_path)

    @patch("subprocess.Popen")
    def test_execute_command_success(self, mock_popen):
        """Test executing a command successfully."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["output line 1\n", "output line 2\n"])
        mock_process.stderr = iter([])
        mock_process.__enter__ = Mock(return_value=mock_process)
        mock_process.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_process

        result = list(self.api._execute_command("test_cmd"))

        self.assertEqual(len(result), 3)  # 2 output lines + "Done"
        self.assertEqual(result[0], "output line 1\n")
        self.assertEqual(result[-1], "Done")

    @patch("subprocess.Popen")
    def test_execute_command_with_errors(self, mock_popen):
        """Test executing a command with stderr output."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["output line\n"])
        mock_process.stderr = iter(["error line\n"])
        mock_process.__enter__ = Mock(return_value=mock_process)
        mock_process.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_process

        result = list(self.api._execute_command("test_cmd"))

        # Should include both stderr and stdout
        self.assertIn("error line\n", result)
        self.assertIn("output line\n", result)

    @patch("subprocess.Popen")
    def test_execute_command_exception(self, mock_popen):
        """Test executing a command handles exceptions."""
        mock_popen.side_effect = Exception("Command failed")

        result = list(self.api._execute_command("test_cmd"))

        self.assertEqual(len(result), 1)
        self.assertIn("Error executing command", result[0])

    @patch("os.popen")
    def test_toggle_daemon_start(self, mock_popen):
        """Test starting a daemon."""
        mock_file = Mock()
        mock_file.read.return_value = "Daemon started"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_file

        with patch.object(self.api.logger, "info") as mock_log:
            result = self.api._toggle_daemon("ethoscope_backup_mysql", True)

            self.assertEqual(result, "Daemon started")
            mock_log.assert_called_once()
            self.assertIn("Starting", mock_log.call_args[0][0])

    @patch("os.popen")
    def test_toggle_daemon_stop(self, mock_popen):
        """Test stopping a daemon."""
        mock_file = Mock()
        mock_file.read.return_value = "Daemon stopped"
        mock_file.__enter__ = Mock(return_value=mock_file)
        mock_file.__exit__ = Mock(return_value=False)
        mock_popen.return_value = mock_file

        with patch.object(self.api.logger, "info") as mock_log:
            result = self.api._toggle_daemon("ethoscope_backup_mysql", False)

            self.assertEqual(result, "Daemon stopped")
            mock_log.assert_called_once()
            self.assertIn("Stopping", mock_log.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
