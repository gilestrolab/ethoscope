"""
Authentication module for Ethoscope Node.

Provides PIN-based user authentication with session management,
rate limiting, and security features.
"""

from .middleware import AuthMiddleware
from .middleware import require_admin
from .middleware import require_auth
from .session import SessionManager

__all__ = ["AuthMiddleware", "require_auth", "require_admin", "SessionManager"]
