"""
Unit tests for Authentication Middleware.

Tests HTTP authentication, rate limiting, and session management.
"""

import time
import unittest
from unittest.mock import Mock, patch

import bottle

from ethoscope_node.auth.middleware import (
    AuthMiddleware,
    get_current_user,
    require_admin,
    require_auth,
)


class TestAuthMiddleware(unittest.TestCase):
    """Test suite for AuthMiddleware class."""

    def setUp(self):
        """Create mock database and configuration for testing."""
        self.mock_db = Mock()
        self.mock_config = Mock()

        # Mock session manager initialization
        with patch("ethoscope_node.auth.middleware.SessionManager"):
            self.middleware = AuthMiddleware(self.mock_db, self.mock_config)

    def test_initialization(self):
        """Test AuthMiddleware initialization."""
        self.assertEqual(self.middleware.database, self.mock_db)
        self.assertEqual(self.middleware.config, self.mock_config)
        self.assertEqual(self.middleware.max_attempts, 5)
        self.assertEqual(self.middleware.lockout_duration, 15 * 60)
        self.assertTrue(self.middleware.progressive_lockout)

    @patch("bottle.request")
    def test_get_current_user_with_valid_session(self, mock_request):
        """Test getting current user with valid session cookie."""
        mock_request.get_cookie.return_value = "valid_token"

        mock_user = {"username": "testuser", "id": 1}
        self.middleware.session_manager.get_user_from_session.return_value = mock_user

        user = self.middleware.get_current_user()

        self.assertEqual(user, mock_user)
        mock_request.get_cookie.assert_called_once_with("ethoscope_session")

    @patch("bottle.request")
    def test_get_current_user_no_cookie(self, mock_request):
        """Test getting current user when no session cookie exists."""
        mock_request.get_cookie.return_value = None

        user = self.middleware.get_current_user()

        self.assertIsNone(user)

    @patch("bottle.request")
    def test_is_authenticated_true(self, mock_request):
        """Test is_authenticated returns True for valid session."""
        mock_request.get_cookie.return_value = "valid_token"
        self.middleware.session_manager.get_user_from_session.return_value = {
            "username": "testuser"
        }

        self.assertTrue(self.middleware.is_authenticated())

    @patch("bottle.request")
    def test_is_authenticated_false(self, mock_request):
        """Test is_authenticated returns False with no session."""
        mock_request.get_cookie.return_value = None

        self.assertFalse(self.middleware.is_authenticated())

    @patch("bottle.request")
    def test_is_admin_true(self, mock_request):
        """Test is_admin returns True for admin user."""
        mock_request.get_cookie.return_value = "token"
        self.middleware.session_manager.get_user_from_session.return_value = {
            "username": "admin",
            "isadmin": 1,
        }

        self.assertTrue(self.middleware.is_admin())

    @patch("bottle.request")
    def test_is_admin_false_non_admin(self, mock_request):
        """Test is_admin returns False for non-admin user."""
        mock_request.get_cookie.return_value = "token"
        self.middleware.session_manager.get_user_from_session.return_value = {
            "username": "user",
            "isadmin": 0,
        }

        self.assertFalse(self.middleware.is_admin())

    @patch("bottle.request")
    def test_is_admin_false_not_authenticated(self, mock_request):
        """Test is_admin returns False when not authenticated."""
        mock_request.get_cookie.return_value = None

        self.assertFalse(self.middleware.is_admin())

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_check_rate_limit_allowed(self, mock_time):
        """Test rate limit check allows attempts within limit."""
        mock_time.return_value = 1000.0

        allowed = self.middleware.check_rate_limit("testuser", "192.168.1.1")

        self.assertTrue(allowed)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_check_rate_limit_exceeded_user(self, mock_time):
        """Test rate limit exceeded for username."""
        mock_time.return_value = 1000.0

        # Set up 5 failed attempts just now
        self.middleware._login_attempts["testuser"] = {
            "count": 5,
            "last_attempt": 999.0,
        }

        allowed = self.middleware.check_rate_limit("testuser", "192.168.1.1")

        self.assertFalse(allowed)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_check_rate_limit_exceeded_ip(self, mock_time):
        """Test rate limit exceeded for IP address."""
        mock_time.return_value = 1000.0

        # Set up 15+ failed attempts (3x limit) just now
        self.middleware._ip_attempts["192.168.1.1"] = {
            "count": 16,
            "last_attempt": 999.0,
        }

        allowed = self.middleware.check_rate_limit("testuser", "192.168.1.1")

        self.assertFalse(allowed)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_check_rate_limit_lockout_expired(self, mock_time):
        """Test rate limit allows attempt after lockout expires."""
        mock_time.return_value = 1000.0

        # Set up failed attempts from 20 minutes ago (past 15min lockout)
        self.middleware._login_attempts["testuser"] = {
            "count": 5,
            "last_attempt": 1000.0 - (20 * 60),
        }

        allowed = self.middleware.check_rate_limit("testuser", "192.168.1.1")

        self.assertTrue(allowed)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_record_failed_attempt(self, mock_time):
        """Test recording failed login attempt."""
        mock_time.return_value = 1000.0

        self.middleware.record_failed_attempt("testuser", "192.168.1.1")

        # Should record both username and IP
        self.assertIn("testuser", self.middleware._login_attempts)
        self.assertIn("192.168.1.1", self.middleware._ip_attempts)
        self.assertEqual(self.middleware._login_attempts["testuser"]["count"], 1)
        self.assertEqual(self.middleware._ip_attempts["192.168.1.1"]["count"], 1)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_record_failed_attempt_increments(self, mock_time):
        """Test recording multiple failed attempts increments count."""
        mock_time.return_value = 1000.0

        self.middleware.record_failed_attempt("testuser", "192.168.1.1")
        self.middleware.record_failed_attempt("testuser", "192.168.1.1")
        self.middleware.record_failed_attempt("testuser", "192.168.1.1")

        self.assertEqual(self.middleware._login_attempts["testuser"]["count"], 3)

    def test_clear_failed_attempts(self):
        """Test clearing failed attempts for user."""
        self.middleware._login_attempts["testuser"] = {"count": 3, "last_attempt": 100}

        self.middleware.clear_failed_attempts("testuser")

        self.assertNotIn("testuser", self.middleware._login_attempts)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_authenticate_user_success(self, mock_time):
        """Test successful user authentication."""
        mock_time.return_value = 1000.0

        mock_user = {"username": "testuser", "id": 1, "active": 1}
        self.mock_db.getUserByName.return_value = mock_user
        self.mock_db.verify_pin.return_value = True

        user = self.middleware.authenticate_user("testuser", "1234", "192.168.1.1")

        self.assertEqual(user, mock_user)
        self.mock_db.verify_pin.assert_called_once_with("testuser", "1234")
        # Should clear failed attempts on success
        self.assertNotIn("testuser", self.middleware._login_attempts)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_authenticate_user_rate_limited(self, mock_time):
        """Test authentication blocked by rate limit."""
        mock_time.return_value = 1000.0

        # Setup rate limit exceeded
        self.middleware._login_attempts["testuser"] = {
            "count": 5,
            "last_attempt": 999.0,
        }

        user = self.middleware.authenticate_user("testuser", "1234", "192.168.1.1")

        self.assertIsNone(user)
        # Should not query database
        self.mock_db.getUserByName.assert_not_called()

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_authenticate_user_not_found(self, mock_time):
        """Test authentication with non-existent user."""
        mock_time.return_value = 1000.0

        self.mock_db.getUserByName.return_value = None

        user = self.middleware.authenticate_user("baduser", "1234", "192.168.1.1")

        self.assertIsNone(user)
        self.assertIn("baduser", self.middleware._login_attempts)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_authenticate_user_inactive(self, mock_time):
        """Test authentication blocked for inactive user."""
        mock_time.return_value = 1000.0

        mock_user = {"username": "testuser", "id": 1, "active": 0}
        self.mock_db.getUserByName.return_value = mock_user

        user = self.middleware.authenticate_user("testuser", "1234", "192.168.1.1")

        self.assertIsNone(user)
        self.assertIn("testuser", self.middleware._login_attempts)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_authenticate_user_wrong_pin(self, mock_time):
        """Test authentication with incorrect PIN."""
        mock_time.return_value = 1000.0

        mock_user = {"username": "testuser", "id": 1, "active": 1}
        self.mock_db.getUserByName.return_value = mock_user
        self.mock_db.verify_pin.return_value = False

        user = self.middleware.authenticate_user("testuser", "wrong", "192.168.1.1")

        self.assertIsNone(user)
        self.assertIn("testuser", self.middleware._login_attempts)

    @patch("bottle.request")
    @patch("bottle.response")
    def test_login_user_success(self, mock_response, mock_request):
        """Test successful user login."""
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.1"}

        mock_user = {"username": "testuser", "id": 1, "active": 1}
        self.mock_db.getUserByName.return_value = mock_user
        self.mock_db.verify_pin.return_value = True
        self.middleware.session_manager.create_session.return_value = "session_token"

        token = self.middleware.login_user("testuser", "1234")

        self.assertEqual(token, "session_token")
        mock_response.set_cookie.assert_called_once()

    @patch("bottle.request")
    def test_login_user_auth_failed(self, mock_request):
        """Test login failure when authentication fails."""
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.1"}

        self.mock_db.getUserByName.return_value = None

        token = self.middleware.login_user("baduser", "1234")

        self.assertIsNone(token)

    @patch("bottle.request")
    def test_login_user_session_creation_failed(self, mock_request):
        """Test login failure when session creation fails."""
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.1"}

        mock_user = {"username": "testuser", "id": 1, "active": 1}
        self.mock_db.getUserByName.return_value = mock_user
        self.mock_db.verify_pin.return_value = True
        self.middleware.session_manager.create_session.return_value = None

        token = self.middleware.login_user("testuser", "1234")

        self.assertIsNone(token)

    @patch("bottle.request")
    @patch("bottle.response")
    def test_logout_user_success(self, mock_response, mock_request):
        """Test successful user logout."""
        mock_request.get_cookie.return_value = "session_token"
        self.middleware.session_manager.destroy_session.return_value = True

        result = self.middleware.logout_user()

        self.assertTrue(result)
        self.middleware.session_manager.destroy_session.assert_called_once_with(
            "session_token"
        )
        mock_response.delete_cookie.assert_called_once_with("ethoscope_session")

    @patch("bottle.request")
    def test_logout_user_no_session(self, mock_request):
        """Test logout when no session cookie exists."""
        mock_request.get_cookie.return_value = None

        result = self.middleware.logout_user()

        self.assertFalse(result)

    @patch("bottle.request")
    def test_get_client_ip_remote_addr(self, mock_request):
        """Test getting client IP from REMOTE_ADDR."""
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.100"}

        ip = self.middleware._get_client_ip()

        self.assertEqual(ip, "192.168.1.100")

    @patch("bottle.request")
    def test_get_client_ip_forwarded(self, mock_request):
        """Test getting client IP from X-Forwarded-For header."""
        mock_request.environ = {
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 192.168.1.1",
            "REMOTE_ADDR": "192.168.1.1",
        }

        ip = self.middleware._get_client_ip()

        self.assertEqual(ip, "10.0.0.1")

    @patch("bottle.response")
    def test_set_session_cookie(self, mock_response):
        """Test setting secure session cookie."""
        self.middleware._set_session_cookie("test_token")

        mock_response.set_cookie.assert_called_once_with(
            "ethoscope_session",
            "test_token",
            max_age=2 * 60 * 60,
            httponly=True,
            secure=False,
            samesite="Lax",
            path="/",
        )

    def test_get_lockout_duration_progressive(self):
        """Test progressive lockout durations."""
        # 5 attempts = 5 min lockout
        duration = self.middleware._get_lockout_duration(5)
        self.assertEqual(duration, 5 * 60)

        # 6 attempts = 15 min lockout
        duration = self.middleware._get_lockout_duration(6)
        self.assertEqual(duration, 15 * 60)

        # 7 attempts = 1 hour lockout
        duration = self.middleware._get_lockout_duration(7)
        self.assertEqual(duration, 60 * 60)

    def test_get_lockout_duration_non_progressive(self):
        """Test fixed lockout duration when progressive disabled."""
        self.middleware.progressive_lockout = False

        duration = self.middleware._get_lockout_duration(10)

        self.assertEqual(duration, self.middleware.lockout_duration)

    @patch("ethoscope_node.auth.middleware.time.time")
    def test_clean_old_attempts(self, mock_time):
        """Test cleaning expired failed attempts."""
        mock_time.return_value = 2000.0

        # Add old attempt (2 hours ago, past any lockout duration)
        # count=6 triggers 15min lockout, so 2 hours is definitely past it
        self.middleware._login_attempts["olduser"] = {
            "count": 6,
            "last_attempt": 2000.0 - (2 * 60 * 60),
        }
        # Add recent attempt
        self.middleware._login_attempts["newuser"] = {
            "count": 2,
            "last_attempt": 1990.0,
        }

        self.middleware._clean_old_attempts(2000.0)

        # Old attempt should be removed
        self.assertNotIn("olduser", self.middleware._login_attempts)
        # Recent attempt should remain
        self.assertIn("newuser", self.middleware._login_attempts)


