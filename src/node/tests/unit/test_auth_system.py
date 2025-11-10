"""
Unit tests for authentication system.

Tests the core authentication functionality including PIN hashing,
user verification, session management, and rate limiting.
"""

import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest
from ethoscope_node.auth.middleware import AuthMiddleware
from ethoscope_node.auth.session import SessionManager
from ethoscope_node.utils.etho_db import ExperimentalDB


class TestPINAuthentication:
    """Test PIN hashing and verification functionality."""

    def setup_method(self):
        """Setup test database."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.db = ExperimentalDB()
        # Mock the database path
        self.db._db_path = self.temp_db.name

    def teardown_method(self):
        """Clean up test database."""
        if hasattr(self, "temp_db"):
            try:
                os.unlink(self.temp_db.name)
            except (OSError, FileNotFoundError):
                pass

    def test_hash_pin_with_bcrypt(self):
        """Test PIN hashing with bcrypt."""
        with patch("bcrypt.gensalt") as mock_gensalt, patch(
            "bcrypt.hashpw"
        ) as mock_hashpw:

            mock_gensalt.return_value = b"$2b$12$mock_salt"
            mock_hashpw.return_value = b"$2b$12$mock_salt_hashed_pin"

            result = self.db.hash_pin("1234")

            mock_gensalt.assert_called_once()
            mock_hashpw.assert_called_once_with(b"1234", b"$2b$12$mock_salt")
            assert result == "$2b$12$mock_salt_hashed_pin"

    def test_hash_pin_fallback_to_pbkdf2(self):
        """Test PIN hashing fallback to PBKDF2 when bcrypt unavailable."""
        with patch("bcrypt.gensalt", side_effect=ImportError):
            with patch("hashlib.pbkdf2_hmac") as mock_pbkdf2:
                with patch("os.urandom", return_value=b"mocksalt"):
                    mock_pbkdf2.return_value = b"hashed_result"

                    result = self.db.hash_pin("1234")

                    mock_pbkdf2.assert_called_once()
                    assert result.startswith("pbkdf2:")

    def test_verify_pin_with_bcrypt(self):
        """Test PIN verification with bcrypt hash."""
        with patch("bcrypt.checkpw") as mock_checkpw:
            mock_checkpw.return_value = True

            result = self.db.verify_pin("1234", "$2b$12$hash")

            mock_checkpw.assert_called_once_with(b"1234", b"$2b$12$hash")
            assert result is True

    def test_verify_pin_with_pbkdf2(self):
        """Test PIN verification with PBKDF2 hash."""
        with patch("hashlib.pbkdf2_hmac") as mock_pbkdf2:
            mock_pbkdf2.return_value = b"expected_hash"

            pbkdf2_hash = "pbkdf2:salt:expected_hash"
            result = self.db.verify_pin("1234", pbkdf2_hash)

            assert result is True

    def test_verify_pin_incorrect_pin(self):
        """Test PIN verification with incorrect PIN."""
        with patch("bcrypt.checkpw") as mock_checkpw:
            mock_checkpw.return_value = False

            result = self.db.verify_pin("wrong", "$2b$12$hash")

            assert result is False

    def test_authenticate_user_success(self):
        """Test successful user authentication."""
        with patch.object(
            self.db, "get_user_by_username"
        ) as mock_get_user, patch.object(self.db, "verify_pin") as mock_verify:

            mock_get_user.return_value = {
                "id": 1,
                "username": "testuser",
                "fullname": "Test User",
                "email": "test@example.com",
                "labname": "Test Lab",
                "is_admin": 0,
                "pin": "hashed_pin",
            }
            mock_verify.return_value = True

            result = self.db.authenticate_user("testuser", "1234")

            assert result is not None
            assert result["username"] == "testuser"
            assert result["is_admin"] is False

    def test_authenticate_user_invalid_username(self):
        """Test authentication with invalid username."""
        with patch.object(self.db, "get_user_by_username") as mock_get_user:
            mock_get_user.return_value = None

            result = self.db.authenticate_user("invalid_user", "1234")

            assert result is None

    def test_authenticate_user_wrong_pin(self):
        """Test authentication with wrong PIN."""
        with patch.object(
            self.db, "get_user_by_username"
        ) as mock_get_user, patch.object(self.db, "verify_pin") as mock_verify:

            mock_get_user.return_value = {
                "id": 1,
                "username": "testuser",
                "pin": "hashed_pin",
            }
            mock_verify.return_value = False

            result = self.db.authenticate_user("testuser", "wrong_pin")

            assert result is None

    def test_migrate_plaintext_pins(self):
        """Test migration of plaintext PINs to hashed format."""
        with patch.object(self.db, "get_all_users") as mock_get_users, patch.object(
            self.db, "hash_pin"
        ) as mock_hash, patch.object(self.db, "update_user_pin") as mock_update:

            mock_get_users.return_value = [
                {"id": 1, "username": "user1", "pin": "1234"},
                {"id": 2, "username": "user2", "pin": "$2b$12$already_hashed"},
            ]
            mock_hash.return_value = "hashed_1234"

            result = self.db.migrate_plaintext_pins()

            # Should only migrate the plaintext PIN
            mock_hash.assert_called_once_with("1234")
            mock_update.assert_called_once_with(1, "hashed_1234")
            assert result == 1  # One PIN migrated


class TestSessionManager:
    """Test session management functionality."""

    def setup_method(self):
        """Setup test session manager."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
        self.session_manager = SessionManager(self.temp_db.name)

    def teardown_method(self):
        """Clean up test database."""
        if hasattr(self, "temp_db"):
            try:
                os.unlink(self.temp_db.name)
            except (OSError, FileNotFoundError):
                pass

    def test_create_session(self):
        """Test session creation."""
        user_data = {"id": 1, "username": "testuser"}
        client_ip = "192.168.1.100"

        session_id = self.session_manager.create_session(user_data, client_ip)

        assert session_id is not None
        assert len(session_id) == 64  # 32 bytes hex encoded

    def test_get_valid_session(self):
        """Test retrieving a valid session."""
        user_data = {"id": 1, "username": "testuser"}
        client_ip = "192.168.1.100"

        session_id = self.session_manager.create_session(user_data, client_ip)
        session = self.session_manager.get_session(session_id)

        assert session is not None
        assert session["user_id"] == 1
        assert session["client_ip"] == client_ip

    def test_get_invalid_session(self):
        """Test retrieving an invalid session."""
        session = self.session_manager.get_session("invalid_session_id")

        assert session is None

    def test_session_expiry(self):
        """Test that expired sessions are not returned."""
        user_data = {"id": 1, "username": "testuser"}
        client_ip = "192.168.1.100"

        # Create session with very short expiry
        old_timeout = self.session_manager.session_timeout
        self.session_manager.session_timeout = 0.1  # 0.1 seconds

        session_id = self.session_manager.create_session(user_data, client_ip)

        # Wait for expiry
        time.sleep(0.2)

        session = self.session_manager.get_session(session_id)

        # Restore original timeout
        self.session_manager.session_timeout = old_timeout

        assert session is None

    def test_destroy_session(self):
        """Test session destruction."""
        user_data = {"id": 1, "username": "testuser"}
        client_ip = "192.168.1.100"

        session_id = self.session_manager.create_session(user_data, client_ip)

        # Verify session exists
        assert self.session_manager.get_session(session_id) is not None

        # Destroy session
        result = self.session_manager.destroy_session(session_id)
        assert result is True

        # Verify session no longer exists
        assert self.session_manager.get_session(session_id) is None

    def test_cleanup_expired_sessions(self):
        """Test cleanup of expired sessions."""
        user_data = {"id": 1, "username": "testuser"}
        client_ip = "192.168.1.100"

        # Create sessions with short expiry
        old_timeout = self.session_manager.session_timeout
        self.session_manager.session_timeout = 0.1

        session_id1 = self.session_manager.create_session(user_data, client_ip)
        session_id2 = self.session_manager.create_session(user_data, client_ip)

        # Wait for expiry
        time.sleep(0.2)

        # Cleanup expired sessions
        cleaned = self.session_manager.cleanup_expired_sessions()

        # Restore original timeout
        self.session_manager.session_timeout = old_timeout

        assert cleaned >= 2  # Should have cleaned at least our 2 sessions


