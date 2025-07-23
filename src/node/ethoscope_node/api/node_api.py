"""
Node API Module

Handles node system management including information, daemon control,
configuration management, and system actions.
"""

import bottle
import os
import datetime
import subprocess
import netifaces
from .base import BaseAPI, error_decorator


# System daemons configuration
SYSTEM_DAEMONS = {
    "ethoscope_backup_mysql": {
        'description': 'The service that collects data from the ethoscope mariadb and syncs them with the node.',
        'available_on_docker': True
    },
    "ethoscope_backup_video": {
        'description': 'The service that collects videos in h264 chunks from the ethoscopes and syncs them with the node',
        'available_on_docker': True
    },
    "ethoscope_backup_unified": {
        'description': 'The service that collects videos and SQLite dbs from the ethoscopes and syncs them with the node',
        'available_on_docker': True
    },
    "ethoscope_backup_sqlite": {
        'description': 'The service that collects SQLite db from the ethoscopes and syncs them with the node',
        'available_on_docker': True
    },
    "ethoscope_update_node": {
        'description': 'The service used to update the nodes and the ethoscopes.',
        'available_on_docker': True
    },
    "git-daemon.socket": {
        'description': 'The GIT server that handles git updates for the node and ethoscopes.',
        'available_on_docker': False
    },
    "ntpd": {
        'description': 'The NTPd service is syncing time with the ethoscopes.',
        'available_on_docker': False
    },
    "sshd": {
        'description': 'The SSH daemon allows power users to access the node terminal from remote.',
        'available_on_docker': False
    },
    "vsftpd": {
        'description': 'The FTP server on the node, used to access the local ethoscope data',
        'available_on_docker': False
    },
    "ethoscope_virtuascope": {
        'description': 'A virtual ethoscope running on the node. Useful for offline tracking',
        'available_on_docker': False
    },
    "ethoscope_tunnel": {
        'description': 'Cloudflare tunnel service for remote access to this node via the internet',
        'available_on_docker': False
    }
}


