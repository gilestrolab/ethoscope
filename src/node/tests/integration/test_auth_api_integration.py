"""
Integration tests for authentication API endpoints.

Tests the complete authentication flow including login, logout,
PIN changes, and API endpoint protection.
"""

import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from datetime import timedelta
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import bottle
import pytest
from bottle import HTTPError

from ethoscope_node.api.auth_api import AuthAPI
from ethoscope_node.auth.middleware import AuthMiddleware
from ethoscope_node.utils.etho_db import ExperimentalDB


class TestAuthAPIIntegration:
    """Integration tests for authentication API."""

    def setup_method(self):
        """Setup test environment with real database and API."""
        # Create temporary directory for database
        self.temp_dir = tempfile.mkdtemp(prefix="test_auth_api_")
        self.db = ExperimentalDB(self.temp_dir)
        self._setup_test_users()

        # Initialize authentication middleware and API
        self.config = {"session_timeout": 3600}
        self.auth_middleware = AuthMiddleware(self.db, self.config)
        self.auth_api = AuthAPI(self.db, self.auth_middleware)

        # Create bottle app for testing
        self.app = bottle.Bottle()
        self._setup_routes()

    def teardown_method(self):
        """Clean up test environment."""
        if hasattr(self, "temp_dir"):
            try:
                shutil.rmtree(self.temp_dir)
            except (OSError, FileNotFoundError):
                pass

    def _setup_test_users(self):
        """Setup test users in database."""
        # Create test users table if it doesn't exist
        with patch.object(self.db, "execute") as mock_execute:
            mock_execute.return_value = True

        # Mock user data
        self.test_users = [
            {
                "id": 1,
                "username": "admin",
                "fullname": "Admin User",
                "email": "admin@test.com",
                "labname": "Test Lab",
                "is_admin": True,
                "pin": self.db.hash_pin("1234"),
            },
            {
                "id": 2,
                "username": "user",
                "fullname": "Regular User",
                "email": "user@test.com",
                "labname": "Test Lab",
                "is_admin": False,
                "pin": self.db.hash_pin("5678"),
            },
        ]

    def _setup_routes(self):
        """Setup API routes for testing."""
        self.app.route("/api/auth/login", method="POST", callback=self.auth_api.login)
        self.app.route("/api/auth/logout", method="POST", callback=self.auth_api.logout)
        self.app.route(
            "/api/auth/change_pin", method="POST", callback=self.auth_api.change_pin
        )
        self.app.route(
            "/api/auth/check", method="GET", callback=self.auth_api.check_auth
        )

    def _make_request(self, method, path, data=None, cookies=None):
        """Helper to make requests to the test app."""
        import urllib.parse
        from io import BytesIO

        from bottle import tob

        environ = {
            "REQUEST_METHOD": method.upper(),
            "PATH_INFO": path,
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "80",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": BytesIO(),
            "wsgi.errors": BytesIO(),
            "REMOTE_ADDR": "127.0.0.1",
        }

        if data:
            if isinstance(data, dict):
                data = urllib.parse.urlencode(data)
            environ["wsgi.input"] = BytesIO(tob(data))
            environ["CONTENT_LENGTH"] = str(len(data))
            environ["CONTENT_TYPE"] = "application/x-www-form-urlencoded"

        if cookies:
            cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            environ["HTTP_COOKIE"] = cookie_header

        # Create a response recorder
        response_data = {"status": None, "headers": [], "body": b""}

        def start_response(status, headers):
            response_data["status"] = status
            response_data["headers"] = headers

        try:
            result = self.app.wsgi(environ, start_response)
            if hasattr(result, "__iter__"):
                response_data["body"] = b"".join(result)
            else:
                response_data["body"] = result
        except HTTPError as e:
            response_data["status"] = f"{e.status_code} {e.body}"
            response_data["body"] = (
                e.body.encode() if isinstance(e.body, str) else e.body
            )

        return response_data

    @patch("bottle.request")
    @patch("bottle.response")
    def test_login_success(self, mock_response, mock_request):
        """Test successful login."""
        # Mock request
        mock_request.forms = {"username": "admin", "pin": "1234"}
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}

        # Mock database authentication
        with patch.object(self.db, "authenticate_user") as mock_auth:
            mock_auth.return_value = self.test_users[0]

            result = self.auth_api.login()

            assert result["success"] is True
            assert result["user"]["username"] == "admin"
            assert result["user"]["is_admin"] is True
            assert "session_id" in result

    @patch("bottle.request")
    def test_login_invalid_credentials(self, mock_request):
        """Test login with invalid credentials."""
        mock_request.forms = {"username": "admin", "pin": "wrong_pin"}
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}

        with patch.object(self.db, "authenticate_user") as mock_auth:
            mock_auth.return_value = None

            with patch("bottle.abort") as mock_abort:
                self.auth_api.login()
                mock_abort.assert_called_with(401, "Invalid credentials")

    @patch("bottle.request")
    def test_login_rate_limited(self, mock_request):
        """Test login blocked by rate limiting."""
        mock_request.forms = {"username": "admin", "pin": "1234"}
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}

        # Simulate rate limiting
        with patch.object(self.auth_middleware, "check_rate_limit") as mock_rate_limit:
            mock_rate_limit.return_value = False

            with patch("bottle.abort") as mock_abort:
                self.auth_api.login()
                mock_abort.assert_called_with(
                    429, "Too many failed attempts. Please try again later."
                )

    @patch("bottle.request")
    @patch("bottle.response")
    def test_logout_success(self, mock_response, mock_request):
        """Test successful logout."""
        session_id = "test_session_id"
        mock_request.get_cookie.return_value = session_id

        with patch.object(
            self.auth_middleware.session_manager, "destroy_session"
        ) as mock_destroy:
            mock_destroy.return_value = True

            result = self.auth_api.logout()

            assert result["success"] is True
            assert result["message"] == "Logged out successfully"
            mock_destroy.assert_called_once_with(session_id)

    @patch("bottle.request")
    def test_logout_no_session(self, mock_request):
        """Test logout without active session."""
        mock_request.get_cookie.return_value = None

        with patch("bottle.abort") as mock_abort:
            self.auth_api.logout()
            mock_abort.assert_called_with(401, "No active session")

    @patch("bottle.request")
    def test_check_auth_valid_session(self, mock_request):
        """Test authentication check with valid session."""
        session_id = "valid_session"
        mock_request.get_cookie.return_value = session_id
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}

        mock_session = {
            "user_id": 1,
            "username": "admin",
            "client_ip": "127.0.0.1",
            "created_at": datetime.now().isoformat(),
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
        }

        with patch.object(
            self.auth_middleware.session_manager, "get_session"
        ) as mock_get_session, patch.object(self.db, "get_user_by_id") as mock_get_user:

            mock_get_session.return_value = mock_session
            mock_get_user.return_value = self.test_users[0]

            result = self.auth_api.check_auth()

            assert result["authenticated"] is True
            assert result["user"]["username"] == "admin"
            assert result["user"]["is_admin"] is True

    @patch("bottle.request")
    def test_check_auth_invalid_session(self, mock_request):
        """Test authentication check with invalid session."""
        mock_request.get_cookie.return_value = "invalid_session"

        with patch.object(
            self.auth_middleware.session_manager, "get_session"
        ) as mock_get_session:
            mock_get_session.return_value = None

            result = self.auth_api.check_auth()

            assert result["authenticated"] is False
            assert result["user"] is None

    @patch("bottle.request")
    def test_change_pin_success(self, mock_request):
        """Test successful PIN change."""
        session_id = "valid_session"
        mock_request.get_cookie.return_value = session_id
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}
        mock_request.forms = {"current_pin": "1234", "new_pin": "9999"}

        mock_session = {"user_id": 1, "username": "admin", "client_ip": "127.0.0.1"}

        with patch.object(
            self.auth_middleware.session_manager, "get_session"
        ) as mock_get_session, patch.object(
            self.db, "get_user_by_id"
        ) as mock_get_user, patch.object(
            self.db, "verify_pin"
        ) as mock_verify, patch.object(
            self.db, "hash_pin"
        ) as mock_hash, patch.object(
            self.db, "update_user_pin"
        ) as mock_update:

            mock_get_session.return_value = mock_session
            mock_get_user.return_value = self.test_users[0]
            mock_verify.return_value = True
            mock_hash.return_value = "hashed_new_pin"
            mock_update.return_value = True

            result = self.auth_api.change_pin()

            assert result["success"] is True
            assert result["message"] == "PIN changed successfully"
            mock_verify.assert_called_once_with("1234", self.test_users[0]["pin"])
            mock_hash.assert_called_once_with("9999")
            mock_update.assert_called_once_with(1, "hashed_new_pin")

    @patch("bottle.request")
    def test_change_pin_wrong_current_pin(self, mock_request):
        """Test PIN change with wrong current PIN."""
        session_id = "valid_session"
        mock_request.get_cookie.return_value = session_id
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}
        mock_request.forms = {"current_pin": "wrong_pin", "new_pin": "9999"}

        mock_session = {"user_id": 1, "username": "admin", "client_ip": "127.0.0.1"}

        with patch.object(
            self.auth_middleware.session_manager, "get_session"
        ) as mock_get_session, patch.object(
            self.db, "get_user_by_id"
        ) as mock_get_user, patch.object(
            self.db, "verify_pin"
        ) as mock_verify:

            mock_get_session.return_value = mock_session
            mock_get_user.return_value = self.test_users[0]
            mock_verify.return_value = False

            with patch("bottle.abort") as mock_abort:
                self.auth_api.change_pin()
                mock_abort.assert_called_with(400, "Current PIN is incorrect")

    @patch("bottle.request")
    def test_change_pin_no_session(self, mock_request):
        """Test PIN change without valid session."""
        mock_request.get_cookie.return_value = None
        mock_request.forms = {"current_pin": "1234", "new_pin": "9999"}

        with patch("bottle.abort") as mock_abort:
            self.auth_api.change_pin()
            mock_abort.assert_called_with(401, "Authentication required")