class TestAuthMiddleware:
    """Test authentication middleware functionality."""

    def setup_method(self):
        """Setup test authentication middleware."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()

        self.mock_db = Mock(spec=ExperimentalDB)
        self.mock_config = {"session_timeout": 3600}
        self.auth_middleware = AuthMiddleware(self.mock_db, self.mock_config)

    def teardown_method(self):
        """Clean up test files."""
        if hasattr(self, "temp_db"):
            try:
                os.unlink(self.temp_db.name)
            except (OSError, FileNotFoundError):
                pass

    def test_rate_limiting_allows_valid_attempts(self):
        """Test that rate limiting allows valid login attempts."""
        username = "testuser"
        client_ip = "192.168.1.100"

        # First few attempts should be allowed
        for i in range(3):
            result = self.auth_middleware.check_rate_limit(username, client_ip)
            assert result is True

    def test_rate_limiting_blocks_excessive_attempts(self):
        """Test that rate limiting blocks excessive login attempts."""
        username = "testuser"
        client_ip = "192.168.1.100"

        # Make maximum allowed attempts
        for i in range(5):
            self.auth_middleware.record_failed_attempt(username, client_ip)

        # Next attempt should be blocked
        result = self.auth_middleware.check_rate_limit(username, client_ip)
        assert result is False

    def test_progressive_lockout(self):
        """Test progressive lockout periods."""
        username = "testuser"
        client_ip = "192.168.1.100"

        # Record multiple failed attempts to trigger lockout
        for i in range(5):
            self.auth_middleware.record_failed_attempt(username, client_ip)

        # Should be locked out
        assert self.auth_middleware.check_rate_limit(username, client_ip) is False

        # Check lockout period increases with more attempts
        for i in range(3):
            self.auth_middleware.record_failed_attempt(username, client_ip)

        # Lockout period should have increased
        lockout_info = self.auth_middleware.failed_attempts.get(
            f"{username}:{client_ip}"
        )
        assert lockout_info["lockout_until"] > time.time()

    def test_successful_login_resets_attempts(self):
        """Test that successful login resets failed attempts."""
        username = "testuser"
        client_ip = "192.168.1.100"

        # Record some failed attempts
        for i in range(3):
            self.auth_middleware.record_failed_attempt(username, client_ip)

        # Clear attempts on successful login
        self.auth_middleware.clear_failed_attempts(username, client_ip)

        # Should be able to make new attempts
        result = self.auth_middleware.check_rate_limit(username, client_ip)
        assert result is True

    def test_authenticate_user_success(self):
        """Test successful user authentication through middleware."""
        username = "testuser"
        pin = "1234"
        client_ip = "192.168.1.100"

        mock_user = {
            "id": 1,
            "username": username,
            "fullname": "Test User",
            "email": "test@example.com",
            "is_admin": False,
        }

        self.mock_db.authenticate_user.return_value = mock_user

        result = self.auth_middleware.authenticate_user(username, pin, client_ip)

        assert result is not None
        assert result["username"] == username
        assert "session_id" in result

    def test_authenticate_user_rate_limited(self):
        """Test authentication blocked by rate limiting."""
        username = "testuser"
        pin = "1234"
        client_ip = "192.168.1.100"

        # Trigger rate limiting
        for i in range(5):
            self.auth_middleware.record_failed_attempt(username, client_ip)

        result = self.auth_middleware.authenticate_user(username, pin, client_ip)

        assert result is None
        # Database should not be called when rate limited
        self.mock_db.authenticate_user.assert_not_called()

    def test_authenticate_user_invalid_credentials(self):
        """Test authentication with invalid credentials."""
        username = "testuser"
        pin = "wrong_pin"
        client_ip = "192.168.1.100"

        self.mock_db.authenticate_user.return_value = None

        result = self.auth_middleware.authenticate_user(username, pin, client_ip)

        assert result is None
        # Failed attempt should be recorded
        lockout_key = f"{username}:{client_ip}"
        assert lockout_key in self.auth_middleware.failed_attempts

    def test_require_auth_decorator_with_valid_session(self):
        """Test authentication decorator with valid session."""
        mock_request = Mock()
        mock_request.get_cookie.return_value = "valid_session_id"
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.100"}

        mock_session = {
            "user_id": 1,
            "username": "testuser",
            "client_ip": "192.168.1.100",
        }

        with patch.object(
            self.auth_middleware.session_manager,
            "get_session",
            return_value=mock_session,
        ):

            @self.auth_middleware.require_auth
            def test_endpoint():
                return "success"

            # Mock bottle request
            with patch("bottle.request", mock_request):
                result = test_endpoint()
                assert result == "success"

    def test_require_auth_decorator_without_session(self):
        """Test authentication decorator without valid session."""
        mock_request = Mock()
        mock_request.get_cookie.return_value = None

        @self.auth_middleware.require_auth
        def test_endpoint():
            return "success"

        # Mock bottle request and response
        with patch("bottle.request", mock_request), patch("bottle.abort") as mock_abort:

            test_endpoint()
            mock_abort.assert_called_with(401, "Authentication required")

    def test_require_admin_decorator_with_admin_user(self):
        """Test admin decorator with admin user."""
        mock_request = Mock()
        mock_request.get_cookie.return_value = "valid_session_id"
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.100"}

        mock_session = {"user_id": 1, "username": "admin", "client_ip": "192.168.1.100"}

        mock_user = {"is_admin": True}

        with patch.object(
            self.auth_middleware.session_manager,
            "get_session",
            return_value=mock_session,
        ), patch.object(self.mock_db, "get_user_by_id", return_value=mock_user):

            @self.auth_middleware.require_admin
            def admin_endpoint():
                return "admin_success"

            with patch("bottle.request", mock_request):
                result = admin_endpoint()
                assert result == "admin_success"

    def test_require_admin_decorator_with_regular_user(self):
        """Test admin decorator with regular user."""
        mock_request = Mock()
        mock_request.get_cookie.return_value = "valid_session_id"
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.100"}

        mock_session = {"user_id": 1, "username": "user", "client_ip": "192.168.1.100"}

        mock_user = {"is_admin": False}

        with patch.object(
            self.auth_middleware.session_manager,
            "get_session",
            return_value=mock_session,
        ), patch.object(self.mock_db, "get_user_by_id", return_value=mock_user):

            @self.auth_middleware.require_admin
            def admin_endpoint():
                return "admin_success"

            with patch("bottle.request", mock_request), patch(
                "bottle.abort"
            ) as mock_abort:

                admin_endpoint()
                mock_abort.assert_called_with(403, "Admin access required")


if __name__ == "__main__":
    pytest.main([__file__])
