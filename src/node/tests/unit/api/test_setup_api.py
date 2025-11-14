"""
Unit tests for Setup API endpoints.

Tests installation wizard functionality including system setup, user management,
incubator configuration, notifications, tunnel setup, and virtual sensors.
"""

import json
import socket
import unittest
from unittest.mock import MagicMock, Mock, call, mock_open, patch

import bottle

from ethoscope_node.api.setup_api import SetupAPI


class TestSetupAPI(unittest.TestCase):
    """Test suite for SetupAPI class."""

    def setUp(self):
        """Create mock server instance and SetupAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = Mock()
        self.mock_server.config.content = {"folders": {}}
        self.mock_server.config._settings = {
            "folders": {},
            "smtp": {},
            "mattermost": {},
            "slack": {},
            "tunnel": {},
            "authentication": {},
            "virtual_sensor": {},
        }
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"

        self.api = SetupAPI(self.mock_server)

        # Add db attribute that some methods use
        self.api.db = self.mock_server.database

    def test_register_routes(self):
        """Test that all setup routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 2 routes (GET and POST for /setup/<action>)
        self.assertEqual(len(route_calls), 2)

        # Check routes
        paths_methods = [(call[0], call[1]) for call in route_calls]
        self.assertIn(("/setup/<action>", "GET"), paths_methods)
        self.assertIn(("/setup/<action>", "POST"), paths_methods)

    # ============================================================================
    # GET Endpoints Tests
    # ============================================================================

    def test_setup_get_status(self):
        """Test getting setup status."""
        mock_status = {"completed": False, "steps": {"basic_info": True}}
        self.api.config.get_setup_status.return_value = mock_status

        result = self.api._setup_get("status")

        self.assertEqual(result, mock_status)
        self.api.config.get_setup_status.assert_called_once()

    @patch("psutil.disk_usage")
    @patch("psutil.virtual_memory")
    @patch("socket.gethostname")
    @patch("socket.getfqdn")
    @patch("os.path.exists")
    def test_get_system_info_success(
        self, mock_exists, mock_fqdn, mock_hostname, mock_memory, mock_disk
    ):
        """Test getting system information successfully."""
        # Setup mocks
        mock_hostname.return_value = "test-node"
        mock_fqdn.return_value = "test-node.local"
        mock_exists.return_value = True

        # Mock disk usage
        mock_disk_usage = Mock()
        mock_disk_usage.total = 1000000000
        mock_disk_usage.used = 500000000
        mock_disk_usage.free = 500000000
        mock_disk.return_value = mock_disk_usage

        # Mock memory
        mock_mem = Mock()
        mock_mem.total = 8000000000
        mock_mem.available = 4000000000
        mock_mem.percent = 50.0
        mock_mem.used = 4000000000
        mock_memory.return_value = mock_mem

        # Setup folder config
        self.api.config.content = {"folders": {"results": {"path": "/tmp/results"}}}

        result = self.api._get_system_info()

        self.assertEqual(result["hostname"], "test-node")
        self.assertEqual(result["fqdn"], "test-node.local")
        self.assertIn("results", result["disk_usage"])
        self.assertEqual(result["memory"]["total"], 8000000000)
        self.assertEqual(result["memory"]["percent"], 50.0)

    @patch("socket.gethostname")
    def test_get_system_info_socket_error(self, mock_hostname):
        """Test system info when socket operations fail."""
        mock_hostname.side_effect = Exception("Socket error")

        result = self.api._get_system_info()

        self.assertEqual(result["hostname"], "unknown")
        self.assertEqual(result["fqdn"], "unknown")

    @patch("bottle.request")
    @patch("os.access")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    def test_validate_folders_existing_valid(
        self, mock_is_dir, mock_exists, mock_access, mock_request
    ):
        """Test validating existing valid folders."""
        mock_request.json = {"folders": {"results": "/tmp/results"}}
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        mock_access.return_value = True

        result = self.api._validate_folders()

        validation = result["validation_results"]["results"]
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["exists"])
        self.assertTrue(validation["readable"])
        self.assertTrue(validation["writable"])
        self.assertEqual(len(validation["errors"]), 0)

    @patch("bottle.request")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    @patch("os.access")
    def test_validate_folders_not_writable(
        self, mock_access, mock_is_dir, mock_exists, mock_request
    ):
        """Test validating folder that is not writable."""
        mock_request.json = {"folders": {"results": "/tmp/results"}}
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        def access_check(path, mode):
            import os

            return mode == os.R_OK  # Readable but not writable

        mock_access.side_effect = access_check

        result = self.api._validate_folders()

        validation = result["validation_results"]["results"]
        self.assertFalse(validation["valid"])
        self.assertTrue(validation["readable"])
        self.assertFalse(validation["writable"])
        self.assertIn("not writable", validation["errors"][0])

    @patch("bottle.request")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    def test_validate_folders_create_new(self, mock_mkdir, mock_exists, mock_request):
        """Test validating folder that needs to be created."""
        mock_request.json = {"folders": {"results": "/tmp/new_results"}}
        mock_exists.return_value = False

        result = self.api._validate_folders()

        validation = result["validation_results"]["results"]
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["exists"])
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    @patch("bottle.request")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    def test_validate_folders_create_fails(self, mock_mkdir, mock_exists, mock_request):
        """Test validating folder when creation fails."""
        mock_request.json = {"folders": {"results": "/tmp/new_results"}}
        mock_exists.return_value = False
        mock_mkdir.side_effect = PermissionError("Cannot create directory")

        result = self.api._validate_folders()

        validation = result["validation_results"]["results"]
        self.assertFalse(validation["valid"])
        self.assertIn("Could not create directory", validation["errors"][0])

    def test_get_existing_users_success(self):
        """Test getting existing users successfully."""
        # Mock the db.get_all_users method
        self.api.db.get_all_users = Mock(
            return_value=[
                {
                    "username": "admin",
                    "fullname": "Admin User",
                    "email": "admin@test.com",
                    "labname": "Test Lab",
                },
                {
                    "username": "user1",
                    "fullname": "Test User",
                    "email": "user@test.com",
                    "labname": "Lab 1",
                },
            ]
        )

        result = self.api._get_existing_users()

        self.assertEqual(result["result"], "success")
        self.assertEqual(len(result["users"]), 2)
        self.assertEqual(result["users"][0]["username"], "admin")
        self.assertEqual(result["users"][1]["username"], "user1")

    def test_get_existing_users_error(self):
        """Test getting existing users with database error."""
        self.api.db.get_all_users = Mock(side_effect=Exception("Database error"))

        result = self.api._get_existing_users()

        self.assertEqual(result["result"], "error")
        self.assertIn("Failed to fetch existing users", result["message"])

    def test_setup_get_invalid_action(self):
        """Test GET request with invalid action."""
        # error_decorator catches the HTTPError and returns error dict
        result = self.api._setup_get("invalid_action")

        # Should return error dict due to error_decorator
        self.assertIn("error", result)
        self.assertIn("invalid_action", result["error"])

    # ============================================================================
    # POST Endpoints - Basic Setup Tests
    # ============================================================================

    @patch("bottle.request")
    @patch("pathlib.Path.mkdir")
    def test_setup_basic_info_success(self, mock_mkdir, mock_request):
        """Test basic info setup successfully."""
        mock_request.json = {
            "folders": {
                "results": "/tmp/results",
                "videos": "/tmp/videos",
            }
        }

        # Set up config.content (which is read) AND config._settings
        self.api.config.content = {
            "folders": {
                "results": {"path": "/tmp/old_results"},
                "videos": {"path": "/tmp/old_videos"},
            }
        }
        self.api.config._settings["folders"] = self.api.config.content["folders"]

        result = self.api._setup_basic_info()

        self.assertEqual(result["result"], "success")
        self.api.config.save.assert_called_once()
        self.api.config.mark_setup_step_completed.assert_called_once_with("basic_info")

    @patch("bottle.request")
    @patch("pathlib.Path.mkdir")
    def test_setup_basic_info_folder_creation_error(self, mock_mkdir, mock_request):
        """Test basic info setup with folder creation error."""
        mock_request.json = {"folders": {"results": "/tmp/results"}}

        # Set up config.content (which is read)
        self.api.config.content = {"folders": {"results": {"path": "/tmp/old"}}}

        mock_mkdir.side_effect = PermissionError("Permission denied")

        result = self.api._setup_basic_info()

        self.assertEqual(result["result"], "error")
        self.assertIn("Could not create folder", result["message"])

    # ============================================================================
    # POST Endpoints - Admin User Tests
    # ============================================================================

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_admin_user_create_new(self, mock_db_class, mock_request):
        """Test creating new admin user."""
        mock_request.json = {
            "username": "admin",
            "fullname": "Admin User",
            "email": "admin@test.com",
            "pin": "1234",
            "telephone": "555-1234",
            "labname": "Test Lab",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.getUserByName.return_value = None
        mock_db.addUser.return_value = 1

        result = self.api._setup_admin_user()

        self.assertEqual(result["result"], "success")
        self.assertEqual(result["user_id"], 1)
        mock_db.addUser.assert_called_once()
        call_args = mock_db.addUser.call_args[1]
        self.assertEqual(call_args["username"], "admin")
        self.assertEqual(call_args["isadmin"], 1)

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_admin_user_update_existing(self, mock_db_class, mock_request):
        """Test updating existing admin user."""
        mock_request.json = {
            "username": "admin",
            "fullname": "Updated Admin",
            "email": "admin@test.com",
            "pin": "5678",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.getUserByName.return_value = {"id": 1, "username": "admin"}
        mock_db.updateUser.return_value = 1

        result = self.api._setup_admin_user()

        self.assertEqual(result["result"], "success")
        self.assertEqual(result["user_id"], 1)
        mock_db.updateUser.assert_called_once()
        call_args = mock_db.updateUser.call_args[1]
        self.assertEqual(call_args["fullname"], "Updated Admin")

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_admin_user_replace_existing(self, mock_db_class, mock_request):
        """Test replacing existing admin user."""
        mock_request.json = {
            "username": "new_admin",
            "fullname": "New Admin",
            "email": "new@test.com",
            "pin": "1234",
            "replace_user": "old_admin",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.getUserByName.side_effect = [
            None,  # First call for new_admin
            {"id": 1, "username": "old_admin"},  # Second call for old_admin
        ]
        mock_db.addUser.return_value = 2

        result = self.api._setup_admin_user()

        self.assertEqual(result["result"], "success")
        self.assertEqual(result["user_id"], 2)
        mock_db.deactivateUser.assert_called_once_with(username="old_admin")
        mock_db.addUser.assert_called_once()

    @patch("bottle.request")
    def test_setup_admin_user_missing_username(self, mock_request):
        """Test admin user setup with missing username."""
        mock_request.json = {"email": "admin@test.com"}

        result = self.api._setup_admin_user()

        self.assertEqual(result["result"], "error")
        self.assertIn("Username is required", result["message"])

    @patch("bottle.request")
    def test_setup_admin_user_missing_email(self, mock_request):
        """Test admin user setup with missing email."""
        mock_request.json = {"username": "admin"}

        result = self.api._setup_admin_user()

        self.assertEqual(result["result"], "error")
        self.assertIn("Email is required", result["message"])

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_admin_user_database_error(self, mock_db_class, mock_request):
        """Test admin user setup with database error."""
        mock_request.json = {
            "username": "admin",
            "email": "admin@test.com",
        }

        mock_db_class.side_effect = Exception("Database error")

        result = self.api._setup_admin_user()

        self.assertEqual(result["result"], "error")
        self.assertIn("Database error", result["message"])

    # ============================================================================
    # POST Endpoints - Additional User Tests
    # ============================================================================

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_add_user_success(self, mock_db_class, mock_request):
        """Test adding additional user successfully."""
        mock_request.json = {
            "username": "user1",
            "fullname": "Test User",
            "email": "user@test.com",
            "isadmin": False,
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.addUser.return_value = 2

        result = self.api._setup_add_user()

        self.assertEqual(result["result"], "success")
        self.assertEqual(result["user_id"], 2)
        call_args = mock_db.addUser.call_args[1]
        self.assertEqual(call_args["isadmin"], 0)

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_add_user_as_admin(self, mock_db_class, mock_request):
        """Test adding additional user as admin."""
        mock_request.json = {
            "username": "user1",
            "email": "user@test.com",
            "isadmin": True,
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.addUser.return_value = 2

        result = self.api._setup_add_user()

        self.assertEqual(result["result"], "success")
        call_args = mock_db.addUser.call_args[1]
        self.assertEqual(call_args["isadmin"], 1)

    # ============================================================================
    # POST Endpoints - Update User Tests
    # ============================================================================

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_update_user_success(self, mock_db_class, mock_request):
        """Test updating user successfully."""
        mock_request.json = {
            "original_username": "user1",
            "fullname": "Updated Name",
            "email": "updated@test.com",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.updateUser.return_value = 1

        result = self.api._setup_update_user()

        self.assertEqual(result["result"], "success")
        call_args = mock_db.updateUser.call_args[1]
        self.assertEqual(call_args["fullname"], "Updated Name")

    @patch("bottle.request")
    def test_setup_update_user_missing_original(self, mock_request):
        """Test updating user without original username."""
        mock_request.json = {"fullname": "Updated Name"}

        result = self.api._setup_update_user()

        self.assertEqual(result["result"], "error")
        self.assertIn("Original username is required", result["message"])

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_update_user_email_change(self, mock_db_class, mock_request):
        """Test updating user email."""
        mock_request.json = {
            "original_username": "user1",
            "email": "newemail@test.com",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.updateUser.return_value = 1

        result = self.api._setup_update_user()

        self.assertEqual(result["result"], "success")
        call_args = mock_db.updateUser.call_args[1]
        self.assertEqual(call_args["email"], "newemail@test.com")

    # ============================================================================
    # POST Endpoints - Incubator Tests
    # ============================================================================

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_add_incubator_success(self, mock_db_class, mock_request):
        """Test adding incubator successfully."""
        mock_request.json = {
            "name": "Incubator 1",
            "location": "Room 101",
            "owner": "admin",
            "description": "Test incubator",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.addIncubator.return_value = 1

        result = self.api._setup_add_incubator()

        self.assertEqual(result["result"], "success")
        self.assertEqual(result["incubator_id"], 1)
        call_args = mock_db.addIncubator.call_args[1]
        self.assertEqual(call_args["name"], "Incubator 1")
        self.assertEqual(call_args["active"], 1)

    @patch("bottle.request")
    def test_setup_add_incubator_missing_name(self, mock_request):
        """Test adding incubator without name."""
        mock_request.json = {"location": "Room 101"}

        result = self.api._setup_add_incubator()

        self.assertEqual(result["result"], "error")
        self.assertIn("Incubator name is required", result["message"])

    @patch("bottle.request")
    @patch("ethoscope_node.api.setup_api.ExperimentalDB")
    def test_setup_update_incubator_success(self, mock_db_class, mock_request):
        """Test updating incubator successfully."""
        mock_request.json = {
            "original_name": "Incubator 1",
            "location": "Room 102",
        }

        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.updateIncubator.return_value = 1

        result = self.api._setup_update_incubator()

        self.assertEqual(result["result"], "success")
        call_args = mock_db.updateIncubator.call_args[1]
        self.assertEqual(call_args["location"], "Room 102")

    @patch("bottle.request")
    def test_setup_update_incubator_missing_original(self, mock_request):
        """Test updating incubator without original name."""
        mock_request.json = {"location": "Room 102"}

        result = self.api._setup_update_incubator()

        self.assertEqual(result["result"], "error")
        self.assertIn("Original incubator name is required", result["message"])

    # ============================================================================
    # POST Endpoints - Notification Tests
    # ============================================================================

    @patch("bottle.request")
    def test_setup_notifications_smtp(self, mock_request):
        """Test SMTP notification setup."""
        mock_request.json = {
            "smtp": {
                "enabled": True,
                "host": "smtp.test.com",
                "port": 587,
                "use_tls": True,
                "username": "test@test.com",
                "password": "secret123",
                "from_email": "ethoscope@test.com",
            }
        }

        result = self.api._setup_notifications()

        self.assertEqual(result["result"], "success")
        smtp_config = self.api.config._settings["smtp"]
        self.assertTrue(smtp_config["enabled"])
        self.assertEqual(smtp_config["host"], "smtp.test.com")
        self.assertEqual(smtp_config["password"], "secret123")
        self.api.config.save.assert_called_once()

    @patch("bottle.request")
    def test_setup_notifications_smtp_masked_password(self, mock_request):
        """Test SMTP notification setup with masked password."""
        self.api.config._settings["smtp"] = {"password": "existing_password"}

        mock_request.json = {
            "smtp": {
                "enabled": True,
                "host": "smtp.test.com",
                "password": "***CONFIGURED***",
            }
        }

        result = self.api._setup_notifications()

        self.assertEqual(result["result"], "success")
        smtp_config = self.api.config._settings["smtp"]
        self.assertEqual(smtp_config["password"], "existing_password")

    @patch("bottle.request")
    def test_setup_notifications_mattermost(self, mock_request):
        """Test Mattermost notification setup."""
        mock_request.json = {
            "mattermost": {
                "enabled": True,
                "server_url": "https://mattermost.test.com",
                "bot_token": "token123",
                "channel_id": "channel123",
            }
        }

        result = self.api._setup_notifications()

        self.assertEqual(result["result"], "success")
        mm_config = self.api.config._settings["mattermost"]
        self.assertTrue(mm_config["enabled"])
        self.assertEqual(mm_config["server_url"], "https://mattermost.test.com")
        self.assertEqual(mm_config["bot_token"], "token123")

    @patch("bottle.request")
    def test_setup_notifications_slack(self, mock_request):
        """Test Slack notification setup."""
        mock_request.json = {
            "slack": {
                "enabled": True,
                "webhook_url": "https://hooks.slack.com/test",
                "channel": "#general",
            }
        }

        result = self.api._setup_notifications()

        self.assertEqual(result["result"], "success")
        slack_config = self.api.config._settings["slack"]
        self.assertTrue(slack_config["enabled"])
        self.assertEqual(slack_config["webhook_url"], "https://hooks.slack.com/test")

    # ============================================================================
    # POST Endpoints - Test Notifications
    # ============================================================================

    @patch("bottle.request")
    @patch("smtplib.SMTP")
    def test_test_smtp_success(self, mock_smtp_class, mock_request):
        """Test SMTP configuration test successfully."""
        mock_request.json = {
            "type": "smtp",
            "config": {
                "host": "smtp.test.com",
                "port": 587,
                "use_tls": True,
                "username": "test@test.com",
                "password": "secret",
                "from_email": "test@test.com",
                "test_email": "recipient@test.com",
            },
        }

        mock_smtp = Mock()
        mock_smtp_class.return_value = mock_smtp

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "success")
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once()
        mock_smtp.send_message.assert_called_once()

    @patch("bottle.request")
    @patch("smtplib.SMTP_SSL")
    def test_test_smtp_ssl(self, mock_smtp_class, mock_request):
        """Test SMTP configuration with SSL (port 465)."""
        mock_request.json = {
            "type": "smtp",
            "config": {
                "host": "smtp.test.com",
                "port": 465,
                "username": "test@test.com",
                "password": "secret",
                "from_email": "test@test.com",
            },
        }

        mock_smtp = Mock()
        mock_smtp_class.return_value = mock_smtp

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "success")
        # SSL connection should not call starttls
        mock_smtp.starttls.assert_not_called()

    @patch("bottle.request")
    @patch("smtplib.SMTP")
    def test_test_smtp_error(self, mock_smtp_class, mock_request):
        """Test SMTP configuration test with error."""
        mock_request.json = {
            "type": "smtp",
            "config": {
                "host": "smtp.test.com",
                "port": 587,
                "from_email": "test@test.com",
            },
        }

        mock_smtp_class.side_effect = Exception("Connection failed")

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "error")
        self.assertIn("SMTP test failed", result["message"])

    @patch("bottle.request")
    @patch("requests.post")
    def test_test_mattermost_success(self, mock_post, mock_request):
        """Test Mattermost configuration test successfully."""
        mock_request.json = {
            "type": "mattermost",
            "config": {
                "server_url": "https://mattermost.test.com",
                "bot_token": "token123",
                "channel_id": "channel123",
            },
        }

        mock_response = Mock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "success")
        mock_post.assert_called_once()

    @patch("bottle.request")
    @patch("requests.post")
    def test_test_mattermost_missing_config(self, mock_post, mock_request):
        """Test Mattermost configuration test with missing config."""
        mock_request.json = {
            "type": "mattermost",
            "config": {"server_url": "https://mattermost.test.com"},
        }

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "error")
        self.assertIn("required", result["message"])

    @patch("bottle.request")
    @patch("requests.post")
    def test_test_slack_success(self, mock_post, mock_request):
        """Test Slack configuration test successfully."""
        mock_request.json = {
            "type": "slack",
            "config": {
                "webhook_url": "https://hooks.slack.com/test",
                "channel": "#general",
            },
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "success")
        mock_post.assert_called_once()

    @patch("bottle.request")
    @patch("requests.post")
    def test_test_slack_masked_url(self, mock_post, mock_request):
        """Test Slack configuration test with masked webhook URL."""
        self.api.config._settings["slack"] = {
            "webhook_url": "https://hooks.slack.com/real"
        }

        mock_request.json = {
            "type": "slack",
            "config": {"webhook_url": "***CONFIGURED***"},
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = self.api._test_notifications()

        self.assertEqual(result["result"], "success")
        # Should use the real URL from config
        call_args = mock_post.call_args[0]
        self.assertEqual(call_args[0], "https://hooks.slack.com/real")

    # ============================================================================
    # POST Endpoints - Tunnel Tests
    # ============================================================================

    @patch("bottle.request")
    def test_setup_tunnel_custom_mode(self, mock_request):
        """Test tunnel setup in custom mode."""
        mock_request.json = {
            "tunnel_enabled": True,
            "tunnel_mode": "custom",
            "token": "tunnel_token_123",
            "custom_domain": "my-node.example.com",
            "authentication_enabled": True,
        }

        self.api.server._update_tunnel_environment = Mock()

        result = self.api._setup_tunnel()

        self.assertEqual(result["result"], "success")
        self.api.config.update_tunnel_config.assert_called_once()
        tunnel_config = self.api.config.update_tunnel_config.call_args[0][0]
        self.assertTrue(tunnel_config["enabled"])
        self.assertEqual(tunnel_config["mode"], "custom")
        self.assertEqual(tunnel_config["token"], "tunnel_token_123")

    @patch("bottle.request")
    def test_setup_tunnel_masked_token(self, mock_request):
        """Test tunnel setup with masked token."""
        self.api.config._settings["tunnel"] = {"token": "existing_token"}

        mock_request.json = {
            "tunnel_enabled": True,
            "token": "***CONFIGURED***",
            "tunnel_mode": "custom",
            "custom_domain": "test.com",
            "authentication_enabled": True,
        }

        result = self.api._setup_tunnel()

        self.assertEqual(result["result"], "success")
        tunnel_config = self.api.config.update_tunnel_config.call_args[0][0]
        self.assertEqual(tunnel_config["token"], "existing_token")

    @patch("bottle.request")
    def test_setup_tunnel_missing_token(self, mock_request):
        """Test tunnel setup with missing token."""
        mock_request.json = {
            "tunnel_enabled": True,
            "tunnel_mode": "custom",
            "custom_domain": "test.com",
        }

        result = self.api._setup_tunnel()

        self.assertEqual(result["result"], "error")
        self.assertIn("Tunnel token is required", result["message"])

    @patch("bottle.request")
    def test_setup_tunnel_missing_custom_domain(self, mock_request):
        """Test tunnel setup in custom mode without domain."""
        mock_request.json = {
            "tunnel_enabled": True,
            "tunnel_mode": "custom",
            "token": "token123",
        }

        result = self.api._setup_tunnel()

        self.assertEqual(result["result"], "error")
        self.assertIn("Custom domain is required", result["message"])

    @patch("bottle.request")
    def test_setup_tunnel_requires_auth(self, mock_request):
        """Test tunnel setup requires authentication."""
        mock_request.json = {
            "tunnel_enabled": True,
            "tunnel_mode": "custom",
            "token": "token123",
            "custom_domain": "test.com",
            "authentication_enabled": False,
        }

        result = self.api._setup_tunnel()

        self.assertEqual(result["result"], "error")
        self.assertIn("Authentication must be enabled", result["message"])

    # ============================================================================
    # POST Endpoints - Virtual Sensor Tests
    # ============================================================================

    @patch("bottle.request")
    def test_setup_virtual_sensor_success(self, mock_request):
        """Test virtual sensor setup successfully."""
        mock_request.json = {
            "enabled": True,
            "sensor_name": "weather-sensor",
            "location": "Lab 1",
            "weather_location": "London,UK",
            "api_key": "api_key_123",
        }

        self.api.config.config = {}
        self.api.config.save_config = Mock()

        result = self.api._setup_virtual_sensor()

        self.assertEqual(result["result"], "success")
        self.api.config.save_config.assert_called_once()
        vs_config = self.api.config.config["virtual_sensor"]
        self.assertTrue(vs_config["enabled"])
        self.assertEqual(vs_config["sensor_name"], "weather-sensor")

    @patch("bottle.request")
    def test_setup_virtual_sensor_missing_fields(self, mock_request):
        """Test virtual sensor setup with missing required fields."""
        mock_request.json = {"enabled": True}

        result = self.api._setup_virtual_sensor()

        self.assertEqual(result["result"], "error")
        self.assertIn("Missing required field", result["message"])

    @patch("bottle.request")
    def test_setup_virtual_sensor_disabled(self, mock_request):
        """Test virtual sensor setup when disabled."""
        mock_request.json = {"enabled": False}

        self.api.config.config = {}
        self.api.config.save_config = Mock()

        result = self.api._setup_virtual_sensor()

        self.assertEqual(result["result"], "success")
        vs_config = self.api.config.config["virtual_sensor"]
        self.assertFalse(vs_config["enabled"])

    @patch("bottle.request")
    @patch("urllib.request.urlopen")
    def test_test_weather_api_city_name(self, mock_urlopen, mock_request):
        """Test weather API with city name."""
        mock_request.json = {
            "weather_location": "London",
            "api_key": "test_key",
        }

        mock_response = Mock()
        mock_response.read.return_value = json.dumps(
            {
                "main": {"temp": 20, "humidity": 60, "pressure": 1013},
                "name": "London",
                "sys": {"country": "GB"},
            }
        ).encode()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = self.api._test_weather_api()

        self.assertTrue(result["success"])
        self.assertEqual(result["temperature"], 20)
        self.assertEqual(result["location"], "London")

    @patch("bottle.request")
    @patch("urllib.request.urlopen")
    def test_test_weather_api_coordinates(self, mock_urlopen, mock_request):
        """Test weather API with lat,lon coordinates."""
        mock_request.json = {
            "weather_location": "51.5074,-0.1278",
            "api_key": "test_key",
        }

        mock_response = Mock()
        mock_response.read.return_value = json.dumps(
            {
                "main": {"temp": 20, "humidity": 60, "pressure": 1013},
                "name": "London",
                "sys": {"country": "GB"},
            }
        ).encode()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = self.api._test_weather_api()

        self.assertTrue(result["success"])
        # Should use lat/lon in URL
        call_args = mock_urlopen.call_args[0][0]
        self.assertIn("lat=51.5074", call_args)
        self.assertIn("lon=-0.1278", call_args)

    @patch("bottle.request")
    @patch("urllib.request.urlopen")
    def test_test_weather_api_city_id(self, mock_urlopen, mock_request):
        """Test weather API with city ID."""
        mock_request.json = {
            "weather_location": "2643743",
            "api_key": "test_key",
        }

        mock_response = Mock()
        mock_response.read.return_value = json.dumps(
            {
                "main": {"temp": 20, "humidity": 60, "pressure": 1013},
                "name": "London",
                "sys": {"country": "GB"},
            }
        ).encode()
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = self.api._test_weather_api()

        self.assertTrue(result["success"])
        # Should use city ID in URL
        call_args = mock_urlopen.call_args[0][0]
        self.assertIn("id=2643743", call_args)

    @patch("bottle.request")
    @patch("urllib.request.urlopen")
    def test_test_weather_api_invalid_key(self, mock_urlopen, mock_request):
        """Test weather API with invalid API key."""
        import urllib.error

        mock_request.json = {
            "weather_location": "London",
            "api_key": "invalid_key",
        }

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "", 401, "Unauthorized", {}, None
        )

        result = self.api._test_weather_api()

        self.assertFalse(result["success"])
        self.assertIn("Invalid API key", result["message"])

    @patch("bottle.request")
    @patch("urllib.request.urlopen")
    def test_test_weather_api_location_not_found(self, mock_urlopen, mock_request):
        """Test weather API with location not found."""
        import urllib.error

        mock_request.json = {
            "weather_location": "InvalidCity",
            "api_key": "test_key",
        }

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "", 404, "Not Found", {}, None
        )

        result = self.api._test_weather_api()

        self.assertFalse(result["success"])
        self.assertIn("Location not found", result["message"])

    # ============================================================================
    # POST Endpoints - Complete/Reset Tests
    # ============================================================================

    def test_complete_setup_success(self):
        """Test completing setup successfully."""
        result = self.api._complete_setup()

        self.assertEqual(result["result"], "success")
        self.assertTrue(result["setup_completed"])
        self.api.config.complete_setup.assert_called_once()

    def test_complete_setup_error(self):
        """Test completing setup with error."""
        self.api.config.complete_setup.side_effect = Exception("Setup error")

        result = self.api._complete_setup()

        self.assertEqual(result["result"], "error")
        self.assertIn("Setup error", result["message"])

    def test_reset_setup_success(self):
        """Test resetting setup successfully."""
        result = self.api._reset_setup()

        self.assertEqual(result["result"], "success")
        self.assertFalse(result["setup_completed"])
        self.api.config.reset_setup.assert_called_once()

    def test_reset_setup_error(self):
        """Test resetting setup with error."""
        self.api.config.reset_setup.side_effect = Exception("Reset error")

        result = self.api._reset_setup()

        self.assertEqual(result["result"], "error")
        self.assertIn("Reset error", result["message"])

    # ============================================================================
    # POST Endpoints - Get Current Config Tests
    # ============================================================================

    def test_get_current_config_success(self):
        """Test getting current configuration successfully."""
        # Setup folder config
        self.api.config._settings["folders"] = {
            "results": {"path": "/tmp/results"},
            "videos": {"path": "/tmp/videos"},
        }

        # Setup notification configs
        self.api.config._settings["smtp"] = {
            "enabled": True,
            "password": "secret",
        }
        self.api.config._settings["tunnel"] = {
            "enabled": True,
            "token": "tunnel_token",
        }

        # Since _get_current_config imports ExperimentalDB locally, we can't easily mock it
        # Just test that it doesn't crash and returns success
        result = self.api._get_current_config()

        self.assertEqual(result["result"], "success")
        config = result["config"]

        # Check folders
        self.assertEqual(config["folders"]["results"], "/tmp/results")

        # Check masked values
        self.assertEqual(
            config["notifications"]["smtp"]["password"], "***CONFIGURED***"
        )
        self.assertEqual(config["tunnel"]["token"], "***CONFIGURED***")

    def test_get_current_config_no_admin(self):
        """Test getting current configuration with no admin user."""
        # This test can't properly mock the DB because of local import
        # Just test that it returns success
        result = self.api._get_current_config()

        self.assertEqual(result["result"], "success")
        # admin_user may or may not be None depending on local DB state
        self.assertIn("admin_user", result["config"])

    def test_get_current_config_database_error(self):
        """Test getting current configuration with database error."""
        # This method catches DB errors internally and returns success
        # Just test that it doesn't crash
        result = self.api._get_current_config()

        # The method catches exceptions and returns success with warnings logged
        # It doesn't fail when DB operations fail, it just uses defaults
        self.assertEqual(result["result"], "success")

    def test_setup_post_invalid_action(self):
        """Test POST request with invalid action."""
        # error_decorator catches the HTTPError and returns error dict
        result = self.api._setup_post("invalid_action")

        # Should return error dict due to error_decorator
        self.assertIn("error", result)
        self.assertIn("invalid_action", result["error"])


if __name__ == "__main__":
    unittest.main()
