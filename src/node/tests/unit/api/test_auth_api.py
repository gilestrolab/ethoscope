"""
Unit tests for Authentication API endpoints.

Tests login, logout, session management, and PIN change functionality.
"""

import unittest
from unittest.mock import Mock, patch

from ethoscope_node.api.auth_api import AuthAPI


def create_auth_mock():
    """Helper to create properly configured auth middleware mock."""
    mock_auth = Mock()
    mock_auth.config = Mock()
    mock_auth.config._settings = {"authentication": {"enabled": True}}
    mock_auth.is_authenticated.return_value = True
    mock_auth.is_admin.return_value = False
    return mock_auth


def setup_decorator_auth_mock():
    """
    Helper to create auth middleware mock that works with @require_auth decorator.

    The @require_auth decorator accesses bottle.app().auth_middleware,
    so we need to return a mock that bypasses auth checks.
    """
    mock_auth = Mock()
    mock_auth.config = Mock()
    mock_auth.config._settings = {"authentication": {"enabled": False}}  # Bypass auth
    mock_auth.is_authenticated.return_value = True
    return mock_auth


class TestAuthAPI(unittest.TestCase):
    """Test suite for AuthAPI class."""

    def setUp(self):
        """Create mock server instance and AuthAPI for testing."""
        self.mock_server = Mock()
        self.mock_server.app = Mock()
        self.mock_server.config = Mock()
        self.mock_server.config._settings = {}
        self.mock_server.device_scanner = Mock()
        self.mock_server.sensor_scanner = Mock()
        self.mock_server.database = Mock()
        self.mock_server.results_dir = "/tmp/results"
        self.mock_server.sensors_dir = "/tmp/sensors"
        self.mock_server.roi_templates_dir = "/tmp/templates"
        self.mock_server.tmp_imgs_dir = "/tmp/imgs"

        self.api = AuthAPI(self.mock_server)

    def test_register_routes(self):
        """Test that all auth routes are registered."""
        route_calls = []

        def mock_route(path, method):
            def decorator(func):
                route_calls.append((path, method, func.__name__))
                return func

            return decorator

        self.api.app.route = mock_route
        self.api.register_routes()

        # Should register 7 routes
        self.assertEqual(len(route_calls), 7)

        paths = [call[0] for call in route_calls]
        self.assertIn("/auth/login", paths)
        self.assertIn("/auth/logout", paths)
        self.assertIn("/auth/session", paths)
        self.assertIn("/auth/change-pin", paths)
        self.assertIn("/auth/sessions", paths)
        self.assertIn("/auth/sessions/<username>", paths)
        self.assertIn("/api/auth/check", paths)

    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_login_success(self, mock_get_json):
        """Test successful user login."""
        mock_get_json.return_value = {"username": "testuser", "pin": "1234"}

        # Mock auth middleware
        mock_auth = Mock()
        mock_auth.login_user.return_value = "session_token_123"
        self.api.app.auth_middleware = mock_auth

        # Mock database user retrieval
        self.api.database.getUserByName.return_value = {
            "username": "testuser",
            "fullname": "Test User",
            "email": "test@example.com",
            "isadmin": 1,
            "labname": "Test Lab",
        }

        result = self.api._login()

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Login successful")
        self.assertEqual(result["user"]["username"], "testuser")
        self.assertTrue(result["user"]["isadmin"])
        mock_auth.login_user.assert_called_once_with("testuser", "1234")

    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_login_missing_username(self, mock_get_json):
        """Test login with missing username."""
        mock_get_json.return_value = {"username": "", "pin": "1234"}

        result = self.api._login()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Username is required")

    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_login_missing_pin(self, mock_get_json):
        """Test login with missing PIN."""
        mock_get_json.return_value = {"username": "testuser", "pin": ""}

        result = self.api._login()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "PIN is required")

    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_login_no_auth_middleware(self, mock_get_json):
        """Test login when auth middleware not available."""
        mock_get_json.return_value = {"username": "testuser", "pin": "1234"}
        self.api.app.auth_middleware = None

        result = self.api._login()

        self.assertFalse(result["success"])
        self.assertIn("Authentication system not available", result["message"])

    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_login_failed_authentication(self, mock_get_json):
        """Test login with failed authentication."""
        mock_get_json.return_value = {"username": "baduser", "pin": "wrong"}

        mock_auth = Mock()
        mock_auth.login_user.return_value = None  # Failed login
        self.api.app.auth_middleware = mock_auth

        result = self.api._login()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Invalid username or PIN")

    def test_logout_success(self):
        """Test successful user logout."""
        mock_auth = Mock()
        mock_auth.get_current_user.return_value = {"username": "testuser"}
        mock_auth.logout_user.return_value = True
        self.api.app.auth_middleware = mock_auth

        result = self.api._logout()

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Logout successful")
        mock_auth.logout_user.assert_called_once()

    def test_logout_no_middleware(self):
        """Test logout when auth middleware not available."""
        self.api.app.auth_middleware = None

        result = self.api._logout()

        self.assertFalse(result["success"])
        self.assertIn("Authentication system not available", result["message"])

    def test_logout_no_session(self):
        """Test logout with no active session."""
        mock_auth = Mock()
        mock_auth.get_current_user.return_value = None
        mock_auth.logout_user.return_value = False
        self.api.app.auth_middleware = mock_auth

        result = self.api._logout()

        self.assertFalse(result["success"])
        self.assertIn("no active session", result["message"])

    def test_get_session_authenticated(self):
        """Test getting session info for authenticated user."""
        mock_auth = Mock()
        mock_auth.get_current_user.return_value = {
            "username": "testuser",
            "fullname": "Test User",
            "email": "test@example.com",
            "telephone": "123-456-7890",
            "labname": "Test Lab",
            "isadmin": 1,
            "active": 1,
        }
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": True}}

        result = self.api._get_session()

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "testuser")
        self.assertTrue(result["user"]["isadmin"])

    def test_get_session_not_authenticated(self):
        """Test getting session info when not authenticated."""
        mock_auth = Mock()
        mock_auth.get_current_user.return_value = None
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": True}}

        result = self.api._get_session()

        self.assertFalse(result["authenticated"])
        self.assertIsNone(result["user"])

    def test_get_session_auth_disabled(self):
        """Test getting session when authentication is disabled."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": False}}

        result = self.api._get_session()

        # Should return mock system user when auth disabled
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "system")
        self.assertTrue(result["user"]["isadmin"])

    def test_get_session_no_middleware(self):
        """Test getting session when middleware not available."""
        self.api.app.auth_middleware = None

        result = self.api._get_session()

        self.assertFalse(result["authenticated"])
        self.assertIn("Authentication system not available", result["message"])

    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_login_exception_handling(self, mock_get_json):
        """Test login with unexpected exception."""
        mock_get_json.side_effect = Exception("Unexpected error")

        result = self.api._login()

        self.assertFalse(result["success"])
        self.assertIn("server error", result["message"])

    def test_logout_exception_handling(self):
        """Test logout with unexpected exception."""
        mock_auth = Mock()
        mock_auth.get_current_user.side_effect = Exception("Session error")
        self.api.app.auth_middleware = mock_auth

        result = self.api._logout()

        self.assertFalse(result["success"])
        self.assertIn("server error", result["message"])

    def test_get_session_alternative_config_method(self):
        """Test get_session using get_authentication_config method."""
        mock_auth = Mock()
        mock_auth.get_current_user.return_value = {
            "username": "testuser",
            "fullname": "Test User",
            "email": "test@example.com",
            "telephone": "",
            "labname": "",
            "isadmin": 0,
            "active": 1,
        }
        self.api.app.auth_middleware = mock_auth

        # Use alternative config method
        self.api.config.get_authentication_config = Mock(return_value={"enabled": True})
        delattr(self.api.config, "_settings")

        result = self.api._get_session()

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "testuser")

    def test_get_session_config_error(self):
        """Test get_session when config access raises exception."""
        mock_auth = Mock()
        mock_auth.get_current_user.return_value = None
        self.api.app.auth_middleware = mock_auth

        # Simulate config access error
        type(self.api.config)._settings = property(
            lambda self: (_ for _ in ()).throw(Exception("Config error"))
        )

        result = self.api._get_session()

        # Should default to auth disabled (returns system user when auth disabled)
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "system")

    def test_get_session_exception(self):
        """Test get_session with unexpected exception."""
        mock_auth = Mock()
        mock_auth.get_current_user.side_effect = Exception("Database error")
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": True}}

        result = self.api._get_session()

        self.assertFalse(result["authenticated"])
        self.assertIn("Error retrieving session", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_success(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test successful PIN change."""
        # Setup auth middleware mock for decorator
        mock_auth = Mock()
        mock_auth.config._settings = {"authentication": {"enabled": False}}
        mock_auth.is_authenticated.return_value = True
        mock_bottle_app.return_value.auth_middleware = mock_auth

        mock_get_json.return_value = {
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }
        mock_current_user.return_value = {"username": "testuser"}

        self.api.database.verify_pin.return_value = True
        self.api.database.hash_pin.return_value = "hashed_5678"
        self.api.database.updateUser.return_value = 1

        result = self.api._change_pin()

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "PIN changed successfully")
        self.api.database.verify_pin.assert_called_once_with("testuser", "1234")
        self.api.database.updateUser.assert_called_once_with(
            username="testuser", pin="hashed_5678"
        )

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_missing_current_pin(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change with missing current PIN."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }
        mock_current_user.return_value = {"username": "testuser"}

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Current PIN is required")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_missing_new_pin(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change with missing new PIN."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "1234",
            "new_pin": "",
            "confirm_pin": "",
        }
        mock_current_user.return_value = {"username": "testuser"}

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "New PIN is required")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_mismatch(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change with mismatched confirmation."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "9999",
        }
        mock_current_user.return_value = {"username": "testuser"}

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertIn("does not match", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_no_session(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change with no active session."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }
        mock_current_user.return_value = None

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No active session")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_invalid_current(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change with incorrect current PIN."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "wrong",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }
        mock_current_user.return_value = {"username": "testuser"}
        self.api.database.verify_pin.return_value = False

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Current PIN is incorrect")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_hash_failure(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change when hashing fails."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }
        mock_current_user.return_value = {"username": "testuser"}
        self.api.database.verify_pin.return_value = True
        self.api.database.hash_pin.return_value = None

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertIn("Failed to process new PIN", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_update_failure(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change when database update fails."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.return_value = {
            "current_pin": "1234",
            "new_pin": "5678",
            "confirm_pin": "5678",
        }
        mock_current_user.return_value = {"username": "testuser"}
        self.api.database.verify_pin.return_value = True
        self.api.database.hash_pin.return_value = "hashed_5678"
        self.api.database.updateUser.return_value = -1

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Failed to update PIN")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    @patch("ethoscope_node.api.auth_api.BaseAPI.get_request_json")
    def test_change_pin_exception(
        self, mock_get_json, mock_current_user, mock_bottle_app
    ):
        """Test PIN change with unexpected exception."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_get_json.side_effect = Exception("Database error")
        mock_current_user.return_value = {"username": "testuser"}

        result = self.api._change_pin()

        self.assertFalse(result["success"])
        self.assertIn("server error", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_get_all_sessions_admin(self, mock_current_user, mock_bottle_app):
        """Test getting all sessions as admin."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "admin", "isadmin": 1}

        mock_auth = Mock()
        mock_session_manager = Mock()
        mock_session_manager.get_active_sessions.return_value = [
            {"username": "user1", "session_id": "abc123"},
            {"username": "user2", "session_id": "def456"},
        ]
        mock_auth.session_manager = mock_session_manager
        self.api.app.auth_middleware = mock_auth

        result = self.api._get_all_sessions()

        self.assertTrue(result["success"])
        self.assertEqual(len(result["sessions"]), 2)
        self.assertEqual(result["total_count"], 2)
        mock_session_manager.get_active_sessions.assert_called_once_with()

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_get_all_sessions_regular_user(self, mock_current_user, mock_bottle_app):
        """Test getting sessions as regular user (own sessions only)."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "testuser", "isadmin": 0}

        mock_auth = Mock()
        mock_session_manager = Mock()
        mock_session_manager.get_active_sessions.return_value = [
            {"username": "testuser", "session_id": "abc123"}
        ]
        mock_auth.session_manager = mock_session_manager
        self.api.app.auth_middleware = mock_auth

        result = self.api._get_all_sessions()

        self.assertTrue(result["success"])
        self.assertEqual(len(result["sessions"]), 1)
        mock_session_manager.get_active_sessions.assert_called_once_with("testuser")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_get_all_sessions_no_middleware(self, mock_current_user, mock_bottle_app):
        """Test getting sessions when middleware not available."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "testuser", "isadmin": 0}
        self.api.app.auth_middleware = None

        result = self.api._get_all_sessions()

        self.assertFalse(result["success"])
        self.assertIn("Authentication system not available", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_get_all_sessions_no_active_session(
        self, mock_current_user, mock_bottle_app
    ):
        """Test getting sessions with no active session."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = None

        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth

        result = self.api._get_all_sessions()

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No active session")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_get_all_sessions_exception(self, mock_current_user, mock_bottle_app):
        """Test getting sessions with unexpected exception."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "testuser", "isadmin": 0}

        mock_auth = Mock()
        mock_auth.session_manager.get_active_sessions.side_effect = Exception(
            "Session error"
        )
        self.api.app.auth_middleware = mock_auth

        result = self.api._get_all_sessions()

        self.assertFalse(result["success"])
        self.assertIn("Failed to retrieve sessions", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_admin(self, mock_current_user, mock_bottle_app):
        """Test admin terminating another user's sessions."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "admin", "isadmin": 1}

        mock_auth = Mock()
        mock_session_manager = Mock()
        mock_session_manager.destroy_user_sessions.return_value = True
        mock_auth.session_manager = mock_session_manager
        self.api.app.auth_middleware = mock_auth

        result = self.api._terminate_user_sessions("targetuser")

        self.assertTrue(result["success"])
        self.assertIn("targetuser", result["message"])
        mock_session_manager.destroy_user_sessions.assert_called_once_with("targetuser")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_own(self, mock_current_user, mock_bottle_app):
        """Test user terminating their own sessions."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "testuser", "isadmin": 0}

        mock_auth = Mock()
        mock_session_manager = Mock()
        mock_session_manager.destroy_user_sessions.return_value = True
        mock_auth.session_manager = mock_session_manager
        self.api.app.auth_middleware = mock_auth

        result = self.api._terminate_user_sessions("testuser")

        self.assertTrue(result["success"])
        mock_session_manager.destroy_user_sessions.assert_called_once_with("testuser")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_insufficient_privileges(
        self, mock_current_user, mock_bottle_app
    ):
        """Test regular user trying to terminate another user's sessions."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "testuser", "isadmin": 0}

        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth

        result = self.api._terminate_user_sessions("otheruser")

        self.assertFalse(result["success"])
        self.assertIn("Insufficient privileges", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_no_middleware(
        self, mock_current_user, mock_bottle_app
    ):
        """Test terminating sessions when middleware not available."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "admin", "isadmin": 1}
        self.api.app.auth_middleware = None

        result = self.api._terminate_user_sessions("testuser")

        self.assertFalse(result["success"])
        self.assertIn("Authentication system not available", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_no_active_session(
        self, mock_current_user, mock_bottle_app
    ):
        """Test terminating sessions with no active session."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = None

        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth

        result = self.api._terminate_user_sessions("testuser")

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No active session")

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_failure(self, mock_current_user, mock_bottle_app):
        """Test terminating sessions when destroy operation fails."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "admin", "isadmin": 1}

        mock_auth = Mock()
        mock_session_manager = Mock()
        mock_session_manager.destroy_user_sessions.return_value = False
        mock_auth.session_manager = mock_session_manager
        self.api.app.auth_middleware = mock_auth

        result = self.api._terminate_user_sessions("testuser")

        self.assertFalse(result["success"])
        self.assertIn("Failed to terminate sessions", result["message"])

    @patch("bottle.app")
    @patch("ethoscope_node.api.auth_api.get_current_user")
    def test_terminate_user_sessions_exception(
        self, mock_current_user, mock_bottle_app
    ):
        """Test terminating sessions with unexpected exception."""
        mock_bottle_app.return_value.auth_middleware = setup_decorator_auth_mock()
        mock_current_user.return_value = {"username": "admin", "isadmin": 1}

        mock_auth = Mock()
        mock_auth.session_manager.destroy_user_sessions.side_effect = Exception(
            "Session error"
        )
        self.api.app.auth_middleware = mock_auth

        result = self.api._terminate_user_sessions("testuser")

        self.assertFalse(result["success"])
        self.assertIn("Failed to terminate sessions", result["message"])

    def test_check_auth_no_middleware(self):
        """Test check auth when middleware not available."""
        self.api.app.auth_middleware = None

        result = self.api._check_auth()

        self.assertFalse(result["authenticated"])
        self.assertIsNone(result["user"])

    def test_check_auth_authenticated(self):
        """Test check auth with authenticated user."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": True}}

        # Mock get_current_user at the module level
        with patch("ethoscope_node.api.auth_api.get_current_user") as mock_get_user:
            mock_get_user.return_value = {
                "username": "testuser",
                "fullname": "Test User",
                "email": "test@example.com",
                "isadmin": 1,
            }

            result = self.api._check_auth()

            self.assertTrue(result["authenticated"])
            self.assertEqual(result["user"]["username"], "testuser")
            self.assertTrue(result["user"]["is_admin"])

    def test_check_auth_not_authenticated(self):
        """Test check auth when not authenticated."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": True}}

        with patch("ethoscope_node.api.auth_api.get_current_user") as mock_get_user:
            mock_get_user.return_value = None

            result = self.api._check_auth()

            self.assertFalse(result["authenticated"])
            self.assertIsNone(result["user"])

    def test_check_auth_disabled(self):
        """Test check auth when authentication is disabled."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": False}}

        result = self.api._check_auth()

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "system")
        self.assertTrue(result["user"]["is_admin"])

    def test_check_auth_alternative_config_method(self):
        """Test check auth using get_authentication_config method."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth
        self.api.config.get_authentication_config = Mock(
            return_value={"enabled": False}
        )
        delattr(self.api.config, "_settings")

        result = self.api._check_auth()

        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "system")

    def test_check_auth_config_error(self):
        """Test check auth when config access raises exception."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth

        # Simulate config access error
        type(self.api.config)._settings = property(
            lambda self: (_ for _ in ()).throw(Exception("Config error"))
        )

        result = self.api._check_auth()

        # Should default to auth disabled (system user)
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["user"]["username"], "system")

    def test_check_auth_exception(self):
        """Test check auth with unexpected exception."""
        mock_auth = Mock()
        self.api.app.auth_middleware = mock_auth
        self.api.config._settings = {"authentication": {"enabled": True}}

        with patch("ethoscope_node.api.auth_api.get_current_user") as mock_get_user:
            mock_get_user.side_effect = Exception("Database error")

            result = self.api._check_auth()

            self.assertFalse(result["authenticated"])
            self.assertIsNone(result["user"])


if __name__ == "__main__":
    unittest.main()
