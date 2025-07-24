"""
Setup API Module

Handles installation wizard and first-time setup functionality.
"""

import bottle
import os
import datetime
import shutil
from pathlib import Path
from .base import BaseAPI, error_decorator
from ethoscope_node.utils.etho_db import ExperimentalDB


class SetupAPI(BaseAPI):
    """API endpoints for installation wizard and setup management."""
    
    def register_routes(self):
        """Register setup-related routes."""
        self.app.route('/setup/<action>', method='GET')(self._setup_get)
        self.app.route('/setup/<action>', method='POST')(self._setup_post)
    
    @error_decorator
    def _setup_get(self, action):
        """Handle GET requests for setup information."""
        if action == 'status':
            return self._get_setup_status()
        elif action == 'system-info':
            return self._get_system_info()
        elif action == 'validate-folders':
            return self._validate_folders()
        elif action == 'current-config':
            return self._get_current_config()
        else:
            bottle.abort(404, f"Setup action '{action}' not found")
    
    @error_decorator
    def _setup_post(self, action):
        """Handle POST requests for setup actions."""
        if action == 'basic-info':
            return self._setup_basic_info()
        elif action == 'admin-user':
            return self._setup_admin_user()
        elif action == 'add-user':
            return self._setup_add_user()
        elif action == 'add-incubator':
            return self._setup_add_incubator()
        elif action == 'notifications':
            return self._setup_notifications()
        elif action == 'test-notifications':
            return self._test_notifications()
        elif action == 'tunnel':
            return self._setup_tunnel()
        elif action == 'complete':
            return self._complete_setup()
        elif action == 'reset':
            return self._reset_setup()
        elif action == 'current-config':
            return self._get_current_config()
        else:
            bottle.abort(404, f"Setup action '{action}' not found")
    
    def _get_setup_status(self):
        """Get current setup status and progress."""
        return self.config.get_setup_status()
    
    def _get_system_info(self):
        """Get system information for setup validation."""
        import socket
        import psutil
        
        # Get hostname
        try:
            hostname = socket.gethostname()
            fqdn = socket.getfqdn()
        except Exception:
            hostname = "unknown"
            fqdn = "unknown"
        
        # Get disk usage for important paths
        disk_info = {}
        for path_name, path_config in self.config.content.get('folders', {}).items():
            try:
                path = path_config.get('path', '')
                if path and os.path.exists(path):
                    usage = psutil.disk_usage(path)
                    disk_info[path_name] = {
                        'path': path,
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': (usage.used / usage.total) * 100
                    }
            except Exception as e:
                self.logger.warning(f"Error getting disk usage for {path_name}: {e}")
        
        # Get memory info
        try:
            memory = psutil.virtual_memory()
            memory_info = {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent,
                'used': memory.used
            }
        except Exception:
            memory_info = {}
        
        return {
            'hostname': hostname,
            'fqdn': fqdn,
            'disk_usage': disk_info,
            'memory': memory_info,
            'python_version': os.sys.version,
            'current_user': os.getenv('USER', 'unknown')
        }
    
    def _validate_folders(self):
        """Validate folder paths and permissions."""
        data = self.get_request_json()
        folders = data.get('folders', {})
        
        validation_results = {}
        
        for folder_name, folder_path in folders.items():
            result = {
                'path': folder_path,
                'valid': False,
                'exists': False,
                'writable': False,
                'readable': False,
                'errors': []
            }
            
            try:
                # Check if path exists
                path = Path(folder_path)
                if path.exists():
                    result['exists'] = True
                    
                    # Check if it's a directory
                    if not path.is_dir():
                        result['errors'].append("Path exists but is not a directory")
                    else:
                        # Check permissions
                        result['readable'] = os.access(folder_path, os.R_OK)
                        result['writable'] = os.access(folder_path, os.W_OK)
                        
                        if not result['readable']:
                            result['errors'].append("Directory is not readable")
                        if not result['writable']:
                            result['errors'].append("Directory is not writable")
                        
                        if result['readable'] and result['writable']:
                            result['valid'] = True
                else:
                    # Try to create the directory
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        result['exists'] = True
                        result['readable'] = True
                        result['writable'] = True
                        result['valid'] = True
                    except Exception as e:
                        result['errors'].append(f"Could not create directory: {e}")
            
            except Exception as e:
                result['errors'].append(f"Error validating path: {e}")
            
            validation_results[folder_name] = result
        
        return {'validation_results': validation_results}
    
    def _setup_basic_info(self):
        """Configure basic system information."""
        data = self.get_request_json()
        
        # Update folder paths if provided
        folders = data.get('folders', {})
        if folders:
            current_folders = self.config.content.get('folders', {})
            
            for folder_name, folder_path in folders.items():
                if folder_name in current_folders:
                    # Create directory if it doesn't exist
                    try:
                        Path(folder_path).mkdir(parents=True, exist_ok=True)
                        current_folders[folder_name]['path'] = folder_path
                    except Exception as e:
                        self.logger.error(f"Error creating folder {folder_path}: {e}")
                        return {'result': 'error', 'message': f"Could not create folder {folder_path}: {e}"}
            
            # Update configuration
            self.config._settings['folders'] = current_folders
            self.config.save()
        
        # Mark step as completed
        self.config.mark_setup_step_completed('basic_info')
        
        return {'result': 'success', 'message': 'Basic configuration updated successfully'}
    
    def _setup_admin_user(self):
        """Create or replace admin user."""
        data = self.get_request_json()
        
        try:
            db = ExperimentalDB()
            
            # Get required user data
            user_data = {
                'username': data.get('username', '').strip(),
                'fullname': data.get('fullname', '').strip(),
                'email': data.get('email', '').strip(),
                'pin': data.get('pin', '').strip(),
                'telephone': data.get('telephone', '').strip(),
                'labname': data.get('labname', '').strip(),
                'active': 1,
                'isadmin': 1
            }
            
            # Validate required fields
            if not user_data['username']:
                return {'result': 'error', 'message': 'Username is required'}
            if not user_data['email']:
                return {'result': 'error', 'message': 'Email is required'}
            
            # Check if user already exists
            existing_user = db.getUserByName(user_data['username'])
            
            if existing_user:
                # Update existing user
                updates_data = {k: v for k, v in user_data.items() if k != 'username'}
                self.logger.info(f"Updating user {user_data['username']} with data: {updates_data}")
                result = db.updateUser(username=user_data['username'], **updates_data)
                self.logger.info(f"Update result: {result}")
                
                if result >= 0:
                    self.config.mark_setup_step_completed('admin_user')
                    return {
                        'result': 'success', 
                        'message': f'Admin user {user_data["username"]} updated successfully',
                        'user_id': existing_user['id']
                    }
                else:
                    return {'result': 'error', 'message': 'Failed to update admin user'}
            else:
                # Check if replacing existing admin user
                replace_user = data.get('replace_user')
                if replace_user:
                    # Deactivate the existing user
                    existing_replace_user = db.getUserByName(replace_user)
                    if existing_replace_user:
                        db.deactivateUser(username=replace_user)
                        self.logger.info(f"Deactivated existing admin user: {replace_user}")
                
                # Add new admin user
                result = db.addUser(**user_data)
                
                if result > 0:
                    self.config.mark_setup_step_completed('admin_user')
                    return {
                        'result': 'success', 
                        'message': f'Admin user {user_data["username"]} created successfully',
                        'user_id': result
                    }
                else:
                    return {'result': 'error', 'message': 'Failed to create admin user'}
                
        except Exception as e:
            self.logger.error(f"Error creating admin user: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _setup_add_user(self):
        """Add additional user."""
        data = self.get_request_json()
        
        try:
            db = ExperimentalDB()
            
            # Get user data
            user_data = {
                'username': data.get('username', '').strip(),
                'fullname': data.get('fullname', '').strip(),
                'email': data.get('email', '').strip(),
                'pin': data.get('pin', '').strip(),
                'telephone': data.get('telephone', '').strip(),
                'labname': data.get('labname', '').strip(),
                'active': 1,
                'isadmin': 1 if data.get('isadmin', False) else 0
            }
            
            # Validate required fields
            if not user_data['username']:
                return {'result': 'error', 'message': 'Username is required'}
            if not user_data['email']:
                return {'result': 'error', 'message': 'Email is required'}
            
            # Add user
            result = db.addUser(**user_data)
            
            if result > 0:
                return {
                    'result': 'success', 
                    'message': f'User {user_data["username"]} created successfully',
                    'user_id': result
                }
            else:
                return {'result': 'error', 'message': 'Failed to create user'}
                
        except Exception as e:
            self.logger.error(f"Error creating user: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _setup_add_incubator(self):
        """Add incubator."""
        data = self.get_request_json()
        
        try:
            db = ExperimentalDB()
            
            # Get incubator data
            incubator_data = {
                'name': data.get('name', '').strip(),
                'location': data.get('location', '').strip(),
                'owner': data.get('owner', '').strip(),
                'description': data.get('description', '').strip(),
                'active': 1
            }
            
            # Validate required fields
            if not incubator_data['name']:
                return {'result': 'error', 'message': 'Incubator name is required'}
            
            # Add incubator
            result = db.addIncubator(**incubator_data)
            
            if result > 0:
                return {
                    'result': 'success', 
                    'message': f'Incubator {incubator_data["name"]} created successfully',
                    'incubator_id': result
                }
            else:
                return {'result': 'error', 'message': 'Failed to create incubator'}
                
        except Exception as e:
            self.logger.error(f"Error creating incubator: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _setup_notifications(self):
        """Configure notification settings."""
        data = self.get_request_json()
        
        try:
            # Update SMTP settings (stored directly under 'smtp' key)
            smtp_config = data.get('smtp', {})
            if smtp_config:
                current_smtp = self.config._settings.get('smtp', {})
                
                # Handle masked password - preserve existing password if user didn't change it
                submitted_password = smtp_config.get('password', '')
                if submitted_password == '***CONFIGURED***' and current_smtp.get('password'):
                    # User didn't change the masked password, preserve existing one
                    actual_password = current_smtp.get('password')
                else:
                    # User provided a new password (or cleared it)
                    actual_password = submitted_password
                
                smtp_settings = {
                    'enabled': smtp_config.get('enabled', False),
                    'host': smtp_config.get('host', 'localhost'),
                    'port': int(smtp_config.get('port', 587)),
                    'use_tls': smtp_config.get('use_tls', True),
                    'username': smtp_config.get('username', ''),
                    'password': actual_password,
                    'from_email': smtp_config.get('from_email', 'ethoscope@localhost')
                }
                
                # Store directly under 'smtp' key (matching configuration.py structure)
                self.config._settings['smtp'] = smtp_settings
            
            # Update Mattermost settings (stored directly under 'mattermost' key)
            mattermost_config = data.get('mattermost', {})
            if mattermost_config:
                current_mattermost = self.config._settings.get('mattermost', {})
                
                # Handle masked token - preserve existing token if user didn't change it
                submitted_token = mattermost_config.get('bot_token', '')
                if submitted_token == '***CONFIGURED***' and current_mattermost.get('bot_token'):
                    # User didn't change the masked token, preserve existing one
                    actual_token = current_mattermost.get('bot_token')
                else:
                    # User provided a new token (or cleared it)
                    actual_token = submitted_token
                
                mattermost_settings = {
                    'enabled': mattermost_config.get('enabled', False),
                    'server_url': mattermost_config.get('server_url', ''),
                    'bot_token': actual_token,
                    'channel_id': mattermost_config.get('channel_id', '')
                }
                
                # Store directly under 'mattermost' key (matching configuration.py structure)
                self.config._settings['mattermost'] = mattermost_settings
            
            # Save configuration
            self.config.save()
            self.config.mark_setup_step_completed('notifications')
            
            return {'result': 'success', 'message': 'Notification settings updated successfully'}
            
        except Exception as e:
            self.logger.error(f"Error updating notification settings: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _setup_tunnel(self):
        """Configure tunnel settings."""
        data = self.get_request_json()
        
        try:
            # Get current token to preserve it if masked value is sent
            current_tunnel_config = self.config._settings.get('tunnel', {})
            current_token = current_tunnel_config.get('token', '')
            
            # Handle masked token - preserve existing token if user didn't change it
            submitted_token = data.get('token', '')
            if submitted_token == '***CONFIGURED***' and current_token:
                # User didn't change the masked token, preserve existing one
                actual_token = current_token
            else:
                # User provided a new token (or cleared it)
                actual_token = submitted_token
            
            # Update tunnel configuration with dual mode support
            tunnel_config = {
                'enabled': data.get('enabled', False),
                'mode': data.get('mode', 'custom'),  # 'custom' (free) or 'ethoscope_net' (paid)
                'token': actual_token,
                'node_id': data.get('node_id', 'auto'),
                'domain': data.get('domain', 'ethoscope.net'),
                'custom_domain': data.get('custom_domain', '')  # For custom domain mode
            }
            
            # Validate configuration based on mode
            if tunnel_config['enabled']:
                if not tunnel_config['token']:
                    return {'result': 'error', 'message': 'Tunnel token is required when tunnel is enabled'}
                
                if tunnel_config['mode'] == 'custom' and not tunnel_config['custom_domain']:
                    return {'result': 'error', 'message': 'Custom domain is required for free mode'}
            
            # Update configuration using the existing method
            self.config.update_tunnel_config(tunnel_config)
            
            # Update the tunnel environment file if server is available
            if hasattr(self, 'server') and self.server:
                self.server._update_tunnel_environment()
            
            # Mark this setup step as completed
            self.config.mark_setup_step_completed('tunnel')
            
            return {'result': 'success', 'message': 'Tunnel settings updated successfully'}
            
        except Exception as e:
            self.logger.error(f"Error updating tunnel settings: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _test_notifications(self):
        """Test notification configuration."""
        data = self.get_request_json()
        test_type = data.get('type', 'smtp')
        
        try:
            if test_type == 'smtp':
                return self._test_smtp(data.get('config', {}))
            elif test_type == 'mattermost':
                return self._test_mattermost(data.get('config', {}))
            else:
                return {'result': 'error', 'message': f'Unknown test type: {test_type}'}
                
        except Exception as e:
            self.logger.error(f"Error testing {test_type} configuration: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _test_smtp(self, smtp_config):
        """Test SMTP configuration by sending a test email."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        try:
            # Get configuration
            host = smtp_config.get('host', 'localhost')
            port = int(smtp_config.get('port', 587))
            use_tls = smtp_config.get('use_tls', True)
            username = smtp_config.get('username', '')
            password = smtp_config.get('password', '')
            from_email = smtp_config.get('from_email', 'ethoscope@localhost')
            test_email = smtp_config.get('test_email', from_email)
            
            # Create test message
            msg = MIMEMultipart()
            msg['From'] = from_email
            msg['To'] = test_email
            msg['Subject'] = "Ethoscope Node - SMTP Configuration Test"
            
            body = """
This is a test email sent from the Ethoscope Node installation wizard.
If you receive this message, your SMTP configuration is working correctly.

Best regards,
Ethoscope Node Setup Wizard
"""
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect and send email with timeout
            server = None
            try:
                # Try SMTP_SSL first for port 465, then regular SMTP
                if port == 465:
                    server = smtplib.SMTP_SSL(host, port, timeout=10)
                    server.ehlo()  # Identify ourselves
                else:
                    server = smtplib.SMTP(host, port, timeout=10)
                    server.ehlo()  # Identify ourselves
                    
                    if use_tls:
                        server.starttls()
                        server.ehlo()  # Re-identify after STARTTLS
                
                if username and password:
                    server.login(username, password)
                
                server.send_message(msg)
                
            finally:
                if server:
                    try:
                        server.quit()
                    except:
                        pass  # Ignore quit errors
            
            return {
                'result': 'success', 
                'message': f'Test email sent successfully to {test_email}'
            }
            
        except Exception as e:
            return {
                'result': 'error', 
                'message': f'SMTP test failed: {str(e)}'
            }
    
    def _test_mattermost(self, mattermost_config):
        """Test Mattermost configuration by sending a test message."""
        import requests
        
        try:
            # Get configuration
            server_url = mattermost_config.get('server_url', '').rstrip('/')
            bot_token = mattermost_config.get('bot_token', '')
            channel_id = mattermost_config.get('channel_id', '')
            
            if not all([server_url, bot_token, channel_id]):
                return {
                    'result': 'error',
                    'message': 'Server URL, bot token, and channel ID are required'
                }
            
            # Prepare test message
            message = {
                'channel_id': channel_id,
                'message': 'This is a test message from the Ethoscope Node installation wizard. If you see this, your Mattermost configuration is working correctly!'
            }
            
            headers = {
                'Authorization': f'Bearer {bot_token}',
                'Content-Type': 'application/json'
            }
            
            # Send test message
            response = requests.post(
                f'{server_url}/api/v4/posts',
                json=message,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 201:
                return {
                    'result': 'success',
                    'message': 'Test message sent successfully to Mattermost'
                }
            else:
                return {
                    'result': 'error',
                    'message': f'Mattermost test failed: HTTP {response.status_code} - {response.text}'
                }
                
        except Exception as e:
            return {
                'result': 'error',
                'message': f'Mattermost test failed: {str(e)}'
            }
    
    def _complete_setup(self):
        """Complete the setup process."""
        try:
            # Mark setup as completed
            self.config.complete_setup()
            
            return {
                'result': 'success',
                'message': 'Installation wizard completed successfully',
                'setup_completed': True
            }
            
        except Exception as e:
            self.logger.error(f"Error completing setup: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _reset_setup(self):
        """Reset setup status (for testing or re-setup)."""
        try:
            # Reset setup status
            self.config.reset_setup()
            
            return {
                'result': 'success',
                'message': 'Setup status reset successfully',
                'setup_completed': False
            }
            
        except Exception as e:
            self.logger.error(f"Error resetting setup: {e}")
            return {'result': 'error', 'message': str(e)}
    
    def _get_current_config(self):
        """Get current system configuration for reconfiguration mode."""
        try:
            from ethoscope_node.utils.etho_db import ExperimentalDB
            
            config_data = {
                'folders': {},
                'admin_user': None,
                'users': [],
                'incubators': [],
                'tunnel': {
                    'enabled': False,
                    'mode': 'custom',
                    'token': '',  # Will be populated with masked value if configured
                    'node_id': 'auto',
                    'domain': 'ethoscope.net',
                    'custom_domain': ''
                },
                'notifications': {
                    'smtp': {
                        'enabled': False,
                        'host': 'localhost',
                        'port': 587,
                        'use_tls': True,
                        'username': '',
                        'password': '',
                        'from_email': 'ethoscope@localhost'
                    },
                    'mattermost': {
                        'enabled': False,
                        'server_url': '',
                        'bot_token': '',
                        'channel_id': ''
                    }
                }
            }
            
            # Get current folder configuration
            if hasattr(self.config, '_settings') and 'folders' in self.config._settings:
                folders_config = self.config._settings['folders']
                for folder_name, folder_info in folders_config.items():
                    if isinstance(folder_info, dict) and 'path' in folder_info:
                        config_data['folders'][folder_name] = folder_info['path']
            
            # Get admin user information
            try:
                db = ExperimentalDB()
                all_users = db.getAllUsers(active_only=False, asdict=True)
                for username, user_info in all_users.items():
                    if user_info.get('isadmin') == 1:
                        config_data['admin_user'] = {
                            'username': username,
                            'fullname': user_info.get('fullname', ''),
                            'email': user_info.get('email', ''),
                            'pin': user_info.get('pin', ''),
                            'telephone': user_info.get('telephone', ''),
                            'labname': user_info.get('labname', '')
                        }
                        break  # Use first admin user found
            except Exception as e:
                self.logger.warning(f"Could not load admin user info: {e}")
            
            # Get tunnel settings
            try:
                tunnel_config = self.config._settings.get('tunnel', {})
                if tunnel_config:
                    # Show masked token if one exists, empty if none configured
                    existing_token = tunnel_config.get('token', '')
                    masked_token = '***CONFIGURED***' if existing_token else ''
                    
                    config_data['tunnel'].update({
                        'enabled': tunnel_config.get('enabled', False),
                        'mode': tunnel_config.get('mode', 'custom'),
                        'token': masked_token,  # Show masked token for UX, empty if none exists
                        'node_id': tunnel_config.get('node_id', 'auto'),
                        'domain': tunnel_config.get('domain', 'ethoscope.net'),
                        'custom_domain': tunnel_config.get('custom_domain', '')
                    })
            except Exception as e:
                self.logger.warning(f"Could not load tunnel settings: {e}")
            
            # Get notification settings (from correct configuration paths)
            try:
                # SMTP settings - stored directly under 'smtp' key
                smtp_config = self.config._settings.get('smtp', {})
                if smtp_config:
                    # Show masked password if one exists, empty if none configured
                    existing_password = smtp_config.get('password', '')
                    masked_password = '***CONFIGURED***' if existing_password else ''
                    
                    config_data['notifications']['smtp'].update({
                        'enabled': smtp_config.get('enabled', False),
                        'host': smtp_config.get('host', 'localhost'),
                        'port': smtp_config.get('port', 587),
                        'use_tls': smtp_config.get('use_tls', True),
                        'username': smtp_config.get('username', ''),
                        'password': masked_password,  # Show masked password for UX, empty if none exists
                        'from_email': smtp_config.get('from_email', 'ethoscope@localhost')
                    })
                
                # Mattermost settings - stored directly under 'mattermost' key
                mattermost_config = self.config._settings.get('mattermost', {})
                if mattermost_config:
                    # Show masked token if one exists, empty if none configured
                    existing_token = mattermost_config.get('bot_token', '')
                    masked_token = '***CONFIGURED***' if existing_token else ''
                    
                    config_data['notifications']['mattermost'].update({
                        'enabled': mattermost_config.get('enabled', False),
                        'server_url': mattermost_config.get('server_url', ''),
                        'bot_token': masked_token,  # Show masked token for UX, empty if none exists
                        'channel_id': mattermost_config.get('channel_id', '')
                    })
            except Exception as e:
                self.logger.warning(f"Could not load notification settings: {e}")
            
            # Get existing users (excluding admin user already loaded)
            try:
                db = ExperimentalDB()
                all_users = db.getAllUsers(active_only=False, asdict=True)
                for username, user_info in all_users.items():
                    # Skip the admin user as it's already loaded separately
                    if user_info.get('isadmin') != 1:
                        config_data['users'].append({
                            'username': username,
                            'fullname': user_info.get('fullname', ''),
                            'email': user_info.get('email', ''),
                            'pin': user_info.get('pin', ''),
                            'telephone': user_info.get('telephone', ''),
                            'labname': user_info.get('labname', ''),
                            'isadmin': bool(user_info.get('isadmin', 0))
                        })
            except Exception as e:
                self.logger.warning(f"Could not load existing users: {e}")
            
            # Get existing incubators
            try:
                db = ExperimentalDB()
                all_incubators = db.get_all_incubators()
                for incubator in all_incubators:
                    config_data['incubators'].append({
                        'name': incubator.get('name', ''),
                        'description': incubator.get('description', ''),
                        'location': incubator.get('location', ''),
                        'temperature_range_min': incubator.get('temperature_range_min', 20),
                        'temperature_range_max': incubator.get('temperature_range_max', 30),
                        'humidity_min': incubator.get('humidity_min', 40),
                        'humidity_max': incubator.get('humidity_max', 70)
                    })
            except Exception as e:
                self.logger.warning(f"Could not load existing incubators: {e}")
            
            return {
                'result': 'success',
                'config': config_data
            }
            
        except Exception as e:
            self.logger.error(f"Error loading current configuration: {e}")
            return {'result': 'error', 'message': str(e)}