class TestAuthDecorators(unittest.TestCase):
    """Test suite for authentication decorators."""

    def setUp(self):
        """Set up mock app and auth middleware."""
        self.mock_app = Mock()
        self.mock_middleware = Mock()
        self.mock_config = Mock()
        self.mock_middleware.config = self.mock_config

        # Set up mock to be accessed via bottle.app()
        self.mock_app.auth_middleware = self.mock_middleware

    @patch("bottle.app")
    @patch("bottle.abort")
    def test_require_auth_authenticated(self, mock_abort, mock_app):
        """Test require_auth allows authenticated user."""
        mock_app.return_value = self.mock_app
        self.mock_middleware.is_authenticated.return_value = True
        self.mock_config._settings = {"authentication": {"enabled": True}}

        @require_auth
        def protected_route():
            return "success"

        result = protected_route()

        self.assertEqual(result, "success")
        mock_abort.assert_not_called()

    @patch("bottle.app")
    @patch("bottle.abort")
    def test_require_auth_not_authenticated(self, mock_abort, mock_app):
        """Test require_auth blocks unauthenticated user."""
        mock_app.return_value = self.mock_app
        self.mock_middleware.is_authenticated.return_value = False
        self.mock_config._settings = {"authentication": {"enabled": True}}

        @require_auth
        def protected_route():
            return "success"

        protected_route()

        mock_abort.assert_called_once_with(401, "Authentication required")

    @patch("bottle.app")
    def test_require_auth_disabled(self, mock_app):
        """Test require_auth allows access when auth disabled."""
        mock_app.return_value = self.mock_app
        self.mock_config._settings = {"authentication": {"enabled": False}}

        @require_auth
        def protected_route():
            return "success"

        result = protected_route()

        self.assertEqual(result, "success")
        # Should not check authentication
        self.mock_middleware.is_authenticated.assert_not_called()

    @patch("bottle.app")
    @patch("bottle.abort")
    def test_require_admin_authenticated_admin(self, mock_abort, mock_app):
        """Test require_admin allows admin user."""
        mock_app.return_value = self.mock_app
        self.mock_middleware.is_authenticated.return_value = True
        self.mock_middleware.is_admin.return_value = True
        self.mock_config._settings = {"authentication": {"enabled": True}}

        @require_admin
        def admin_route():
            return "admin success"

        result = admin_route()

        self.assertEqual(result, "admin success")
        mock_abort.assert_not_called()

    @patch("bottle.app")
    @patch("bottle.abort")
    def test_require_admin_not_admin(self, mock_abort, mock_app):
        """Test require_admin blocks non-admin user."""
        mock_app.return_value = self.mock_app
        self.mock_middleware.is_authenticated.return_value = True
        self.mock_middleware.is_admin.return_value = False
        self.mock_config._settings = {"authentication": {"enabled": True}}

        @require_admin
        def admin_route():
            return "admin success"

        admin_route()

        mock_abort.assert_called_once_with(403, "Admin privileges required")

    @patch("bottle.app")
    def test_get_current_user_helper(self, mock_app):
        """Test get_current_user helper function."""
        mock_app.return_value = self.mock_app
        mock_user = {"username": "testuser"}
        self.mock_middleware.get_current_user.return_value = mock_user

        user = get_current_user()

        self.assertEqual(user, mock_user)

    @patch("bottle.app")
    def test_get_current_user_no_middleware(self, mock_app):
        """Test get_current_user when middleware not available."""
        mock_app_without_auth = Mock()
        mock_app_without_auth.auth_middleware = None
        mock_app.return_value = mock_app_without_auth

        user = get_current_user()

        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()
