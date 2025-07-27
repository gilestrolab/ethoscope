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
        'description': 'Cloudflare tunnel service for remote access to this node via the internet. Requires token.',
        'available_on_docker': False
    },
    "ethoscope_sensor_virtual": {
        'description': 'A virtual sensor collecting real world data about. Requires token.',
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
            # Delegate to tunnel utils
            if hasattr(self.server, 'tunnel_utils') and self.server.tunnel_utils:
                return self.server.tunnel_utils.get_tunnel_status()
            else:
                return {'error': 'Tunnel utilities not available'}
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
            
            with os.popen('git rev-parse --short HEAD') as df:
                git_commit = df.read().strip() or "Not detected"
            
            with os.popen('git show -s --format=%ci HEAD') as df:
                git_date = df.read().strip() or "Not detected"
            
            with os.popen('git status -s -uno') as df:
                needs_update = df.read() != ""
        except Exception:
            git_branch = "Not detected"
            git_commit = "Not detected"
            git_date = "Not detected"
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
            'GIT_COMMIT': git_commit,
            'GIT_DATE': git_date,
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
            # Delegate to tunnel utils
            if hasattr(self.server, 'tunnel_utils') and self.server.tunnel_utils:
                return self.server.tunnel_utils.toggle_tunnel(action.get('enabled', False))
            else:
                return {'success': False, 'error': 'Tunnel utilities not available'}
        
        elif action_type == 'update_tunnel_config':
            # Delegate to tunnel utils
            if hasattr(self.server, 'tunnel_utils') and self.server.tunnel_utils:
                return self.server.tunnel_utils.update_tunnel_config(action.get('config', {}))
            else:
                return {'success': False, 'error': 'Tunnel utilities not available'}
        
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
