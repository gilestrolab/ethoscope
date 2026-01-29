"""
Unit tests for Bug Report API endpoints.

Tests bug report generation including node system information collection,
device information collection, and error handling.
"""

import datetime
import unittest
from unittest.mock import MagicMock, Mock, patch

from ethoscope_node.api.bugreport_api import (
    DEFAULT_LOG_LINES,
    MAX_LOG_LINES,
    REPORT_VERSION,
    BugReportAPI,
)


class TestBugReportAPI(unittest.TestCase):
    """Test suite for BugReportAPI class."""

    def setUp(self):
        """Create mock server instance and BugReportAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = Mock()
        self.mock_server.config.content = {
            "folders": {"results": {"path": "/tmp/results"}},
        }
        self.mock_server.config.get_device_options.return_value = {"option1": "value1"}
        self.mock_server.config.is_setup_required.return_value = False
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"
        self.mock_server.systemctl = "systemctl"

        self.api = BugReportAPI(self.mock_server)

    def test_register_routes(self):
        """Test that bug report routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 1 route
        self.assertEqual(len(route_calls), 1)

        paths = [call[0] for call in route_calls]
        self.assertIn("/bugreport/generate", paths)

    def test_get_report_metadata(self):
        """Test report metadata generation."""
        with patch("socket.gethostname", return_value="test-node"):
            result = self.api._get_report_metadata()

        self.assertEqual(result["version"], REPORT_VERSION)
        self.assertEqual(result["hostname"], "test-node")
        self.assertIn("generated_at", result)

    def test_get_report_metadata_hostname_exception(self):
        """Test report metadata handles hostname exception."""
        with patch("socket.gethostname", side_effect=Exception("Network error")):
            result = self.api._get_report_metadata()

        self.assertEqual(result["hostname"], "unknown")

    def test_get_system_info(self):
        """Test system info collection."""
        errors = []

        mock_uptime_content = "12345.67 23456.78\n"
        with patch(
            "builtins.open", unittest.mock.mock_open(read_data=mock_uptime_content)
        ):
            result = self.api._get_system_info(errors)

        self.assertIn("platform", result)
        self.assertIn("kernel", result)
        self.assertIn("architecture", result)
        self.assertIn("uptime", result)
        self.assertEqual(len(errors), 0)

    def test_get_system_info_exception(self):
        """Test system info handles exceptions."""
        errors = []

        with patch("platform.platform", side_effect=Exception("Platform error")):
            result = self.api._get_system_info(errors)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("Failed to get system info", errors[0])

    @patch("shutil.disk_usage")
    def test_get_disk_info(self, mock_disk_usage):
        """Test disk info collection."""
        mock_disk_usage.return_value = (
            100 * 1024**3,  # 100 GB total
            50 * 1024**3,  # 50 GB used
            50 * 1024**3,  # 50 GB free
        )
        errors = []

        result = self.api._get_disk_info(errors)

        self.assertEqual(result["total_gb"], 100.0)
        self.assertEqual(result["used_gb"], 50.0)
        self.assertEqual(result["available_gb"], 50.0)
        self.assertEqual(result["percent_used"], 50.0)
        self.assertEqual(len(errors), 0)

    @patch("shutil.disk_usage")
    def test_get_disk_info_exception(self, mock_disk_usage):
        """Test disk info handles exceptions."""
        mock_disk_usage.side_effect = Exception("Disk error")
        errors = []

        result = self.api._get_disk_info(errors)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("Failed to get disk info", errors[0])

    def test_get_memory_info(self):
        """Test memory info collection."""
        errors = []
        meminfo_content = """MemTotal:       16000000 kB
MemFree:         4000000 kB
MemAvailable:    8000000 kB
Buffers:         1000000 kB
"""

        with patch("builtins.open", unittest.mock.mock_open(read_data=meminfo_content)):
            result = self.api._get_memory_info(errors)

        self.assertAlmostEqual(result["total_mb"], 16000000 / 1024, places=0)
        self.assertAlmostEqual(result["available_mb"], 8000000 / 1024, places=0)
        self.assertEqual(result["percent_used"], 50.0)
        self.assertEqual(len(errors), 0)

    def test_get_memory_info_exception(self):
        """Test memory info handles exceptions."""
        errors = []

        with patch("builtins.open", side_effect=Exception("File error")):
            result = self.api._get_memory_info(errors)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("Failed to get memory info", errors[0])

    @patch("ethoscope_node.api.bugreport_api.netifaces")
    def test_get_network_info(self, mock_netifaces):
        """Test network info collection."""
        mock_netifaces.interfaces.return_value = ["eth0", "lo"]

        def mock_ifaddresses(iface):
            if iface == "eth0":
                return {
                    17: [{"addr": "aa:bb:cc:dd:ee:ff"}],
                    2: [{"addr": "192.168.1.100", "netmask": "255.255.255.0"}],
                }
            elif iface == "lo":
                return {
                    17: [{"addr": "00:00:00:00:00:00"}],
                    2: [{"addr": "127.0.0.1", "netmask": "255.0.0.0"}],
                }
            return {}

        mock_netifaces.ifaddresses.side_effect = mock_ifaddresses
        errors = []

        result = self.api._get_network_info(errors)

        self.assertIn("interfaces", result)
        # Should include eth0 but not lo (zero MAC is filtered out)
        self.assertIn("eth0", result["interfaces"])
        self.assertEqual(result["interfaces"]["eth0"]["MAC"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(result["interfaces"]["eth0"]["IP"], "192.168.1.100")
        self.assertEqual(len(errors), 0)

    @patch("ethoscope_node.api.bugreport_api.netifaces")
    def test_get_network_info_exception(self, mock_netifaces):
        """Test network info handles exceptions."""
        mock_netifaces.interfaces.side_effect = Exception("Network error")
        errors = []

        result = self.api._get_network_info(errors)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("Failed to get network info", errors[0])

    @patch("subprocess.run")
    def test_get_git_info(self, mock_run):
        """Test git info collection."""
        # Mock git commands
        mock_run.side_effect = [
            Mock(returncode=0, stdout="main\n"),  # branch
            Mock(returncode=0, stdout="abc1234\n"),  # commit
            Mock(returncode=0, stdout="2024-01-01 12:00:00\n"),  # date
            Mock(returncode=0, stdout=""),  # status (no changes)
        ]
        errors = []

        result = self.api._get_git_info(errors)

        self.assertEqual(result["branch"], "main")
        self.assertEqual(result["commit"], "abc1234")
        self.assertEqual(result["date"], "2024-01-01 12:00:00")
        self.assertFalse(result["has_local_changes"])
        self.assertEqual(len(errors), 0)

    @patch("subprocess.run")
    def test_get_git_info_with_changes(self, mock_run):
        """Test git info when there are local changes."""
        mock_run.side_effect = [
            Mock(returncode=0, stdout="dev\n"),
            Mock(returncode=0, stdout="def5678\n"),
            Mock(returncode=0, stdout="2024-01-02 14:00:00\n"),
            Mock(returncode=0, stdout=" M file.py\n"),  # Has changes
        ]
        errors = []

        result = self.api._get_git_info(errors)

        self.assertTrue(result["has_local_changes"])

    @patch("subprocess.run")
    def test_get_git_info_exception(self, mock_run):
        """Test git info handles exceptions."""
        mock_run.side_effect = Exception("Git not found")
        errors = []

        result = self.api._get_git_info(errors)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("Failed to get git info", errors[0])

    @patch("subprocess.run")
    def test_get_services_status(self, mock_run):
        """Test services status collection."""

        # Mock systemctl calls
        def mock_systemctl(*args, **kwargs):
            cmd = args[0]
            if "is-active" in cmd:
                return Mock(returncode=0, stdout="active\n")
            elif "show" in cmd:
                return Mock(
                    returncode=0,
                    stdout="ActiveEnterTimestamp=Mon 2024-01-01 12:00:00 UTC\n",
                )
            return Mock(returncode=1, stdout="")

        mock_run.side_effect = mock_systemctl
        errors = []

        result = self.api._get_services_status(errors)

        self.assertIn("ethoscope_node", result)
        self.assertEqual(result["ethoscope_node"]["active"], "active")
        self.assertEqual(len(errors), 0)

    @patch("subprocess.run")
    def test_get_node_logs(self, mock_run):
        """Test node logs collection."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Jan 01 12:00:00 node[1234]: Log line 1\nJan 01 12:00:01 node[1234]: Log line 2",
        )
        errors = []

        result = self.api._get_node_logs(errors, 500)

        self.assertEqual(len(result), 2)
        self.assertIn("Log line 1", result[0])
        self.assertEqual(len(errors), 0)

    @patch("subprocess.run")
    def test_get_node_logs_exception(self, mock_run):
        """Test node logs handles exceptions."""
        mock_run.side_effect = Exception("Journalctl error")
        errors = []

        result = self.api._get_node_logs(errors, 500)

        self.assertEqual(result, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Failed to get node logs", errors[0])

    def test_collect_devices_info_no_scanner(self):
        """Test device collection when scanner not available."""
        self.api.device_scanner = None
        errors = []

        result = self.api._collect_devices_info(errors, 500)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertIn("Device scanner not available", errors[0])

    def test_collect_devices_info_offline_device(self):
        """Test device collection with offline device."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "offline",
                "id": "ETHOSCOPE_001",
            }
        }
        errors = []

        result = self.api._collect_devices_info(errors, 500)

        self.assertIn("ETHOSCOPE_001", result)
        self.assertEqual(result["ETHOSCOPE_001"]["status"], "offline")
        self.assertIn("offline", result["ETHOSCOPE_001"]["error"])

    def test_collect_devices_info_online_device(self):
        """Test device collection with online device."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "running",
                "id": "ETHOSCOPE_001",
            }
        }

        mock_device = Mock()
        mock_device.machine_info.return_value = {"hostname": "eth001"}
        mock_device.log.return_value = {"log": "Some log data"}
        self.api.device_scanner.get_device.return_value = mock_device

        errors = []

        result = self.api._collect_devices_info(errors, 500)

        self.assertIn("ETHOSCOPE_001", result)
        self.assertEqual(result["ETHOSCOPE_001"]["status"], "running")
        self.assertEqual(
            result["ETHOSCOPE_001"]["machine_info"], {"hostname": "eth001"}
        )
        self.assertEqual(result["ETHOSCOPE_001"]["log"], "Some log data")

    def test_collect_devices_info_device_error(self):
        """Test device collection handles device errors."""
        self.api.device_scanner.get_all_devices_info.return_value = {
            "ETHOSCOPE_001": {
                "status": "running",
                "id": "ETHOSCOPE_001",
            }
        }

        mock_device = Mock()
        mock_device.machine_info.side_effect = Exception("Connection error")
        mock_device.log.side_effect = Exception("Log error")
        self.api.device_scanner.get_device.return_value = mock_device

        errors = []

        result = self.api._collect_devices_info(errors, 500)

        self.assertIn("ETHOSCOPE_001", result)
        self.assertIn("Failed to get machine info", result["ETHOSCOPE_001"]["error"])

    @patch("subprocess.run")
    def test_collect_backup_status(self, mock_run):
        """Test backup status collection."""

        def mock_systemctl(*args, **kwargs):
            cmd = args[0]
            if "ethoscope_backup_mysql" in cmd:
                return Mock(returncode=0, stdout="active\n")
            elif "ethoscope_backup_unified" in cmd:
                return Mock(returncode=0, stdout="inactive\n")
            return Mock(returncode=1, stdout="")

        mock_run.side_effect = mock_systemctl
        errors = []

        result = self.api._collect_backup_status(errors)

        self.assertIn("mysql", result)
        self.assertIn("rsync", result)
        self.assertTrue(result["mysql"]["available"])
        self.assertTrue(result["rsync"]["available"])

    def test_collect_configuration(self):
        """Test configuration collection."""
        errors = []

        result = self.api._collect_configuration(errors)

        self.assertIn("folders", result)
        self.assertIn("device_options", result)
        self.assertIn("setup_required", result)
        self.assertEqual(len(errors), 0)

    def test_collect_configuration_no_config(self):
        """Test configuration collection when config not available."""
        self.api.config = None
        errors = []

        result = self.api._collect_configuration(errors)

        self.assertEqual(result, {})
        self.assertEqual(len(errors), 0)

    def test_generate_summary(self):
        """Test summary generation."""
        report = {
            "report_metadata": {
                "generated_at": "2024-01-01T12:00:00",
                "hostname": "test-node",
            },
            "node": {
                "disk": {"percent_used": 50, "available_gb": 100},
                "memory": {"percent_used": 30, "available_mb": 8000},
                "git_version": {"branch": "main", "commit": "abc123"},
            },
            "devices": {
                "ETHOSCOPE_001": {"status": "running"},
                "ETHOSCOPE_002": {"status": "offline"},
            },
            "errors": ["Error 1"],
        }

        result = self.api._generate_summary(report)

        self.assertIn("test-node", result)
        self.assertIn("50%", result)
        self.assertIn("main", result)
        self.assertIn("1/2 online", result)
        self.assertIn("1", result)  # Collection errors

    @patch.object(BugReportAPI, "_get_report_metadata")
    @patch.object(BugReportAPI, "_collect_node_info")
    @patch.object(BugReportAPI, "_collect_devices_info")
    @patch.object(BugReportAPI, "_collect_backup_status")
    @patch.object(BugReportAPI, "_collect_configuration")
    @patch.object(BugReportAPI, "_generate_summary")
    @patch("ethoscope_node.api.bugreport_api.bottle")
    def test_generate_bug_report(
        self,
        mock_bottle,
        mock_summary,
        mock_config,
        mock_backup,
        mock_devices,
        mock_node,
        mock_metadata,
    ):
        """Test full bug report generation."""
        mock_metadata.return_value = {"version": "1.0", "hostname": "test"}
        mock_node.return_value = {"system": {}}
        mock_devices.return_value = {}
        mock_backup.return_value = {}
        mock_config.return_value = {}
        mock_summary.return_value = "Summary"

        mock_bottle.request.json = None

        result = self.api._generate_bug_report()

        self.assertIn("report_metadata", result)
        self.assertIn("node", result)
        self.assertIn("devices", result)
        self.assertIn("backup_services", result)
        self.assertIn("configuration", result)
        self.assertIn("_summary", result)
        self.assertIn("errors", result)

    @patch.object(BugReportAPI, "get_request_json")
    @patch.object(BugReportAPI, "_get_report_metadata")
    @patch.object(BugReportAPI, "_collect_node_info")
    @patch.object(BugReportAPI, "_collect_devices_info")
    @patch.object(BugReportAPI, "_collect_backup_status")
    @patch.object(BugReportAPI, "_collect_configuration")
    @patch.object(BugReportAPI, "_generate_summary")
    @patch("ethoscope_node.api.bugreport_api.bottle")
    def test_generate_bug_report_with_custom_log_lines(
        self,
        mock_bottle,
        mock_summary,
        mock_config,
        mock_backup,
        mock_devices,
        mock_node,
        mock_metadata,
        mock_get_json,
    ):
        """Test bug report with custom log lines parameter."""
        mock_get_json.return_value = {"log_lines": 1000}
        mock_metadata.return_value = {"version": "1.0", "hostname": "test"}
        mock_node.return_value = {"system": {}}
        mock_devices.return_value = {}
        mock_backup.return_value = {}
        mock_config.return_value = {}
        mock_summary.return_value = "Summary"

        self.api._generate_bug_report()

        # Verify _collect_node_info was called with 1000 log lines
        mock_node.assert_called_once()
        call_args = mock_node.call_args[0]
        self.assertEqual(call_args[1], 1000)

    @patch.object(BugReportAPI, "get_request_json")
    @patch.object(BugReportAPI, "_get_report_metadata")
    @patch.object(BugReportAPI, "_collect_node_info")
    @patch.object(BugReportAPI, "_collect_devices_info")
    @patch.object(BugReportAPI, "_collect_backup_status")
    @patch.object(BugReportAPI, "_collect_configuration")
    @patch.object(BugReportAPI, "_generate_summary")
    @patch("ethoscope_node.api.bugreport_api.bottle")
    def test_generate_bug_report_max_log_lines(
        self,
        mock_bottle,
        mock_summary,
        mock_config,
        mock_backup,
        mock_devices,
        mock_node,
        mock_metadata,
        mock_get_json,
    ):
        """Test bug report enforces max log lines."""
        mock_get_json.return_value = {"log_lines": 10000}  # Over max
        mock_metadata.return_value = {"version": "1.0", "hostname": "test"}
        mock_node.return_value = {"system": {}}
        mock_devices.return_value = {}
        mock_backup.return_value = {}
        mock_config.return_value = {}
        mock_summary.return_value = "Summary"

        self.api._generate_bug_report()

        # Verify _collect_node_info was called with MAX_LOG_LINES
        mock_node.assert_called_once()
        call_args = mock_node.call_args[0]
        self.assertEqual(call_args[1], MAX_LOG_LINES)


class TestBugReportAPIConstants(unittest.TestCase):
    """Test bug report API constants."""

    def test_report_version(self):
        """Test report version is set."""
        self.assertEqual(REPORT_VERSION, "1.0")

    def test_default_log_lines(self):
        """Test default log lines."""
        self.assertEqual(DEFAULT_LOG_LINES, 500)

    def test_max_log_lines(self):
        """Test max log lines."""
        self.assertEqual(MAX_LOG_LINES, 5000)


if __name__ == "__main__":
    unittest.main()
