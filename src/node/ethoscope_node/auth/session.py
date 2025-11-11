"""
Session management for Ethoscope Node authentication.

Handles secure session creation, validation, and cleanup.
"""

import datetime
import logging
import secrets
import time
from typing import Any
from typing import Dict
from typing import Optional


class SessionManager:
    """
    Manages user sessions with secure token generation and validation.

    Sessions are stored in the database with automatic cleanup of expired sessions.
    """

    def __init__(self, database, config):
        """
        Initialize session manager.

        Args:
            database: ExperimentalDB instance
            config: EthoscopeConfiguration instance
        """
        self.database = database
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

        # Configuration
        self.session_timeout = 2 * 60 * 60  # 2 hours default
        self.cleanup_interval = 60 * 60  # Cleanup every hour
        self.max_sessions_per_user = 5  # Limit concurrent sessions

        # Ensure sessions table exists
        self._ensure_sessions_table()

        # Track last cleanup time
        self._last_cleanup = time.time()

    def _ensure_sessions_table(self):
        """Ensure sessions table exists in database."""
        try:
            sql_create_sessions = """
            CREATE TABLE IF NOT EXISTS sessions (
                session_token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                user_id INTEGER,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                expires_at REAL NOT NULL,
                client_ip TEXT,
                user_agent TEXT,
                active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """

            result = self.database.executeSQL(sql_create_sessions)
            if result == -1:
                self.logger.error("Failed to create sessions table")
            else:
                self.logger.debug("Sessions table ensured")

            # Create indexes for performance
            sql_create_index_username = "CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions (username);"
            sql_create_index_expires = "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);"

            result1 = self.database.executeSQL(sql_create_index_username)
            result2 = self.database.executeSQL(sql_create_index_expires)

            if result1 == -1 or result2 == -1:
                self.logger.error("Failed to create one or more session indexes")

        except Exception as e:
            self.logger.error(f"Error ensuring sessions table: {e}")

    def create_session(self, user: Dict[str, Any]) -> Optional[str]:
        """
        Create a new session for the user.

        Args:
            user: User dictionary from database

        Returns:
            Session token if successful, None otherwise
        """
        try:
            username = user.get("username")
            user_id = user.get("id")

            if not username:
                self.logger.error("Cannot create session: username missing")
                return None

            # Clean up expired sessions periodically
            self._periodic_cleanup()

            # Limit concurrent sessions per user
            self._limit_user_sessions(username)

            # Generate secure session token
            session_token = self._generate_session_token()

            # Get request info
            import bottle

            client_ip = self._get_client_ip()
            user_agent = bottle.request.environ.get("HTTP_USER_AGENT", "")[
                :255
            ]  # Limit length

            # Session timestamps
            current_time = time.time()
            expires_at = current_time + self.session_timeout

            # Insert session into database
            sql_insert = """
            INSERT INTO sessions
            (session_token, username, user_id, created_at, last_accessed, expires_at, client_ip, user_agent, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """

            result = self.database.executeSQL(
                sql_insert,
                (
                    session_token,
                    username,
                    user_id,
                    current_time,
                    current_time,
                    expires_at,
                    client_ip,
                    user_agent,
                ),
            )

            if result == -1:
                self.logger.error(f"Failed to create session for user: {username}")
                return None

            self.logger.info(f"Created session for user: {username}")
            return session_token

        except Exception as e:
            self.logger.error(f"Error creating session: {e}")
            return None

    def get_user_from_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """
        Get user information from session token.

        Args:
            session_token: Session token to validate

        Returns:
            User dictionary if session is valid, None otherwise
        """
        try:
            current_time = time.time()

            # Get session from database
            sql_get_session = """
            SELECT s.username, s.user_id, s.expires_at, s.active,
                   u.username, u.fullname, u.email, u.telephone, u.labname, u.active as user_active, u.isadmin
            FROM sessions s
            JOIN users u ON s.username = u.username
            WHERE s.session_token = ? AND s.active = 1 AND s.expires_at > ?
            """

            result = self.database.executeSQL(
                sql_get_session, (session_token, current_time)
            )

            if not result or len(result) == 0:
                return None

            session_data = result[0]

            # Handle tuple format - database returns tuples by default
            # Column order: s.username(0), s.user_id(1), s.expires_at(2), s.active(3),
            #              u.username(4), u.fullname(5), u.email(6), u.telephone(7),
            #              u.labname(8), u.active as user_active(9), u.isadmin(10)

            session_data[0]
            user_id = session_data[1]
            username = session_data[4]
            fullname = session_data[5]
            email = session_data[6]
            telephone = session_data[7]
            labname = session_data[8]
            user_active = session_data[9]
            isadmin = session_data[10]

            # Check if user is still active
            if not user_active:
                self.logger.warning(f"Session for inactive user: {username}")
                self.destroy_session(session_token)
                return None

            # Update last accessed time
            self._update_session_access(session_token, current_time)

            # Return user information
            return {
                "id": user_id,
                "username": username,
                "fullname": fullname or "",
                "email": email or "",
                "telephone": telephone or "",
                "labname": labname or "",
                "active": user_active,
                "isadmin": isadmin,
            }

        except Exception as e:
            self.logger.error(f"Error validating session: {e}")
            return None

    def destroy_session(self, session_token: str) -> bool:
        """
        Destroy a session (logout).

        Args:
            session_token: Session token to destroy

        Returns:
            True if successful, False otherwise
        """
        try:
            sql_destroy = """
            UPDATE sessions
            SET active = 0
            WHERE session_token = ?
            """

            result = self.database.executeSQL(sql_destroy, (session_token,))

            if result == -1:
                self.logger.error(f"Failed to destroy session: {session_token}")
                return False

            self.logger.debug("Session destroyed successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error destroying session: {e}")
            return False

    def destroy_user_sessions(self, username: str) -> bool:
        """
        Destroy all sessions for a user.

        Args:
            username: Username to destroy sessions for

        Returns:
            True if successful, False otherwise
        """
        try:
            sql_destroy = """
            UPDATE sessions
            SET active = 0
            WHERE username = ? AND active = 1
            """

            result = self.database.executeSQL(sql_destroy, (username,))

            if result == -1:
                self.logger.error(f"Failed to destroy sessions for user: {username}")
                return False

            self.logger.info(f"Destroyed all sessions for user: {username}")
            return True

        except Exception as e:
            self.logger.error(f"Error destroying user sessions: {e}")
            return False

    def get_active_sessions(self, username: Optional[str] = None) -> list:
        """
        Get list of active sessions.

        Args:
            username: Optional username to filter by

        Returns:
            List of active session dictionaries
        """
        try:
            current_time = time.time()

            if username:
                sql_get_sessions = """
                SELECT session_token, username, created_at, last_accessed, expires_at, client_ip, user_agent
                FROM sessions
                WHERE username = ? AND active = 1 AND expires_at > ?
                ORDER BY last_accessed DESC
                """
                params = (username, current_time)
            else:
                sql_get_sessions = """
                SELECT session_token, username, created_at, last_accessed, expires_at, client_ip, user_agent
                FROM sessions
                WHERE active = 1 AND expires_at > ?
                ORDER BY last_accessed DESC
                """
                params = (current_time,)

            result = self.database.executeSQL(sql_get_sessions, params)

            if not result:
                return []

            sessions = []
            for row in result:
                # Handle tuple format - database returns tuples by default
                # Column order: session_token(0), username(1), created_at(2), last_accessed(3), expires_at(4), client_ip(5), user_agent(6)
                sessions.append(
                    {
                        "session_token": row[0][:16] + "...",  # Truncate for security
                        "username": row[1],
                        "created_at": datetime.datetime.fromtimestamp(
                            row[2]
                        ).isoformat(),
                        "last_accessed": datetime.datetime.fromtimestamp(
                            row[3]
                        ).isoformat(),
                        "expires_at": datetime.datetime.fromtimestamp(
                            row[4]
                        ).isoformat(),
                        "client_ip": row[5],
                        "user_agent": (
                            row[6][:100] + "..." if len(row[6]) > 100 else row[6]
                        ),
                    }
                )

            return sessions

        except Exception as e:
            self.logger.error(f"Error getting active sessions: {e}")
            return []

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions from database.

        Returns:
            Number of sessions cleaned up
        """
        try:
            current_time = time.time()

            # Get count before cleanup
            sql_count = "SELECT COUNT(*) as count FROM sessions WHERE expires_at <= ? AND active = 1"
            count_result = self.database.executeSQL(sql_count, (current_time,))
            expired_count = (
                count_result[0][0] if count_result else 0
            )  # First row, first column

            # Delete expired sessions
            sql_cleanup = "DELETE FROM sessions WHERE expires_at <= ?"
            result = self.database.executeSQL(sql_cleanup, (current_time,))

            if result != -1 and expired_count > 0:
                self.logger.info(f"Cleaned up {expired_count} expired sessions")

            return expired_count

        except Exception as e:
            self.logger.error(f"Error cleaning up expired sessions: {e}")
            return 0

    def _generate_session_token(self) -> str:
        """Generate a secure session token."""
        return secrets.token_urlsafe(32)  # 256-bit token

    def _get_client_ip(self) -> str:
        """Get client IP address from request."""
        try:
            import bottle

            # Try X-Forwarded-For header first (for proxies)
            forwarded_for = bottle.request.environ.get("HTTP_X_FORWARDED_FOR")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()

            # Fall back to REMOTE_ADDR
            return bottle.request.environ.get("REMOTE_ADDR", "unknown")
        except Exception:
            return "unknown"

    def _update_session_access(self, session_token: str, current_time: float):
        """Update last accessed time for session."""
        try:
            sql_update = """
            UPDATE sessions
            SET last_accessed = ?
            WHERE session_token = ?
            """

            self.database.executeSQL(sql_update, (current_time, session_token))

        except Exception as e:
            self.logger.error(f"Error updating session access time: {e}")

    def _limit_user_sessions(self, username: str):
        """Limit number of concurrent sessions per user."""
        try:
            current_time = time.time()

            # Get active sessions for user
            sql_get_user_sessions = """
            SELECT session_token, last_accessed
            FROM sessions
            WHERE username = ? AND active = 1 AND expires_at > ?
            ORDER BY last_accessed ASC
            """

            result = self.database.executeSQL(
                sql_get_user_sessions, (username, current_time)
            )

            if not result or len(result) < self.max_sessions_per_user:
                return

            # Destroy oldest sessions to make room
            sessions_to_remove = len(result) - self.max_sessions_per_user + 1
            for i in range(sessions_to_remove):
                session_token = result[i][0]  # First column is session_token
                self.destroy_session(session_token)
                self.logger.debug(
                    f"Destroyed old session for user {username} to enforce limit"
                )

        except Exception as e:
            self.logger.error(f"Error limiting user sessions: {e}")

    def _periodic_cleanup(self):
        """Perform periodic cleanup of expired sessions."""
        current_time = time.time()

        # Only cleanup if enough time has passed
        if current_time - self._last_cleanup > self.cleanup_interval:
            self.cleanup_expired_sessions()
            self._last_cleanup = current_time
