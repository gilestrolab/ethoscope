import bottle
import subprocess
import socket
import logging
import traceback
import os
import signal
import sys
import zipfile
import datetime
import fnmatch
import tempfile
import shutil
import netifaces
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

from ethoscope_node.utils.device_scanner import EthoscopeScanner, SensorScanner
from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper, BackupClass
from ethoscope_node.utils.etho_db import ExperimentalDB

# Constants
DEFAULT_PORT = 80
STATIC_DIR = "../static"

SYSTEM_DAEMONS = {
    "ethoscope_backup": {
        'description': 'The service that collects data from the ethoscopes and syncs them with the node.',
        'available_on_docker': True
    },
    "ethoscope_video_backup": {
        'description': 'The service that collects VIDEOs from the ethoscopes and syncs them with the node',
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
        'available_on_docker': True
    },
    "sshd": {
        'description': 'The SSH daemon allows power users to access the node terminal from remote.',
        'available_on_docker': False
    },
    "vsftpd": {
        'description': 'The FTP server on the node, used to access the local ethoscope data',
        'available_on_docker': False
    },
    "virtuascope": {
        'description': 'A virtual ethoscope running on the node. Useful for offline tracking',
        'available_on_docker': False
    }
}


class ServerError(Exception):
    """Custom exception for server errors."""
    pass


def error_decorator(func):
    """Decorator to return error dict for display in webUI."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {'error': traceback.format_exc()}
    return wrapper


def warning_decorator(func):
    """Decorator to return warning dict for display in webUI."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {'error': str(e)}
    return wrapper


class CherootServer(bottle.ServerAdapter):
    """Custom Cheroot server adapter with proper configuration."""
    
    def run(self, handler):
        try:
            from cheroot import wsgi
            from cheroot.ssl import builtin
        except ImportError:
            raise ImportError("Cheroot server requires 'cheroot' package")
        
        # Only use supported parameters
        server_options = {
            'bind_addr': (self.host, self.port),
            'wsgi_app': handler,
        }
        
        # Add SSL if certificates are provided
        certfile = self.options.get('certfile')
        keyfile = self.options.get('keyfile')
        chainfile = self.options.get('chainfile')
        
        server = wsgi.Server(**server_options)
        
        if certfile and keyfile:
            server.ssl_adapter = builtin.BuiltinSSLAdapter(certfile, keyfile, chainfile)
        
        try:
            server.start()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                server.stop()
            except Exception as e:
                logging.warning(f"Error stopping Cheroot server: {e}")


