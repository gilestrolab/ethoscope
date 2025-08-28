"""
Authentication middleware for Ethoscope Node.

Provides secure session management, PIN validation, and authentication decorators.
"""

import bottle
import datetime
import secrets
import logging
import time
from typing import Dict, Optional, Callable, Any
from functools import wraps
from .session import SessionManager


class AuthMiddleware:
    """
    Authentication middleware for managing user sessions and PIN-based authentication.
    
    Features:
    - Secure session management with signed cookies
    - Rate limiting for login attempts  
    - PIN validation with bcrypt hashing
    - Role-based access control (admin vs regular users)
    """
    
    def __init__(self, database, config):
        """
        Initialize authentication middleware.
        
        Args:
            database: ExperimentalDB instance
            config: EthoscopeConfiguration instance
        """
        self.database = database
        self.config = config
        self.session_manager = SessionManager(database, config)
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Rate limiting storage (in production, use Redis or database)
        self._login_attempts = {}  # {username: {'count': int, 'last_attempt': timestamp}}
        self._ip_attempts = {}     # {ip: {'count': int, 'last_attempt': timestamp}}
        
        # Configuration defaults
        self.max_attempts = 5
        self.lockout_duration = 15 * 60  # 15 minutes
        self.session_timeout = 2 * 60 * 60  # 2 hours
        self.progressive_lockout = True
    
    def get_current_user(self) -> Optional[Dict[str, Any]]:
        """
        Get current authenticated user from session.
        
        Returns:
            User dictionary if authenticated, None otherwise
        """
        session_token = bottle.request.get_cookie('ethoscope_session')
        if not session_token:
            return None
        
        return self.session_manager.get_user_from_session(session_token)
    
    def is_authenticated(self) -> bool:
        """Check if current request is from an authenticated user."""
        return self.get_current_user() is not None
    
    def is_admin(self) -> bool:
        """Check if current user is an administrator."""
        user = self.get_current_user()
        if not user:
            return False
        return bool(user.get('isadmin', 0))
    
    def check_rate_limit(self, username: str, client_ip: str) -> bool:
        """
        Check if login attempt is within rate limits.
        
        Args:
            username: Username attempting login
            client_ip: Client IP address
            
        Returns:
            True if attempt is allowed, False if rate limited
        """
        current_time = time.time()
        
        # Clean old attempts
        self._clean_old_attempts(current_time)
        
        # Check username-based rate limiting
        user_attempts = self._login_attempts.get(username, {'count': 0, 'last_attempt': 0})
        if user_attempts['count'] >= self.max_attempts:
            lockout_time = self._get_lockout_duration(user_attempts['count'])
            if current_time - user_attempts['last_attempt'] < lockout_time:
                self.logger.warning(f"Rate limit exceeded for user: {username}")
                return False
        
        # Check IP-based rate limiting
        ip_attempts = self._ip_attempts.get(client_ip, {'count': 0, 'last_attempt': 0})
        if ip_attempts['count'] >= self.max_attempts * 3:  # More lenient for IP
            if current_time - ip_attempts['last_attempt'] < self.lockout_duration:
                self.logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return False
        
        return True
    
    def record_failed_attempt(self, username: str, client_ip: str):
        """
        Record a failed login attempt for rate limiting.
        
        Args:
            username: Username that failed login
            client_ip: Client IP address
        """
        current_time = time.time()
        
        # Record username attempt
        if username not in self._login_attempts:
            self._login_attempts[username] = {'count': 0, 'last_attempt': 0}
        self._login_attempts[username]['count'] += 1
        self._login_attempts[username]['last_attempt'] = current_time
        
        # Record IP attempt
        if client_ip not in self._ip_attempts:
            self._ip_attempts[client_ip] = {'count': 0, 'last_attempt': 0}
        self._ip_attempts[client_ip]['count'] += 1
        self._ip_attempts[client_ip]['last_attempt'] = current_time
        
        self.logger.info(f"Recorded failed login attempt for {username} from {client_ip}")
    
    def clear_failed_attempts(self, username: str):
        """Clear failed attempts for successful login."""
        if username in self._login_attempts:
            del self._login_attempts[username]
    
    def authenticate_user(self, username: str, pin: str, client_ip: str) -> Optional[Dict[str, Any]]:
        """
        Authenticate user with PIN.
        
        Args:
            username: Username to authenticate
            pin: PIN to verify
            client_ip: Client IP address for rate limiting
            
        Returns:
            User dictionary if authentication successful, None otherwise
        """
        # Check rate limiting
        if not self.check_rate_limit(username, client_ip):
            return None
        
        # Get user from database
        user = self.database.getUserByName(username, asdict=True)
        if not user:
            self.record_failed_attempt(username, client_ip)
            self.logger.warning(f"Authentication failed - user not found: {username}")
            return None
        
        # Check if user is active
        if not user.get('active', 0):
            self.record_failed_attempt(username, client_ip)
            self.logger.warning(f"Authentication failed - inactive user: {username}")
            return None
        
        # Verify PIN
        if not self.database.verify_pin(username, pin):
            self.record_failed_attempt(username, client_ip)
            self.logger.warning(f"Authentication failed - invalid PIN for user: {username}")
            return None
        
        # Clear failed attempts on successful login
        self.clear_failed_attempts(username)
        
        self.logger.info(f"User authenticated successfully: {username}")
        return user
    
    def login_user(self, username: str, pin: str) -> Optional[str]:
        """
        Perform user login and create session.
        
        Args:
            username: Username to login
            pin: PIN to verify
            
        Returns:
            Session token if successful, None otherwise
        """
        client_ip = self._get_client_ip()
        
        # Authenticate user
        user = self.authenticate_user(username, pin, client_ip)
        if not user:
            return None
        
        # Create session
        session_token = self.session_manager.create_session(user)
        if not session_token:
            self.logger.error(f"Failed to create session for user: {username}")
            return None
        
        # Set secure cookie
        self._set_session_cookie(session_token)
        
        return session_token
    
    def logout_user(self) -> bool:
        """
        Logout current user and destroy session.
        
        Returns:
            True if logout successful, False otherwise
        """
        session_token = bottle.request.get_cookie('ethoscope_session')
        if not session_token:
            return False
        
        # Destroy session
        success = self.session_manager.destroy_session(session_token)
        
        # Clear cookie
        bottle.response.delete_cookie('ethoscope_session')
        
        return success
    
    def _get_client_ip(self) -> str:
        """Get client IP address from request."""
        # Try X-Forwarded-For header first (for proxies)
        forwarded_for = bottle.request.environ.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        # Fall back to REMOTE_ADDR
        return bottle.request.environ.get('REMOTE_ADDR', 'unknown')
    
    def _set_session_cookie(self, session_token: str):
        """Set secure session cookie."""
        bottle.response.set_cookie(
            'ethoscope_session',
            session_token,
            max_age=self.session_timeout,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite='Lax',
            path='/'
        )
    
    def _get_lockout_duration(self, attempt_count: int) -> int:
        """Get lockout duration based on attempt count (progressive lockout)."""
        if not self.progressive_lockout:
            return self.lockout_duration
        
        # Progressive lockout: 5min, 15min, 1hr, 3hr, 24hr
        durations = [5 * 60, 15 * 60, 60 * 60, 3 * 60 * 60, 24 * 60 * 60]
        index = min(attempt_count - self.max_attempts, len(durations) - 1)
        return durations[index]
    
    def _clean_old_attempts(self, current_time: float):
        """Clean old failed attempts that are outside lockout window."""
        # Clean username attempts
        expired_users = []
        for username, attempts in self._login_attempts.items():
            lockout_time = self._get_lockout_duration(attempts['count'])
            if current_time - attempts['last_attempt'] > lockout_time:
                expired_users.append(username)
        
        for username in expired_users:
            del self._login_attempts[username]
        
        # Clean IP attempts
        expired_ips = []
        for ip, attempts in self._ip_attempts.items():
            if current_time - attempts['last_attempt'] > self.lockout_duration:
                expired_ips.append(ip)
        
        for ip in expired_ips:
            del self._ip_attempts[ip]