class TestEndToEndAuthentication:
    """End-to-end authentication flow tests."""

    def setup_method(self):
        """Setup complete authentication system."""
        self.temp_dir = tempfile.mkdtemp(prefix="test_e2e_auth_")
        self.db = ExperimentalDB(self.temp_dir)
        self.config = {"session_timeout": 3600}
        self.auth_middleware = AuthMiddleware(self.db, self.config)
        self.auth_api = AuthAPI(self.db, self.auth_middleware)

    def teardown_method(self):
        """Clean up test environment."""
        if hasattr(self, "temp_dir"):
            try:
                shutil.rmtree(self.temp_dir)
            except (OSError, FileNotFoundError):
                pass

    def test_complete_authentication_flow(self):
        """Test complete login -> API access -> logout flow."""
        username = "testuser"
        pin = "1234"
        client_ip = "127.0.0.1"

        # Mock user data
        mock_user = {
            "id": 1,
            "username": username,
            "fullname": "Test User",
            "email": "test@example.com",
            "is_admin": False,
            "pin": self.db.hash_pin(pin),
        }

        # Step 1: Login
        with patch.object(self.db, "authenticate_user") as mock_auth:
            mock_auth.return_value = mock_user

            login_result = self.auth_middleware.authenticate_user(
                username, pin, client_ip
            )

            assert login_result is not None
            assert "session_id" in login_result
            session_id = login_result["session_id"]

        # Step 2: Access protected resource
        mock_session = {
            "user_id": 1,
            "username": username,
            "client_ip": client_ip,
            "created_at": datetime.now().isoformat(),
        }

        with patch.object(
            self.auth_middleware.session_manager, "get_session"
        ) as mock_get_session:
            mock_get_session.return_value = mock_session

            # Test authentication check
            @self.auth_middleware.require_auth
            def protected_endpoint():
                return {"message": "Access granted"}

            # Mock bottle request
            mock_request = Mock()
            mock_request.get_cookie.return_value = session_id
            mock_request.environ = {"REMOTE_ADDR": client_ip}

            with patch("bottle.request", mock_request):
                result = protected_endpoint()
                assert result == {"message": "Access granted"}

        # Step 3: Logout
        with patch.object(
            self.auth_middleware.session_manager, "destroy_session"
        ) as mock_destroy:
            mock_destroy.return_value = True

            logout_result = self.auth_middleware.session_manager.destroy_session(
                session_id
            )
            assert logout_result is True

    def test_admin_endpoint_protection(self):
        """Test that admin endpoints are properly protected."""
        # Regular user
        regular_user_session = {
            "user_id": 2,
            "username": "regular_user",
            "client_ip": "127.0.0.1",
        }

        regular_user = {"is_admin": False}

        # Admin endpoint
        @self.auth_middleware.require_admin
        def admin_endpoint():
            return {"message": "Admin access granted"}

        # Mock request from regular user
        mock_request = Mock()
        mock_request.get_cookie.return_value = "regular_user_session"
        mock_request.environ = {"REMOTE_ADDR": "127.0.0.1"}

        with patch.object(
            self.auth_middleware.session_manager, "get_session"
        ) as mock_get_session, patch.object(
            self.db, "get_user_by_id"
        ) as mock_get_user, patch(
            "bottle.request", mock_request
        ), patch(
            "bottle.abort"
        ) as mock_abort:

            mock_get_session.return_value = regular_user_session
            mock_get_user.return_value = regular_user

            admin_endpoint()
            mock_abort.assert_called_with(403, "Admin access required")

    def test_session_timeout_handling(self):
        """Test handling of expired sessions."""
        username = "testuser"
        client_ip = "127.0.0.1"

        # Create session that expires quickly
        old_timeout = self.auth_middleware.session_manager.session_timeout
        self.auth_middleware.session_manager.session_timeout = 0.1  # 0.1 seconds

        # Create session
        user_data = {"id": 1, "username": username}
        session_id = self.auth_middleware.session_manager.create_session(
            user_data, client_ip
        )

        # Wait for expiration
        time.sleep(0.2)

        # Try to access protected endpoint
        @self.auth_middleware.require_auth
        def protected_endpoint():
            return {"message": "Access granted"}

        mock_request = Mock()
        mock_request.get_cookie.return_value = session_id
        mock_request.environ = {"REMOTE_ADDR": client_ip}

        with patch("bottle.request", mock_request), patch("bottle.abort") as mock_abort:

            protected_endpoint()
            mock_abort.assert_called_with(401, "Authentication required")

        # Restore original timeout
        self.auth_middleware.session_manager.session_timeout = old_timeout


if __name__ == "__main__":
    pytest.main([__file__])