class EthoscopeNodeServer:
    """Main server class for Ethoscope Node."""
    
    def __init__(self, port: int = DEFAULT_PORT, debug: bool = False, 
                 temp_results_dir: Optional[str] = None):
        self.port = port
        self.debug = debug
        self.app = bottle.Bottle()
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Core components
        self.config: Optional[EthoscopeConfiguration] = None
        self.device_scanner: Optional[EthoscopeScanner] = None
        self.sensor_scanner: Optional[SensorScanner] = None
        self.database: Optional[ExperimentalDB] = None
        
        # Paths and directories
        self.tmp_imgs_dir: Optional[str] = None
        self.results_dir: Optional[str] = temp_results_dir
        
        # System configuration
        self.is_dockerized = os.path.exists('/.dockerenv')
        self.systemctl = "/usr/bin/systemctl.py" if self.is_dockerized else "/usr/bin/systemctl"
        
        # Server state
        self._server_running = False
        self._shutdown_requested = False
        
        # Setup routes and hooks
        self._setup_routes()
        self._setup_hooks()
    
    def _detect_available_server(self):
        """Detect which server adapter is available."""
        # Try to import servers in order of preference
        servers = [
            ('paste', 'paste.httpserver'),
            ('cheroot', 'cheroot.wsgi'),
            ('cherrypy', 'cherrypy.wsgiserver'),
            ('wsgiref', 'wsgiref.simple_server')  # Built-in fallback
        ]
        
        for server_name, module_name in servers:
            try:
                __import__(module_name)
                self.logger.debug(f"Server {server_name} is available")
                return server_name
            except ImportError:
                continue
        
        # If nothing else, use built-in wsgiref
        return 'wsgiref'
    
    def _setup_routes(self):
        """Setup all application routes."""
        # Static files
        self.app.route('/static/<filepath:path>')(self._serve_static)
        self.app.route('/tmp_static/<filepath:path>')(self._serve_tmp_static)
        self.app.route('/download/<filepath:path>')(self._serve_download)
        self.app.route('/favicon.ico', method='GET')(self._get_favicon)
        
        # Main pages
        self.app.route('/', method='GET')(self._index)
        self.app.route('/update', method='GET')(self._update_redirect)
        
        # Device API
        self.app.route('/devices', method='GET')(self._get_devices)
        self.app.route('/devices_list', method='GET')(self._get_devices_list)
        self.app.route('/device/add', method='POST')(self._manual_add_device)
        self.app.route('/device/<id>/data', method='GET')(self._get_device_info)
        self.app.route('/device/<id>/machineinfo', method='GET')(self._get_device_machine_info)
        self.app.route('/device/<id>/machineinfo', method='POST')(self._set_device_machine_info)
        self.app.route('/device/<id>/module', method='GET')(self._get_device_module)
        self.app.route('/device/<id>/user_options', method='GET')(self._get_device_options)
        self.app.route('/device/<id>/videofiles', method='GET')(self._get_device_videofiles)
        self.app.route('/device/<id>/last_img', method='GET')(self._get_device_last_img)
        self.app.route('/device/<id>/dbg_img', method='GET')(self._get_device_dbg_img)
        self.app.route('/device/<id>/stream', method='GET')(self._get_device_stream)
        self.app.route('/device/<id>/backup', method='POST')(self._force_device_backup)
        self.app.route('/device/<id>/dumpSQLdb', method='GET')(self._device_local_dump)
        self.app.route('/device/<id>/retire', method='GET')(self._retire_device)
        self.app.route('/device/<id>/controls/<instruction>', method='POST')(self._post_device_instructions)
        self.app.route('/device/<id>/log', method='POST')(self._get_log)
        
        # Sensor API
        self.app.route('/sensors', method='GET')(self._get_sensors)
        self.app.route('/sensor/set', method='POST')(self._edit_sensor)
        self.app.route('/list_sensor_csv_files', method='GET')(self._list_csv_files)
        self.app.route('/get_sensor_csv_data/<filename>', method='GET')(self._get_csv_data)
        
        # Node API
        self.app.route('/node/<req>', method='GET')(self._node_info)
        self.app.route('/node-actions', method='POST')(self._node_actions)
        
        # File management
        self.app.route('/result_files/<type>', method='GET')(self._result_files)
        self.app.route('/browse/<folder:path>', method='GET')(self._browse)
        self.app.route('/request_download/<what>', method='POST')(self._download)
        self.app.route('/remove_files', method='POST')(self._remove_files)
        
        # Database API
        self.app.route('/runs_list', method='GET')(self._runs_list)
        self.app.route('/experiments_list', method='GET')(self._experiments_list)
        
        # Redirects
        self.app.route('/list/<type>', method='GET')(self._redirection_to_list)
        self.app.route('/ethoscope/<id>', method='GET')(self._redirection_to_ethoscope)
        self.app.route('/more/<action>', method='GET')(self._redirection_to_more)
        self.app.route('/experiments', method='GET')(self._redirection_to_experiments)
        self.app.route('/sensors_data', method='GET')(self._redirection_to_sensors)
        self.app.route('/resources', method='GET')(self._redirection_to_resources)
    
    def _setup_hooks(self):
        """Setup application hooks."""
        @self.app.hook('after_request')
        def enable_cors():
            bottle.response.headers['Access-Control-Allow-Origin'] = '*'
            bottle.response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
            bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'
    
    def initialize(self):
        """Initialize all server components."""
        try:
            self.logger.info("Initializing Ethoscope Node Server...")
            
            # Load configuration
            self.config = EthoscopeConfiguration()
            self.logger.info("Configuration loaded")
            
            # Setup results directory
            if not self.results_dir:
                self.results_dir = self.config.content['folders']['temporary']['path']
            
            # Create temporary images directory
            self.tmp_imgs_dir = tempfile.mkdtemp(prefix="ethoscope_node_imgs")
            self.logger.info(f"Created temporary images directory: {self.tmp_imgs_dir}")
            
            # Initialize database
            self.database = ExperimentalDB()
            self.logger.info("Database connection established")
            
            # Initialize device scanner
            try:
                self.device_scanner = EthoscopeScanner(results_dir=self.results_dir)
                self.device_scanner.start()
                self.logger.info("Ethoscope scanner started")
            except Exception as e:
                self.logger.error(f"Failed to start ethoscope scanner: {e}")
                raise
            
            # Initialize sensor scanner
            try:
                self.sensor_scanner = SensorScanner()
                self.sensor_scanner.start()
                self.logger.info("Sensor scanner started")
            except Exception as e:
                self.logger.warning(f"Failed to start sensor scanner: {e}")
                self.logger.warning("Continuing without sensor scanner")
                self.sensor_scanner = None
            
            self.logger.info("Server initialization complete")
            
        except Exception as e:
            self.logger.error(f"Server initialization failed: {e}")
            self.cleanup()
            raise
    
    def cleanup(self):
        """Clean up all server resources."""
        if self._shutdown_requested:
            return  # Already cleaning up
            
        self._shutdown_requested = True
        self.logger.info("Cleaning up server resources...")
        
        # Stop server flag
        self._server_running = False
        
        if self.device_scanner:
            try:
                self.device_scanner.stop()
                self.logger.info("Device scanner stopped")
            except Exception as e:
                self.logger.warning(f"Error stopping device scanner: {e}")
        
        if self.sensor_scanner:
            try:
                self.sensor_scanner.stop()
                self.logger.info("Sensor scanner stopped")
            except Exception as e:
                self.logger.warning(f"Error stopping sensor scanner: {e}")
        
        if self.tmp_imgs_dir and os.path.exists(self.tmp_imgs_dir):
            try:
                shutil.rmtree(self.tmp_imgs_dir)
                self.logger.info("Temporary images directory cleaned up")
            except Exception as e:
                self.logger.warning(f"Error cleaning tmp directory: {e}")
        
        # Add a small delay to allow connections to close gracefully
        time.sleep(0.1)
        
        self.logger.info("Server cleanup complete")
    
    def run(self):
        """Start the web server with better server detection."""
        self.logger.info(f"Starting web server on port {self.port}")
        self._server_running = True
        
        # Detect available server
        available_server = self._detect_available_server()
        
        try:
            if available_server == 'cheroot':
                # Register our custom Cheroot server
                bottle.server_names["cheroot"] = CherootServer
            
            self.logger.info(f"Using {available_server} server")
            
            bottle.run(self.app, host='0.0.0.0', port=self.port, 
                      debug=self.debug, server=available_server, 
                      quiet=not self.debug)
                
        except KeyboardInterrupt:
            self.logger.info("Server interrupted")
            raise
        except Exception as e:
            self.logger.error(f"Server error: {e}")
            raise
        finally:
            self._server_running = False

    # [Include all the existing route handler methods here - they remain the same]
    # _serve_static, _serve_tmp_static, _index, _get_devices, etc.
    # I'll include a few key ones as examples:

    def _serve_static(self, filepath):
        return bottle.static_file(filepath, root=STATIC_DIR)
    
    def _serve_tmp_static(self, filepath):
        return bottle.static_file(filepath, root=self.tmp_imgs_dir)
    
    def _serve_download(self, filepath):
        return bottle.static_file(filepath, root="/", download=filepath)
    
    def _get_favicon(self):
        return self._serve_static('img/favicon.ico')
    
    def _index(self):
        return bottle.static_file('index.html', root=STATIC_DIR)
    
    def _update_redirect(self):
        return bottle.redirect(self.config.custom('UPDATE_SERVICE_URL'))
    
    @error_decorator
    def _get_devices(self):
        return self.device_scanner.get_all_devices_info()
    
    def _get_devices_list(self):
        return self._get_devices()

    def _manual_add_device(self):
        """Manually add ethoscopes using provided IPs."""
        input_string = bottle.request.body.read().decode("utf-8")
        added = []
        problems = []
        
        for ip_address in input_string.split(","):
            ip_address = ip_address.strip()
            try:
                self.device_scanner.add(ip_address)
                added.append(ip_address)
            except Exception:
                problems.append(ip_address)
        
        return {"added": added, "problems": problems}
    
    @warning_decorator
    def _get_device_info(self, id):
        device = self.device_scanner.get_device(id)
        
        if not device:
            try:
                return self.device_scanner.get_all_devices_info()[id]
            except KeyError:
                raise Exception(f"A device with ID {id} is unknown to the system")
        
        return device.info()
    
    @error_decorator
    def _get_device_machine_info(self, id):
        device = self.device_scanner.get_device(id)
        if not device:
            return self.device_scanner.get_all_devices_info()[id]
        return device.machine_info()
    
    @error_decorator
    def _set_device_machine_info(self, id):
        post_data = bottle.request.body.read()
        device = self.device_scanner.get_device(id)
        response = device.send_settings(post_data)
        return {**device.machine_info(), "haschanged": response['haschanged']}
    
    @error_decorator
    def _get_device_module(self, id):
        device = self.device_scanner.get_device(id)
        return device.connected_module() if device else {}
    
    @error_decorator
    def _get_device_options(self, id):
        device = self.device_scanner.get_device(id)
        return device.user_options() if device else None
    
    @error_decorator
    def _get_device_videofiles(self, id):
        device = self.device_scanner.get_device(id)
        try:
            return device.videofiles() if device else []
        except Exception:
            return []
    
    @error_decorator
    def _get_device_last_img(self, id):
        device = self.device_scanner.get_device(id)
        device_info = device.info()
        
        if "status" not in device_info or device_info["status"] == "not_in_use":
            raise Exception(f"Device {id} is not in use, no image")
        
        file_like = device.last_image()
        if not file_like:
            raise Exception(f"No image for {id}")
        
        basename = os.path.join(self.tmp_imgs_dir, f"{id}_last_img.jpg")
        return self._cache_img(file_like, basename)
    
    @error_decorator
    def _get_device_dbg_img(self, id):
        device = self.device_scanner.get_device(id)
        file_like = device.dbg_img()
        basename = os.path.join(self.tmp_imgs_dir, f"{id}_debug.png")
        return self._cache_img(file_like, basename)
    
    @error_decorator
    def _get_device_stream(self, id):
        device = self.device_scanner.get_device(id)
        bottle.response.set_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
        return device.relay_stream()
    
    @error_decorator
    def _force_device_backup(self, id):
        """Force backup on device with specified id."""
        device_info = self._get_device_info(id)
        
        try:
            self.logger.info(f"Initiating backup for device {device_info['id']}")
            backup_job = BackupClass(device_info, results_dir=self.results_dir)
            
            self.logger.info(f"Running backup for device {device_info['id']}")
            success = False
            for status_update in backup_job.backup():
                # Process status updates
                status = json.loads(status_update)
                self.logger.info(f"Backup status: {status}")
                if status.get('status') == 'success':
                    success = True
            
            if success:
                self.logger.info(f"Backup done for device {device_info['id']}")
            else:
                self.logger.error(f"Backup for device {device_info['id']} could not be completed")
                
            return {'success': success}
            
        except Exception as e:
            self.logger.error(f"Unexpected error in backup: {e}")
            self.logger.error(traceback.format_exc())
            raise
    
    @error_decorator
    def _device_local_dump(self, id):
        """Ask the device to perform a local SQL dump."""
        device = self.device_scanner.get_device(id)
        return device.dump_sql_db()
    
    @error_decorator
    def _retire_device(self, id):
        """Change the status of the device to inactive in the device database."""
        return self.device_scanner.retire_device(id)
    
    @error_decorator
    def _post_device_instructions(self, id, instruction):
        post_data = bottle.request.body.read()
        device = self.device_scanner.get_device(id)
        device.send_instruction(instruction, post_data)
        return self._get_device_info(id)
    
    @error_decorator
    def _get_log(self, id):
        device = self.device_scanner.get_device(id)
        return device.get_log()
    
    # Route handlers - Sensor API
    @error_decorator
    def _get_sensors(self):
        return self.sensor_scanner.get_all_devices_info() if self.sensor_scanner else {}
    
    def _edit_sensor(self):
        input_string = bottle.request.body.read().decode("utf-8")
        data = eval(input_string)  # Note: This should use json.loads() for security
        
        if self.sensor_scanner:
            try:
                sensor = self.sensor_scanner.get_device(data["id"])
                if sensor:
                    return sensor.set({"location": data["location"], "sensor_name": data["name"]})
            except Exception:
                pass
    
    @error_decorator
    def _list_csv_files(self):
        """List CSV files in /ethoscope_data/sensors/."""
        directory = '/ethoscope_data/sensors/'
        try:
            if os.path.exists(directory):
                csv_files = [f for f in os.listdir(directory) if f.endswith('.csv')]
                return {'files': csv_files}
        except Exception:
            pass
        return {'files': []}
    
    @error_decorator
    def _get_csv_data(self, filename):
        """Read CSV file and return data for plotting."""
        directory = '/ethoscope_data/sensors/'
        filepath = os.path.join(directory, filename)
        
        data = []
        with open(filepath, 'r') as csvfile:
            headers = csvfile.readline().strip().split(',')
            for line in csvfile:
                data.append(line.strip().split(','))
        
        return {'headers': headers, 'data': data}
    
    # Route handlers - Database API
    @error_decorator
    def _runs_list(self):
        return json.dumps(self.database.getRun('all', asdict=True))
    
    @error_decorator
    def _experiments_list(self):
        return json.dumps(self.database.getExperiment('all', asdict=True))
    
    # Route handlers - Node API
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
            return self.config.content['users']
        elif req == 'incubators':
            return self.config.content['incubators']
        elif req == 'sensors':
            return self._get_sensors()
        elif req == 'commands':
            return self.config.content['commands']
        else:
            raise NotImplementedError(f"Unknown node request: {req}")
    
    def _get_node_system_info(self):
        """Get comprehensive node system information."""
        try:
            # Disk usage
            with os.popen(f'df {self.results_dir} -h') as df:
                disk_free = df.read()
            disk_usage = disk_free.split("\n")[1].split()
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
            with os.popen(f'{self.systemctl} status ethoscope_node.service') as df:
                active_since = df.read().split("\n")[2]
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
        
        for daemon_name in daemons.keys():
            try:
                with os.popen(f"{self.systemctl} is-active {daemon_name}") as df:
                    is_active = df.read().strip()
                
                is_not_available_on_docker = not daemons[daemon_name]["available_on_docker"]
                
                daemons[daemon_name].update({
                    'active': is_active,
                    'not_available': (self.is_dockerized and is_not_available_on_docker)
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
        action = bottle.request.json
        action_type = action.get('action')
        
        if action_type == 'restart':
            self.logger.info('User requested a service restart.')
            with os.popen(f"sleep 1; {self.systemctl} restart ethoscope_node.service") as po:
                return po.read()
        
        elif action_type == 'close':
            self._shutdown()
        
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
        if status:
            cmd = f"{self.systemctl} start {daemon_name}"
            self.logger.info(f"Starting daemon {daemon_name}")
        else:
            cmd = f"{self.systemctl} stop {daemon_name}"
            self.logger.info(f"Stopping daemon {daemon_name}")
        
        with os.popen(cmd) as po:
            return po.read()
    
    # Route handlers - File management
    @error_decorator
    def _result_files(self, type):
        """Get result files of specified type."""
        if type == "all":
            pattern = '*'
        else:
            pattern = f'*.{type}'
        
        matches = []
        for root, dirnames, filenames in os.walk(self.results_dir):
            for f in fnmatch.filter(filenames, pattern):
                matches.append(os.path.join(root, f))
        
        return {"files": matches}
    
    @error_decorator
    def _browse(self, folder):
        """Browse directory contents."""
        directory = self.results_dir if folder == 'null' else f'/{folder}'
        files = {}
        
        for (dirpath, dirnames, filenames) in os.walk(directory):
            for name in filenames:
                abs_path = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(abs_path)
                    mtime = os.path.getmtime(abs_path)
                    files[name] = {'abs_path': abs_path, 'size': size, 'mtime': mtime}
                except Exception:
                    # Skip files that can't be accessed
                    continue
        
        return {'files': files}
    
    @error_decorator
    def _download(self, what):
        """Create download archives."""
        if what == 'files':
            req_files = bottle.request.json
            timestamp = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
            zip_file_name = os.path.join(self.results_dir, f'results_{timestamp}.zip')
            
            with zipfile.ZipFile(zip_file_name, mode='a') as zf:
                self.logger.info(f"Creating archive: {zip_file_name}")
                for f in req_files['files']:
                    try:
                        zf.write(f['url'])
                    except Exception as e:
                        self.logger.warning(f"Failed to add {f['url']} to archive: {e}")
            
            return {'url': zip_file_name}
        else:
            raise NotImplementedError(f"Download type '{what}' not supported")
    
    @error_decorator
    def _remove_files(self):
        """Remove specified files."""
        req = bottle.request.json
        results = []
        
        for f in req['files']:
            try:
                rm = subprocess.run(['rm', f['url']], capture_output=True, text=True)
                if rm.returncode == 0:
                    results.append(f['url'])
                    self.logger.info(f"Removed file: {f['url']}")
                else:
                    self.logger.error(f"Failed to remove {f['url']}: {rm.stderr}")
            except Exception as e:
                self.logger.error(f"Error removing {f['url']}: {e}")
        
        return {'result': results}
    
    # Route handlers - Redirects
    def _redirection_to_list(self, type):
        return bottle.redirect(f'/#/list/{type}')
    
    def _redirection_to_ethoscope(self, id):
        return bottle.redirect(f'/#/ethoscope/{id}')
    
    def _redirection_to_more(self, action):
        return bottle.redirect(f'/#/more/{action}')
    
    def _redirection_to_experiments(self):
        return bottle.redirect('/#/experiments')
    
    def _redirection_to_sensors(self):
        return bottle.redirect('/#/sensors_data')
    
    def _redirection_to_resources(self):
        return bottle.redirect('/#/resources')
    
    # Helper methods
    def _cache_img(self, file_like, basename):
        """Cache image file locally."""
        if not file_like:
            return ""
        
        local_file = os.path.join(self.tmp_imgs_dir, basename)
        tmp_file = tempfile.mktemp(prefix="ethoscope_", suffix=".jpg")
        
        try:
            with open(tmp_file, "wb") as lf:
                lf.write(file_like.read())
            shutil.move(tmp_file, local_file)
            return self._serve_tmp_static(os.path.basename(local_file))
        except Exception as e:
            self.logger.error(f"Error caching image: {e}")
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
            return ""


    def _shutdown(self, exit_status=0):
        """Shutdown the server."""
        self.logger.info("Shutting down server")
        self.cleanup()
        os._exit(exit_status)


def setup_logging(debug: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if debug else logging.INFO
    format_string = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    logging.basicConfig(level=level, format=format_string)
    
    if debug:
        logging.info("Debug logging enabled")


def parse_command_line():
    """Parse command line arguments."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Ethoscope Node Server')
    parser.add_argument('-D', '--debug', action='store_true',
                       help='Enable debug mode')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT,
                       help=f'Server port (default: {DEFAULT_PORT})')
    parser.add_argument('-e', '--temporary-results-dir', dest='temp_results_dir',
                       help='Directory for temporary result files')
    
    return parser.parse_args()


def main():
    """Main entry point with improved cleanup."""
    # Parse arguments and setup logging
    args = parse_command_line()
    setup_logging(args.debug)
    logger = logging.getLogger('EthoscopeNodeServer')
    
    server = None
    
    def signal_handler(sig, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {sig}, shutting down gracefully...")
        if server:
            server.cleanup()
        sys.exit(0)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Initialize and start server
        server = EthoscopeNodeServer(
            port=args.port,
            debug=args.debug,
            temp_results_dir=args.temp_results_dir
        )
        
        server.initialize()
        server.run()
        
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        
    except socket.error as e:
        logger.error(f"Socket error: {e}")
        logger.error(f"Port {args.port} is probably not accessible. Try another port with -p option")
        if server:
            server.cleanup()
        sys.exit(1)
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        if server:
            server.cleanup()
        sys.exit(1)
        
    finally:
        if server:
            server.cleanup()
        logger.info("Server shutdown complete")


if __name__ == '__main__':
    main()