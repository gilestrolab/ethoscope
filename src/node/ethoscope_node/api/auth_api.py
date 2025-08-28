"""
Authentication API Module

Handles user authentication, login/logout, and session management endpoints.
"""

import bottle
import datetime
import logging
import time
from typing import Dict, Any, Optional
from .base import BaseAPI, error_decorator
from ethoscope_node.auth.middleware import get_current_user, require_auth


class AuthAPI(BaseAPI):
    """API endpoints for user authentication and session management."""
    
    def register_routes(self):
        """Register authentication-related routes."""
        self.app.route('/auth/login', method='POST')(self._login)
        self.app.route('/auth/logout', method='POST')(self._logout)  
        self.app.route('/auth/session', method='GET')(self._get_session)
        self.app.route('/auth/change-pin', method='POST')(self._change_pin)
        self.app.route('/auth/sessions', method='GET')(self._get_all_sessions)
        self.app.route('/auth/sessions/<username>', method='DELETE')(self._terminate_user_sessions)
        
        # Also register the API check endpoint that the frontend expects
        self.app.route('/api/auth/check', method='GET')(self._check_auth)
    
    @error_decorator
    def _login(self):
        """Handle user login with PIN authentication."""
        try:
            data = self.get_request_json()
            
            # Debug logging
            self.logger.info(f"Login request received - data: {data}")
            
            # Validate input
            username = data.get('username', '').strip()
            pin = data.get('pin', '').strip()
            
            # Debug logging
            self.logger.info(f"Login attempt - username: '{username}', pin length: {len(pin)}")
            
            if not username:
                return {
                    'success': False,
                    'message': 'Username is required'
                }
            
            if not pin:
                return {
                    'success': False,
                    'message': 'PIN is required'
                }
            
            # Get auth middleware
            auth_middleware = getattr(self.app, 'auth_middleware', None)
            if not auth_middleware:
                self.logger.error("Authentication middleware not available")
                return {
                    'success': False,
                    'message': 'Authentication system not available'
                }
            
            # Attempt login
            session_token = auth_middleware.login_user(username, pin)
            
            if session_token:
                # Get user information directly from database
                user = self.database.getUserByName(username, asdict=True)
                
                self.logger.info(f"Successful login for user: {username}")
                return {
                    'success': True,
                    'message': 'Login successful',
                    'user': {
                        'username': user.get('username'),
                        'fullname': user.get('fullname', ''),
                        'email': user.get('email', ''),
                        'isadmin': bool(user.get('isadmin', 0)),
                        'labname': user.get('labname', '')
                    },
                    'session_token': session_token  # For debugging/testing only
                }
            else:
                self.logger.warning(f"Failed login attempt for user: {username}")
                return {
                    'success': False,
                    'message': 'Invalid username or PIN'
                }
                
        except Exception as e:
            self.logger.error(f"Error during login: {e}")
            return {
                'success': False,
                'message': 'Login failed due to server error'
            }
    
    @error_decorator
    def _logout(self):
        """Handle user logout."""
        try:
            # Get auth middleware
            auth_middleware = getattr(self.app, 'auth_middleware', None)
            if not auth_middleware:
                return {
                    'success': False,
                    'message': 'Authentication system not available'
                }
            
            # Get current user for logging
            current_user = auth_middleware.get_current_user()
            username = current_user.get('username', 'unknown') if current_user else 'unknown'
            
            # Attempt logout
            success = auth_middleware.logout_user()
            
            if success:
                self.logger.info(f"User logged out: {username}")
                return {
                    'success': True,
                    'message': 'Logout successful'
                }
            else:
                return {
                    'success': False,
                    'message': 'Logout failed - no active session'
                }
                
        except Exception as e:
            self.logger.error(f"Error during logout: {e}")
            return {
                'success': False,
                'message': 'Logout failed due to server error'
            }
    
    @error_decorator
    def _get_session(self):
        """Get current session information."""
        try:
            # Get auth middleware
            auth_middleware = getattr(self.app, 'auth_middleware', None)
            if not auth_middleware:
                return {
                    'authenticated': False,
                    'message': 'Authentication system not available'
                }
            
            # Check if authentication is enabled in configuration
            # Use the same approach as in _check_auth but with proper access to config
            auth_enabled = False
            
            # Try to access authentication setting through the configuration
            try:
                # Method 1: Direct access to authentication config through settings
                if hasattr(self.config, '_settings'):
                    auth_config = self.config._settings.get('authentication', {})
                    auth_enabled = bool(auth_config.get('enabled', False))
                # Method 2: Try using get_authentication_config method
                elif hasattr(self.config, 'get_authentication_config'):
                    auth_config = self.config.get_authentication_config()
                    auth_enabled = bool(auth_config.get('enabled', False))
            except Exception as config_error:
                self.logger.warning(f"Could not access authentication configuration: {config_error}")
                auth_enabled = False  # Default to disabled if we can't determine the setting
            
            # If authentication is disabled, return mock authenticated user
            if not auth_enabled:
                return {
                    'authenticated': True,
                    'user': {
                        'username': 'system',
                        'fullname': 'System User',
                        'email': '',
                        'telephone': '',
                        'labname': '',
                        'isadmin': True,
                        'active': True
                    }
                }
            
            # Authentication is enabled, check for real user session
            user = auth_middleware.get_current_user()
            
            if user:
                return {
                    'authenticated': True,
                    'user': {
                        'username': user.get('username'),
                        'fullname': user.get('fullname', ''),
                        'email': user.get('email', ''),
                        'telephone': user.get('telephone', ''),
                        'labname': user.get('labname', ''),
                        'isadmin': bool(user.get('isadmin', 0)),
                        'active': bool(user.get('active', 0))
                    }
                }
            else:
                return {
                    'authenticated': False,
                    'user': None
                }
                
        except Exception as e:
            self.logger.error(f"Error getting session info: {e}")
            return {
                'authenticated': False,
                'message': 'Error retrieving session information'
            }
    
    @error_decorator
    @require_auth
    def _change_pin(self):
        """Handle PIN change for current user."""
        try:
            data = self.get_request_json()
            
            # Validate input
            current_pin = data.get('current_pin', '').strip()
            new_pin = data.get('new_pin', '').strip()
            confirm_pin = data.get('confirm_pin', '').strip()
            
            if not current_pin:
                return {
                    'success': False,
                    'message': 'Current PIN is required'
                }
            
            if not new_pin:
                return {
                    'success': False,
                    'message': 'New PIN is required'
                }
            
            if new_pin != confirm_pin:
                return {
                    'success': False,
                    'message': 'New PIN confirmation does not match'
                }
            
            # Get current user
            current_user = get_current_user()
            if not current_user:
                return {
                    'success': False,
                    'message': 'No active session'
                }
            
            username = current_user.get('username')
            
            # Verify current PIN
            if not self.database.verify_pin(username, current_pin):
                self.logger.warning(f"PIN change failed - invalid current PIN for user: {username}")
                return {
                    'success': False,
                    'message': 'Current PIN is incorrect'
                }
            
            # Hash and update new PIN
            hashed_pin = self.database.hash_pin(new_pin)
            if not hashed_pin:
                self.logger.error(f"Failed to hash new PIN for user: {username}")
                return {
                    'success': False,
                    'message': 'Failed to process new PIN'
                }
            
            # Update PIN in database
            result = self.database.updateUser(username=username, pin=hashed_pin)
            
            if result >= 0:
                self.logger.info(f"PIN changed successfully for user: {username}")
                return {
                    'success': True,
                    'message': 'PIN changed successfully'
                }
            else:
                self.logger.error(f"Failed to update PIN for user: {username}")
                return {
                    'success': False,
                    'message': 'Failed to update PIN'
                }
                
        except Exception as e:
            self.logger.error(f"Error during PIN change: {e}")
            return {
                'success': False,
                'message': 'PIN change failed due to server error'
            }
    
    @error_decorator
    @require_auth
    def _get_all_sessions(self):
        """Get list of active sessions (admin only for all, user for own)."""
        try:
            # Get auth middleware
            auth_middleware = getattr(self.app, 'auth_middleware', None)
            if not auth_middleware:
                return {
                    'success': False,
                    'message': 'Authentication system not available'
                }
            
            current_user = get_current_user()
            if not current_user:
                return {
                    'success': False,
                    'message': 'No active session'
                }
            
            username = current_user.get('username')
            is_admin = bool(current_user.get('isadmin', 0))
            
            # Get sessions based on user privileges
            if is_admin:
                # Admin can see all sessions
                sessions = auth_middleware.session_manager.get_active_sessions()
            else:
                # Regular user can only see their own sessions
                sessions = auth_middleware.session_manager.get_active_sessions(username)
            
            return {
                'success': True,
                'sessions': sessions,
                'total_count': len(sessions)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting sessions: {e}")
            return {
                'success': False,
                'message': 'Failed to retrieve sessions'
            }
    
    @error_decorator
    @require_auth
    def _terminate_user_sessions(self, username):
        """Terminate all sessions for a user (admin only or own sessions)."""
        try:
            # Get auth middleware
            auth_middleware = getattr(self.app, 'auth_middleware', None)
            if not auth_middleware:
                return {
                    'success': False,
                    'message': 'Authentication system not available'
                }
            
            current_user = get_current_user()
            if not current_user:
                return {
                    'success': False,
                    'message': 'No active session'
                }
            
            current_username = current_user.get('username')
            is_admin = bool(current_user.get('isadmin', 0))
            
            # Check permissions
            if not is_admin and username != current_username:
                return {
                    'success': False,
                    'message': 'Insufficient privileges to terminate sessions for other users'
                }
            
            # Terminate sessions
            success = auth_middleware.session_manager.destroy_user_sessions(username)
            
            if success:
                self.logger.info(f"Terminated all sessions for user: {username} (by {current_username})")
                return {
                    'success': True,
                    'message': f'All sessions terminated for user: {username}'
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to terminate sessions'
                }
                
        except Exception as e:
            self.logger.error(f"Error terminating sessions: {e}")
            return {
                'success': False,
                'message': 'Failed to terminate sessions'
            }
    
    @error_decorator
    def _check_auth(self):
        """Check authentication status - compatible with frontend expectations."""
        try:
            # Get auth middleware
            auth_middleware = getattr(self.app, 'auth_middleware', None)
            if not auth_middleware:
                return {
                    'authenticated': False,
                    'user': None
                }
            
            # Check if authentication is enabled in configuration
            auth_enabled = False
            
            # Try to access authentication setting through the configuration
            try:
                # Method 1: Direct access to authentication config through settings
                if hasattr(self.config, '_settings'):
                    auth_config = self.config._settings.get('authentication', {})
                    auth_enabled = bool(auth_config.get('enabled', False))
                # Method 2: Try using get_authentication_config method
                elif hasattr(self.config, 'get_authentication_config'):
                    auth_config = self.config.get_authentication_config()
                    auth_enabled = bool(auth_config.get('enabled', False))
            except Exception as config_error:
                self.logger.warning(f"Could not access authentication configuration: {config_error}")
                auth_enabled = False  # Default to disabled if we can't determine the setting
            
            # If authentication is disabled, return mock authenticated user
            if not auth_enabled:
                return {
                    'authenticated': True,
                    'user': {
                        'username': 'system',
                        'fullname': 'System User',
                        'email': '',
                        'is_admin': True
                    }
                }
            
            # Authentication is enabled, check for real user session
            current_user = get_current_user()
            if current_user:
                return {
                    'authenticated': True,
                    'user': {
                        'username': current_user.get('username'),
                        'fullname': current_user.get('fullname'),
                        'email': current_user.get('email'),
                        'is_admin': bool(current_user.get('isadmin', 0))
                    }
                }
            else:
                return {
                    'authenticated': False,
                    'user': None
                }
                
        except Exception as e:
            self.logger.error(f"Error checking authentication: {e}")
            return {
                'authenticated': False,
                'user': None
            }