def require_auth(func: Callable) -> Callable:
    """
    Decorator to require authentication for API endpoints.
    
    Usage:
        @require_auth
        def protected_endpoint():
            # This endpoint requires authentication
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get auth middleware from bottle app
        auth_middleware = getattr(bottle.app(), 'auth_middleware', None)
        if not auth_middleware:
            bottle.abort(500, "Authentication middleware not available")
        
        # Check if authentication is enabled in configuration
        config = auth_middleware.config
        auth_enabled = False
        
        # Check authentication.enabled setting
        try:
            # Method 1: Direct access to authentication config through settings
            if hasattr(config, '_settings'):
                auth_config = config._settings.get('authentication', {})
                auth_enabled = bool(auth_config.get('enabled', False))
            # Method 2: Try using get_authentication_config method
            elif hasattr(config, 'get_authentication_config'):
                auth_config = config.get_authentication_config()
                auth_enabled = bool(auth_config.get('enabled', False))
        except Exception:
            auth_enabled = False  # Default to disabled if we can't determine the setting
        
        # If authentication is disabled, allow access without checking
        if not auth_enabled:
            return func(*args, **kwargs)
        
        # Authentication is enabled, check if user is authenticated
        if not auth_middleware.is_authenticated():
            bottle.abort(401, "Authentication required")
        
        return func(*args, **kwargs)
    return wrapper


def require_admin(func: Callable) -> Callable:
    """
    Decorator to require admin privileges for API endpoints.
    
    Usage:
        @require_admin
        def admin_only_endpoint():
            # This endpoint requires admin privileges
            pass
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get auth middleware from bottle app
        auth_middleware = getattr(bottle.app(), 'auth_middleware', None)
        if not auth_middleware:
            bottle.abort(500, "Authentication middleware not available")
        
        # Check if authentication is enabled in configuration
        config = auth_middleware.config
        auth_enabled = False
        
        # Check authentication.enabled setting
        try:
            # Method 1: Direct access to authentication config through settings
            if hasattr(config, '_settings'):
                auth_config = config._settings.get('authentication', {})
                auth_enabled = bool(auth_config.get('enabled', False))
            # Method 2: Try using get_authentication_config method
            elif hasattr(config, 'get_authentication_config'):
                auth_config = config.get_authentication_config()
                auth_enabled = bool(auth_config.get('enabled', False))
        except Exception:
            auth_enabled = False  # Default to disabled if we can't determine the setting
        
        # If authentication is disabled, allow admin access without checking
        if not auth_enabled:
            return func(*args, **kwargs)
        
        # Authentication is enabled, check if user is authenticated and admin
        if not auth_middleware.is_authenticated():
            bottle.abort(401, "Authentication required")
        
        if not auth_middleware.is_admin():
            bottle.abort(403, "Admin privileges required")
        
        return func(*args, **kwargs)
    return wrapper


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Helper function to get current authenticated user.
    
    Returns:
        User dictionary if authenticated, None otherwise
    """
    auth_middleware = getattr(bottle.app(), 'auth_middleware', None)
    if not auth_middleware:
        return None
    
    return auth_middleware.get_current_user()