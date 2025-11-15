"""
Unit tests for Session Management.

Tests secure session creation, validation, and cleanup for authentication.
"""

import datetime
import time
import unittest
from unittest.mock import Mock, patch

from ethoscope_node.auth.session import SessionManager


class TestSessionManager(unittest.TestCase):
    """Test suite for SessionManager class."""

    def setUp(self):
        """Create mock database and configuration for testing."""
        self.mock_db = Mock()
        self.mock_config = Mock()

        # Mock successful table creation
        self.mock_db.executeSQL.return_value = 0

        self.manager = SessionManager(self.mock_db, self.mock_config)

    def test_initialization(self):
        """Test SessionManager initialization."""
        self.assertEqual(self.manager.database, self.mock_db)
        self.assertEqual(self.manager.config, self.mock_config)
        self.assertEqual(self.manager.session_timeout, 2 * 60 * 60)  # 2 hours
        self.assertEqual(self.manager.cleanup_interval, 60 * 60)  # 1 hour
        self.assertEqual(self.manager.max_sessions_per_user, 5)

        # Should have called table creation
        self.assertTrue(self.mock_db.executeSQL.called)

    def test_ensure_sessions_table_success(self):
        """Test successful sessions table creation."""
        mock_db = Mock()
        mock_db.executeSQL.return_value = 0  # Success

        SessionManager(mock_db, self.mock_config)

        # Should create table and indexes (3 SQL statements)
        self.assertEqual(mock_db.executeSQL.call_count, 3)

        # Check CREATE TABLE was called
        first_call = mock_db.executeSQL.call_args_list[0]
        self.assertIn("CREATE TABLE IF NOT EXISTS sessions", first_call[0][0])

    def test_ensure_sessions_table_failure(self):
        """Test sessions table creation failure handling."""
        mock_db = Mock()
        mock_db.executeSQL.return_value = -1  # Failure

        with patch.object(SessionManager, "__init__", lambda x, y, z: None):
            manager = SessionManager.__new__(SessionManager)
            manager.database = mock_db
            manager.logger = Mock()

            manager._ensure_sessions_table()

            # Should log error
            manager.logger.error.assert_called()

    @patch("ethoscope_node.auth.session.time.time")
    @patch("bottle.request")
    def test_create_session_success(self, mock_request, mock_time):
        """Test successful session creation."""
        mock_time.return_value = 1000.0
        mock_request.environ = {
            "HTTP_USER_AGENT": "TestBrowser/1.0",
            "REMOTE_ADDR": "192.168.1.100",
        }

        # Mock database responses
        self.mock_db.executeSQL.return_value = 0  # Success

        # Mock _periodic_cleanup to avoid side effects
        self.manager._periodic_cleanup = Mock()
        self.manager._limit_user_sessions = Mock()

        user = {"username": "testuser", "id": 1}
        token = self.manager.create_session(user)

        # Should return a token
        self.assertIsNotNone(token)
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 32)  # URL-safe base64 of 32 bytes

    def test_create_session_missing_username(self):
        """Test session creation with missing username."""
        user = {"id": 1}  # No username

        token = self.manager.create_session(user)

        # Should return None
        self.assertIsNone(token)

    @patch("ethoscope_node.auth.session.time.time")
    @patch("bottle.request")
    def test_create_session_database_failure(self, mock_request, mock_time):
        """Test session creation with database failure."""
        mock_time.return_value = 1000.0
        mock_request.environ = {"HTTP_USER_AGENT": "Test", "REMOTE_ADDR": "127.0.0.1"}

        # Mock database failure
        self.mock_db.executeSQL.return_value = -1

        self.manager._periodic_cleanup = Mock()
        self.manager._limit_user_sessions = Mock()

        user = {"username": "testuser", "id": 1}
        token = self.manager.create_session(user)

        # Should return None on failure
        self.assertIsNone(token)

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_user_from_session_valid(self, mock_time):
        """Test getting user from valid session."""
        mock_time.return_value = 1000.0

        # Mock database response - tuple format as returned by SQLite
        session_data = [
            (
                "testuser",  # s.username (0)
                1,  # s.user_id (1)
                2000.0,  # s.expires_at (2)
                1,  # s.active (3)
                "testuser",  # u.username (4)
                "Test User",  # u.fullname (5)
                "test@example.com",  # u.email (6)
                "123-456-7890",  # u.telephone (7)
                "Test Lab",  # u.labname (8)
                1,  # u.active (9)
                0,  # u.isadmin (10)
            )
        ]
        self.mock_db.executeSQL.return_value = session_data

        user = self.manager.get_user_from_session("valid_token")

        # Should return user dictionary
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "testuser")
        self.assertEqual(user["id"], 1)
        self.assertEqual(user["fullname"], "Test User")
        self.assertEqual(user["email"], "test@example.com")
        self.assertEqual(user["isadmin"], 0)

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_user_from_session_expired(self, mock_time):
        """Test getting user from expired session."""
        mock_time.return_value = 1000.0

        # Mock no results (expired session filtered by WHERE clause)
        self.mock_db.executeSQL.return_value = []

        user = self.manager.get_user_from_session("expired_token")

        # Should return None
        self.assertIsNone(user)

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_user_from_session_inactive_user(self, mock_time):
        """Test getting user from session when user is inactive."""
        mock_time.return_value = 1000.0

        # User is inactive (user_active = 0)
        session_data = [
            (
                "testuser",
                1,
                2000.0,
                1,
                "testuser",
                "Test User",
                "test@example.com",
                "123",
                "Lab",
                0,  # user_active = 0 (inactive)
                0,
            )
        ]
        self.mock_db.executeSQL.return_value = session_data

        self.manager.destroy_session = Mock(return_value=True)

        user = self.manager.get_user_from_session("token")

        # Should destroy session and return None
        self.assertIsNone(user)
        self.manager.destroy_session.assert_called_once_with("token")

    def test_destroy_session_success(self):
        """Test successful session destruction."""
        self.mock_db.executeSQL.return_value = 0  # Success

        result = self.manager.destroy_session("test_token")

        # Should return True
        self.assertTrue(result)

        # Should have called UPDATE to set active = 0
        call_args = self.mock_db.executeSQL.call_args
        self.assertIn("UPDATE sessions", call_args[0][0])
        self.assertIn("active = 0", call_args[0][0])

    def test_destroy_session_failure(self):
        """Test session destruction failure."""
        self.mock_db.executeSQL.return_value = -1  # Failure

        result = self.manager.destroy_session("test_token")

        # Should return False
        self.assertFalse(result)

    def test_destroy_user_sessions_success(self):
        """Test destroying all sessions for a user."""
        self.mock_db.executeSQL.return_value = 0

        result = self.manager.destroy_user_sessions("testuser")

        # Should return True
        self.assertTrue(result)

        # Should update all active sessions for user
        call_args = self.mock_db.executeSQL.call_args
        self.assertIn("username = ?", call_args[0][0])
        self.assertEqual(call_args[0][1], ("testuser",))

    def test_destroy_user_sessions_failure(self):
        """Test destroying user sessions failure."""
        self.mock_db.executeSQL.return_value = -1

        result = self.manager.destroy_user_sessions("testuser")

        self.assertFalse(result)

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_active_sessions_all(self, mock_time):
        """Test getting all active sessions."""
        mock_time.return_value = 1000.0

        # Mock multiple active sessions
        sessions_data = [
            ("token1", "user1", 100.0, 900.0, 2000.0, "192.168.1.1", "Browser1"),
            ("token2", "user2", 200.0, 950.0, 2000.0, "192.168.1.2", "Browser2"),
        ]
        self.mock_db.executeSQL.return_value = sessions_data

        sessions = self.manager.get_active_sessions()

        # Should return list of sessions
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["username"], "user1")
        self.assertEqual(sessions[1]["username"], "user2")
        # Tokens should be truncated for security
        self.assertTrue(sessions[0]["session_token"].endswith("..."))

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_active_sessions_by_user(self, mock_time):
        """Test getting active sessions for specific user."""
        mock_time.return_value = 1000.0

        sessions_data = [
            ("token1", "testuser", 100.0, 900.0, 2000.0, "192.168.1.1", "Browser"),
        ]
        self.mock_db.executeSQL.return_value = sessions_data

        sessions = self.manager.get_active_sessions("testuser")

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["username"], "testuser")

        # Should have filtered by username
        call_args = self.mock_db.executeSQL.call_args
        self.assertIn("username = ?", call_args[0][0])

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_active_sessions_empty(self, mock_time):
        """Test getting active sessions when none exist."""
        mock_time.return_value = 1000.0
        self.mock_db.executeSQL.return_value = []

        sessions = self.manager.get_active_sessions()

        self.assertEqual(sessions, [])

    @patch("ethoscope_node.auth.session.time.time")
    def test_cleanup_expired_sessions(self, mock_time):
        """Test cleanup of expired sessions."""
        mock_time.return_value = 1000.0

        # Reset mock to clear initialization calls
        self.mock_db.executeSQL.reset_mock()

        # Mock count query returns 3 expired sessions
        self.mock_db.executeSQL.side_effect = [
            [(3,)],  # COUNT result
            0,  # DELETE result
        ]

        count = self.manager.cleanup_expired_sessions()

        # Should return count of cleaned sessions
        self.assertEqual(count, 3)

        # Should have called both COUNT and DELETE
        self.assertEqual(self.mock_db.executeSQL.call_count, 2)

    @patch("ethoscope_node.auth.session.time.time")
    def test_cleanup_expired_sessions_none(self, mock_time):
        """Test cleanup when no expired sessions exist."""
        mock_time.return_value = 1000.0

        self.mock_db.executeSQL.side_effect = [
            [(0,)],  # COUNT result - no expired sessions
            0,
        ]

        count = self.manager.cleanup_expired_sessions()

        self.assertEqual(count, 0)

    def test_generate_session_token(self):
        """Test session token generation."""
        token1 = self.manager._generate_session_token()
        token2 = self.manager._generate_session_token()

        # Should be strings
        self.assertIsInstance(token1, str)
        self.assertIsInstance(token2, str)

        # Should be long enough (32 bytes = ~43 base64 chars)
        self.assertGreater(len(token1), 32)

        # Should be unique
        self.assertNotEqual(token1, token2)

    @patch("bottle.request")
    def test_get_client_ip_direct(self, mock_request):
        """Test getting client IP from REMOTE_ADDR."""
        mock_request.environ = {"REMOTE_ADDR": "192.168.1.100"}

        ip = self.manager._get_client_ip()

        self.assertEqual(ip, "192.168.1.100")

    @patch("bottle.request")
    def test_get_client_ip_forwarded(self, mock_request):
        """Test getting client IP from X-Forwarded-For header."""
        mock_request.environ = {
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 192.168.1.100",
            "REMOTE_ADDR": "192.168.1.1",
        }

        ip = self.manager._get_client_ip()

        # Should return first IP from X-Forwarded-For
        self.assertEqual(ip, "10.0.0.1")

    @patch("bottle.request")
    def test_get_client_ip_unknown(self, mock_request):
        """Test getting client IP when not available."""
        mock_request.environ = {}

        ip = self.manager._get_client_ip()

        self.assertEqual(ip, "unknown")

    def test_update_session_access(self):
        """Test updating session last accessed time."""
        self.mock_db.executeSQL.return_value = 0

        self.manager._update_session_access("test_token", 1500.0)

        # Should have called UPDATE
        call_args = self.mock_db.executeSQL.call_args
        self.assertIn("last_accessed", call_args[0][0])
        self.assertEqual(call_args[0][1], (1500.0, "test_token"))

    @patch("ethoscope_node.auth.session.time.time")
    def test_limit_user_sessions_under_limit(self, mock_time):
        """Test session limiting when under limit."""
        mock_time.return_value = 1000.0

        # Mock 3 active sessions (under limit of 5)
        self.mock_db.executeSQL.return_value = [
            ("token1", 900.0),
            ("token2", 950.0),
            ("token3", 980.0),
        ]

        self.manager.destroy_session = Mock()

        self.manager._limit_user_sessions("testuser")

        # Should not destroy any sessions
        self.manager.destroy_session.assert_not_called()

    @patch("ethoscope_node.auth.session.time.time")
    def test_limit_user_sessions_at_limit(self, mock_time):
        """Test session limiting when at limit."""
        mock_time.return_value = 1000.0

        # Mock 5 active sessions (at limit)
        self.mock_db.executeSQL.return_value = [
            ("token1", 700.0),
            ("token2", 800.0),
            ("token3", 850.0),
            ("token4", 900.0),
            ("token5", 950.0),
        ]

        self.manager.destroy_session = Mock()

        self.manager._limit_user_sessions("testuser")

        # Should destroy oldest session to make room (1 session)
        self.assertEqual(self.manager.destroy_session.call_count, 1)
        self.manager.destroy_session.assert_called_with("token1")

    @patch("ethoscope_node.auth.session.time.time")
    def test_limit_user_sessions_over_limit(self, mock_time):
        """Test session limiting when over limit."""
        mock_time.return_value = 1000.0

        # Mock 7 active sessions (over limit of 5)
        self.mock_db.executeSQL.return_value = [
            ("token1", 600.0),
            ("token2", 700.0),
            ("token3", 800.0),
            ("token4", 850.0),
            ("token5", 900.0),
            ("token6", 950.0),
            ("token7", 980.0),
        ]

        self.manager.destroy_session = Mock()

        self.manager._limit_user_sessions("testuser")

        # Should destroy 3 oldest sessions (7 - 5 + 1 = 3)
        self.assertEqual(self.manager.destroy_session.call_count, 3)

    @patch("ethoscope_node.auth.session.time.time")
    def test_periodic_cleanup_triggered(self, mock_time):
        """Test periodic cleanup is triggered after interval."""
        # Set last cleanup to 2 hours ago
        self.manager._last_cleanup = 0.0
        mock_time.return_value = 2 * 60 * 60 + 1  # Just past cleanup interval

        self.manager.cleanup_expired_sessions = Mock(return_value=5)

        self.manager._periodic_cleanup()

        # Should have triggered cleanup
        self.manager.cleanup_expired_sessions.assert_called_once()
        self.assertEqual(self.manager._last_cleanup, 2 * 60 * 60 + 1)

    @patch("ethoscope_node.auth.session.time.time")
    def test_periodic_cleanup_not_triggered(self, mock_time):
        """Test periodic cleanup not triggered before interval."""
        current_time = 1000.0
        self.manager._last_cleanup = current_time - 100  # Only 100 seconds ago
        mock_time.return_value = current_time

        self.manager.cleanup_expired_sessions = Mock()

        self.manager._periodic_cleanup()

        # Should NOT trigger cleanup (not enough time passed)
        self.manager.cleanup_expired_sessions.assert_not_called()

    def test_get_active_sessions_long_user_agent(self):
        """Test that long user agents are truncated in session list."""
        with patch("ethoscope_node.auth.session.time.time") as mock_time:
            mock_time.return_value = 1000.0

            # Mock session with very long user agent
            long_ua = "X" * 200  # 200 characters
            sessions_data = [
                ("token1", "user1", 100.0, 900.0, 2000.0, "192.168.1.1", long_ua),
            ]
            self.mock_db.executeSQL.return_value = sessions_data

            sessions = self.manager.get_active_sessions()

            # User agent should be truncated to 100 chars + "..."
            self.assertEqual(len(sessions[0]["user_agent"]), 103)
            self.assertTrue(sessions[0]["user_agent"].endswith("..."))

    def test_ensure_sessions_table_exception(self):
        """Test exception handling in sessions table creation."""
        mock_db = Mock()
        mock_db.executeSQL.side_effect = Exception("Database error")

        with patch.object(SessionManager, "__init__", lambda x, y, z: None):
            manager = SessionManager.__new__(SessionManager)
            manager.database = mock_db
            manager.logger = Mock()

            manager._ensure_sessions_table()

            # Should log error
            manager.logger.error.assert_called()
            error_call = manager.logger.error.call_args[0][0]
            self.assertIn("Error ensuring sessions table", error_call)

    @patch("ethoscope_node.auth.session.time.time")
    @patch("bottle.request")
    def test_create_session_exception(self, mock_request, mock_time):
        """Test exception handling in session creation."""
        mock_time.return_value = 1000.0
        mock_request.environ = {"HTTP_USER_AGENT": "Test", "REMOTE_ADDR": "127.0.0.1"}

        # Cause exception by making database raise
        self.mock_db.executeSQL.side_effect = Exception("Database error")

        user = {"username": "testuser", "id": 1}
        token = self.manager.create_session(user)

        # Should return None and log error
        self.assertIsNone(token)

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_user_from_session_exception(self, mock_time):
        """Test exception handling in session validation."""
        mock_time.return_value = 1000.0

        # Cause exception
        self.mock_db.executeSQL.side_effect = Exception("Database error")

        user = self.manager.get_user_from_session("test_token")

        # Should return None
        self.assertIsNone(user)

    def test_destroy_session_exception(self):
        """Test exception handling in session destruction."""
        self.mock_db.executeSQL.side_effect = Exception("Database error")

        result = self.manager.destroy_session("test_token")

        # Should return False
        self.assertFalse(result)

    def test_destroy_user_sessions_exception(self):
        """Test exception handling in user sessions destruction."""
        self.mock_db.executeSQL.side_effect = Exception("Database error")

        result = self.manager.destroy_user_sessions("testuser")

        # Should return False
        self.assertFalse(result)

    @patch("ethoscope_node.auth.session.time.time")
    def test_get_active_sessions_exception(self, mock_time):
        """Test exception handling in get active sessions."""
        mock_time.return_value = 1000.0

        self.mock_db.executeSQL.side_effect = Exception("Database error")

        sessions = self.manager.get_active_sessions()

        # Should return empty list
        self.assertEqual(sessions, [])

    @patch("ethoscope_node.auth.session.time.time")
    def test_cleanup_expired_sessions_exception(self, mock_time):
        """Test exception handling in cleanup."""
        mock_time.return_value = 1000.0

        self.mock_db.executeSQL.side_effect = Exception("Database error")

        count = self.manager.cleanup_expired_sessions()

        # Should return 0
        self.assertEqual(count, 0)

    def test_get_client_ip_exception(self):
        """Test exception handling in get client IP."""
        with patch("bottle.request") as mock_request:
            # Cause exception when accessing environ
            mock_request.environ.get.side_effect = Exception("Request error")

            ip = self.manager._get_client_ip()

            # Should return "unknown"
            self.assertEqual(ip, "unknown")

    def test_update_session_access_exception(self):
        """Test exception handling in session access update."""
        self.mock_db.executeSQL.side_effect = Exception("Database error")

        # Should not raise exception
        self.manager._update_session_access("test_token", 1500.0)

        # Method should complete without error (exception is logged)

    @patch("ethoscope_node.auth.session.time.time")
    def test_limit_user_sessions_exception(self, mock_time):
        """Test exception handling in session limiting."""
        mock_time.return_value = 1000.0

        self.mock_db.executeSQL.side_effect = Exception("Database error")

        # Should not raise exception
        self.manager._limit_user_sessions("testuser")

        # Method should complete without error (exception is logged)


if __name__ == "__main__":
    unittest.main()
