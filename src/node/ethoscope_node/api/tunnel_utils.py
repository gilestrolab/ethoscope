"""
Tunnel Utilities API

Provides utilities for tunnel configuration and URL management.
"""

import os
import logging
from typing import Optional, Dict, Any
from .base import BaseAPI, error_decorator


class TunnelUtils(BaseAPI):
    """Tunnel utilities for managing tunnel configuration and URLs."""
    
    def __init__(self, server_instance):
        """Initialize tunnel utilities."""
        super().__init__(server_instance)
    
    def register_routes(self):
        """Register tunnel-related routes."""
        self.app.route('/tunnel/status', method='GET')(self._get_tunnel_status_route)
        self.app.route('/tunnel/toggle', method='POST')(self._toggle_tunnel_route)
        self.app.route('/tunnel/config', method='POST')(self._update_tunnel_config_route)
    
    def get_tunnel_update_url(self) -> str:
        """
        Get the UPDATE_SERVICE_URL based on tunnel configuration.
        
        Returns:
            UPDATE_SERVICE_URL based on tunnel settings or default localhost
        """
        try:
            if not self.config:
                return "http://localhost:8888"
                
            tunnel_config = self.config.get_tunnel_config()
            
            # If tunnel is enabled and has a valid domain
            if tunnel_config.get('enabled', False) and tunnel_config.get('full_domain'):
                return f"http://{tunnel_config['full_domain']}:8888"
            else:
                # Fallback to localhost
                return "http://localhost:8888"
                
        except Exception as e:
            self.logger.warning(f"Error constructing tunnel update URL: {e}")
            return "http://localhost:8888"
    
    @error_decorator
    def update_tunnel_environment(self) -> None:
        """
        Update tunnel environment file from configuration.
        
        Creates /etc/ethoscope/tunnel.env with tunnel token and updates
        the UPDATE_SERVICE_URL in configuration based on tunnel settings.
        """
        try:
            if not self.config:
                self.logger.warning("No configuration available for tunnel environment update")
                return
                
            tunnel_config = self.config.get_tunnel_config()
            tunnel_token = tunnel_config.get('token', '')
            
            if tunnel_token:
                env_file_path = "/etc/ethoscope/tunnel.env"
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(env_file_path), exist_ok=True)
                
                # Write environment file
                with open(env_file_path, 'w') as f:
                    f.write(f"TUNNEL_TOKEN={tunnel_token}\\n")
                
                # Set secure permissions (readable by root only)
                os.chmod(env_file_path, 0o600)
                
                # Update UPDATE_SERVICE_URL in configuration based on tunnel settings
                update_url = self.get_tunnel_update_url()
                self.config.update_custom("UPDATE_SERVICE_URL", update_url)
                
                self.logger.info(f"Updated tunnel environment file and UPDATE_SERVICE_URL to {update_url}")
            else:
                self.logger.debug("No tunnel token configured, skipping environment file update")
                
        except Exception as e:
            self.logger.warning(f"Failed to update tunnel environment file: {e}")
            raise
    
    def get_hostname_aware_redirect_url(self, current_host: str, fallback_url: str) -> str:
        """
        Get redirect URL based on current hostname with local/external logic.
        
        Args:
            current_host: Current request hostname (from HTTP_HOST header)
            fallback_url: Fallback URL to use for external access
            
        Returns:
            Appropriate redirect URL based on hostname
        """
        try:
            # Extract hostname without port
            hostname = current_host.split(':')[0] if ':' in current_host else current_host
            hostname = hostname.lower()
            
            # Check if current hostname is localhost, node, or 127.0.0.1
            if hostname in ['localhost', 'node', '127.0.0.1']:
                # Use local URL for localhost/node access
                return f"http://{hostname}:8888"
            else:
                # Use configured external URL for other hostnames
                return fallback_url
                
        except Exception as e:
            self.logger.warning(f"Error determining hostname-aware redirect URL: {e}")
            return fallback_url
    
    # API Route Handlers
    
    @error_decorator
    def _get_tunnel_status_route(self):
        """API route to get tunnel status."""
        return self.json_response(self.get_tunnel_status())
    
    @error_decorator
    def _toggle_tunnel_route(self):
        """API route to toggle tunnel on/off."""
        data = self.get_request_json()
        enabled = data.get('enabled', False)
        result = self.toggle_tunnel(enabled)
        return self.json_response(result)
    
    @error_decorator
    def _update_tunnel_config_route(self):
        """API route to update tunnel configuration."""
        data = self.get_request_json()
        config_data = data.get('config', {})
        result = self.update_tunnel_config(config_data)
        return self.json_response(result)
    
    # Core Tunnel Management Functions
    
    def get_tunnel_status(self) -> Dict[str, Any]:
        """Get current tunnel configuration and status."""
        tunnel_config = self.config.get_tunnel_config()
        
        # Check if tunnel service is running
        try:
            systemctl = self.server.systemctl
            with os.popen(f"{systemctl} is-active ethoscope_tunnel") as result:
                service_status = result.read().strip()
                
            tunnel_config['service_running'] = (service_status == 'active')
            tunnel_config['service_status'] = service_status
            
            # Get service info if active
            if service_status == 'active':
                with os.popen(f"{systemctl} status ethoscope_tunnel --no-pager -l") as result:
                    status_output = result.read()
                tunnel_config['service_info'] = status_output
            
        except Exception as e:
            self.logger.warning(f"Failed to check tunnel service status: {e}")
            tunnel_config['service_running'] = False
            tunnel_config['service_status'] = 'Unknown'
        
        return tunnel_config
    
    def toggle_tunnel(self, enabled: bool) -> Dict[str, Any]:
        """Enable or disable the tunnel."""
        self.logger.info(f"User requested tunnel {'enable' if enabled else 'disable'}")
        
        # Update configuration
        self.config.update_tunnel_config({
            'enabled': enabled,
            'status': 'connecting' if enabled else 'disconnected'
        })
        
        try:
            tunnel_config = self.config.get_tunnel_config()
            tunnel_token = tunnel_config.get('token', '')
            
            if not tunnel_token and enabled:
                return {'success': False, 'error': 'Tunnel token not configured', 'enabled': False}
            
            # Update tunnel environment file from configuration
            if enabled:
                self.update_tunnel_environment()
            
            systemctl = self.server.systemctl
            
            if enabled:
                # Start tunnel service
                cmd = f"{systemctl} start ethoscope_tunnel"
                self.logger.info(f"Starting tunnel service: {cmd}")
                
                with os.popen(cmd) as result:
                    output = result.read()
                    
                # Update status to connected if successful
                self.config.update_tunnel_config({'status': 'connected'})
                
            else:
                # Stop tunnel service
                cmd = f"{systemctl} stop ethoscope_tunnel"
                self.logger.info(f"Stopping tunnel service: {cmd}")
                
                with os.popen(cmd) as result:
                    output = result.read()
                    
                # Update status to disconnected
                self.config.update_tunnel_config({'status': 'disconnected'})
            
            return {'success': True, 'message': output, 'enabled': enabled}
            
        except Exception as e:
            error_msg = f"Failed to {'start' if enabled else 'stop'} tunnel: {e}"
            self.logger.error(error_msg)
            
            # Update status to error
            self.config.update_tunnel_config({'status': 'error'})
            
            return {'success': False, 'error': error_msg, 'enabled': False}
    
    def update_tunnel_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update tunnel configuration settings."""
        self.logger.info(f"Updating tunnel configuration: {list(config_data.keys())}")
        
        try:
            # Update configuration
            updated_config = self.config.update_tunnel_config(config_data)
            
            # If tunnel is enabled and token was updated, restart service
            if updated_config.get('enabled') and 'token' in config_data:
                self.logger.info("Token updated, restarting tunnel service")
                
                # Update environment file with new token from configuration
                self.update_tunnel_environment()
                
                # Restart tunnel service to pick up new token
                systemctl = self.server.systemctl
                cmd = f"{systemctl} restart ethoscope_tunnel"
                
                with os.popen(cmd) as result:
                    output = result.read()
                    
                self.logger.info(f"Tunnel service restarted: {output}")
            
            return {'success': True, 'config': updated_config}
            
        except Exception as e:
            error_msg = f"Failed to update tunnel configuration: {e}"
            self.logger.error(error_msg)
            return {'success': False, 'error': error_msg}