class NodeAPI(BaseAPI):
    """API endpoints for node system management."""
    
    def register_routes(self):
        """Register node-related routes."""
        self.app.route('/node/<req>', method='GET')(self._node_info)
        self.app.route('/node-actions', method='POST')(self._node_actions)
        self.app.route('/node/config', method='GET')(self._get_node_config)
    
    @error_decorator
    def _node_info(self, req):
        """Handle various node information requests."""
        if req == 'info':
            return self._get_node_system_info()
        elif req == 'time':
            return {'time': datetime.datetime.now().isoformat()}
        elif req == 'timestamp':
            return {'timestamp': datetime.datetime.now().timestamp()}
        elif req == 'log':
            with os.popen("journalctl -u ethoscope_node -rb") as log:
                return {'log': log.read()}
        elif req == 'daemons':
            return self._get_daemon_status()
        elif req == 'folders':
            return self.config.content['folders']
        elif req == 'users':
            # Get users from database instead of configuration
            try:
                from ethoscope_node.utils.etho_db import ExperimentalDB
                db = ExperimentalDB()
                return db.getAllUsers(active_only=False, asdict=True)
            except Exception as e:
                self.logger.error(f"Error getting users from database: {e}")
                return {}
        elif req == 'incubators':
            # Get incubators from database instead of configuration
            try:
                from ethoscope_node.utils.etho_db import ExperimentalDB
                db = ExperimentalDB()
                return db.getAllIncubators(active_only=False, asdict=True)
            except Exception as e:
                self.logger.error(f"Error getting incubators from database: {e}")
                return {}
        elif req == 'sensors':
            return self.sensor_scanner.get_all_devices_info() if self.sensor_scanner else {}
        elif req == 'commands':
            return self.config.content['commands']
        elif req == 'tunnel':
            return self._get_tunnel_status()
        else:
            raise NotImplementedError(f"Unknown node request: {req}")
    
    @error_decorator
    def _get_node_config(self):
        """Batched endpoint that returns all node configuration data in one request."""
        # Get users from database
        try:
            from ethoscope_node.utils.etho_db import ExperimentalDB
            db = ExperimentalDB()
            users_data = db.getAllUsers(active_only=False, asdict=True)
        except Exception as e:
            self.logger.error(f"Error getting users from database: {e}")
            users_data = {}
        
        return {
            'users': users_data,
            'incubators': self.config.content['incubators'],
            'sensors': self.sensor_scanner.get_all_devices_info() if self.sensor_scanner else {},
            'timestamp': datetime.datetime.now().timestamp()
        }
    
    def _get_node_system_info(self):
        """Get comprehensive node system information."""
        try:
            # Disk usage
            with os.popen(f'df {self.results_dir} -h') as df:
                disk_free = df.read()
            disk_usage = disk_free.split("\\n")[1].split()
        except Exception:
            disk_usage = []
        
        # Results directory status
        rdir = self.results_dir if os.path.exists(self.results_dir) else f"{self.results_dir} is not available"
        
        # Network interfaces
        cards = {}
        ips = []
        
        try:
            adapters_list = [
                [i, netifaces.ifaddresses(i)[17][0]['addr'], netifaces.ifaddresses(i)[2][0]['addr']]
                for i in netifaces.interfaces()
                if 17 in netifaces.ifaddresses(i) and 2 in netifaces.ifaddresses(i)
                and netifaces.ifaddresses(i)[17][0]['addr'] != '00:00:00:00:00:00'
            ]
            
            for adapter_name, mac, ip in adapters_list:
                cards[adapter_name] = {'MAC': mac, 'IP': ip}
                ips.append(ip)
        except Exception:
            pass
        
        # Git information
        try:
            with os.popen('git rev-parse --abbrev-ref HEAD') as df:
                git_branch = df.read().strip() or "Not detected"
            
            with os.popen('git status -s -uno') as df:
                needs_update = df.read() != ""
        except Exception:
            git_branch = "Not detected"
            needs_update = False
        
        # Service status
        try:
            systemctl = self.server.systemctl
            with os.popen(f'{systemctl} status ethoscope_node.service') as df:
                active_since = df.read().split("\\n")[2]
        except Exception:
            active_since = "N/A. Probably not running through systemd"
        
        return {
            'active_since': active_since,
            'disk_usage': disk_usage,
            'RDIR': rdir,
            'IPs': ips,
            'CARDS': cards,
            'GIT_BRANCH': git_branch,
            'NEEDS_UPDATE': needs_update
        }
    
    def _get_daemon_status(self):
        """Get status of system daemons."""
        daemons = SYSTEM_DAEMONS.copy()
        systemctl = self.server.systemctl
        is_dockerized = self.server.is_dockerized
        
        for daemon_name in daemons.keys():
            try:
                with os.popen(f"{systemctl} is-active {daemon_name}") as df:
                    is_active = df.read().strip()
                
                is_not_available_on_docker = not daemons[daemon_name]["available_on_docker"]
                
                daemons[daemon_name].update({
                    'active': is_active,
                    'not_available': (is_dockerized and is_not_available_on_docker)
                })
            except Exception:
                daemons[daemon_name].update({
                    'active': 'unknown',
                    'not_available': False
                })
        
        return daemons
    
    @error_decorator
    def _node_actions(self):
        """Handle various node actions."""
        action = self.get_request_json()
        action_type = action.get('action')
        
        if action_type == 'restart':
            self.logger.info('User requested a service restart.')
            systemctl = self.server.systemctl
            with os.popen(f"sleep 1; {systemctl} restart ethoscope_node.service") as po:
                return po.read()
        
        elif action_type == 'close':
            self.server._shutdown()
        
        elif action_type == 'adduser':
            return self.config.add_user(action['userdata'])
        
        elif action_type == 'addincubator':
            return self.config.add_incubator(action['incubatordata'])
        
        elif action_type == 'addsensor':
            return self.config.add_sensor(action['sensordata'])
        
        elif action_type == 'updatefolders':
            return self._update_folders(action['folders'])
        
        elif action_type == 'exec_cmd':
            return self._execute_command(action['cmd_name'])
        
        elif action_type == 'toggledaemon':
            return self._toggle_daemon(action['daemon_name'], action['status'])
        
        elif action_type == 'toggle_tunnel':
            return self._toggle_tunnel(action.get('enabled', False))
        
        elif action_type == 'update_tunnel_config':
            return self._update_tunnel_config(action.get('config', {}))
        
        else:
            raise NotImplementedError(f"Unknown action: {action_type}")
    
    def _update_folders(self, folders):
        """Update folder configuration."""
        for folder in folders.keys():
            if os.path.exists(folders[folder]['path']):
                self.config.content['folders'][folder]['path'] = folders[folder]['path']
        
        self.config.save()
        return self.config.content['folders']
    
    def _execute_command(self, cmd_name):
        """Execute a configured command."""
        cmd = self.config.content['commands'][cmd_name]['command']
        self.logger.info(f"Executing command: {cmd}")
        
        try:
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, shell=True) as po:
                for line in po.stderr:
                    yield line
                for line in po.stdout:
                    yield line
            yield "Done"
        except Exception as e:
            yield f"Error executing command: {e}"
    
    def _toggle_daemon(self, daemon_name, status):
        """Toggle system daemon on/off."""
        systemctl = self.server.systemctl
        
        if status:
            cmd = f"{systemctl} start {daemon_name}"
            self.logger.info(f"Starting daemon {daemon_name}")
        else:
            cmd = f"{systemctl} stop {daemon_name}"
            self.logger.info(f"Stopping daemon {daemon_name}")
        
        with os.popen(cmd) as po:
            return po.read()
    
    def _get_tunnel_status(self):
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
    
    def _toggle_tunnel(self, enabled):
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
                self.server._update_tunnel_environment()
            
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
    
    def _update_tunnel_config(self, config_data):
        """Update tunnel configuration settings."""
        self.logger.info(f"Updating tunnel configuration: {list(config_data.keys())}")
        
        try:
            # Update configuration
            updated_config = self.config.update_tunnel_config(config_data)
            
            # If tunnel is enabled and token was updated, restart service
            if updated_config.get('enabled') and 'token' in config_data:
                self.logger.info("Token updated, restarting tunnel service")
                
                # Update environment file with new token from configuration
                self.server._update_tunnel_environment()
                
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