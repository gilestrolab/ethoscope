import bottle
import subprocess
import socket
import logging
import traceback
import os
import signal
import sys
import datetime
import tempfile
import shutil
import netifaces
import json
import time
from typing import Dict, List, Optional, Any

from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.sensor_scanner import SensorScanner
from ethoscope_node.utils.configuration import EthoscopeConfiguration, ensure_ssh_keys
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.etho_db import ExperimentalDB
from ethoscope_node.api import (
    DeviceAPI, BackupAPI, SensorAPI, ROITemplateAPI, 
    NodeAPI, FileAPI, DatabaseAPI
)

# Constants
DEFAULT_PORT = 80
STATIC_DIR = "../static"
ETHOSCOPE_DATA_DIR = "/ethoscope_data"

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
            try:
                from cheroot.ssl import builtin
            except ImportError:
                # cheroot < 6.0.0
                pass
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
        
        try:
            if certfile and keyfile:
                server.ssl_adapter = builtin.BuiltinSSLAdapter(certfile, keyfile, chainfile)
        except (NameError, AttributeError):
            # cheroot < 6.0.0
            pass
        
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
                 ethoscope_data_dir: Optional[str] = None, 
                 config_dir: Optional[str] = None ):
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
        self.results_dir: Optional[str] = os.path.join (ethoscope_data_dir, "results")
        self.sensors_dir: Optional[str] = os.path.join (ethoscope_data_dir, "sensors")
        self.roi_templates_dir: Optional[str] = os.path.join(ethoscope_data_dir, "roi_templates")

        self.config_dir: Optional[str] = config_dir
        
        # System configuration
        self.is_dockerized = os.path.exists('/.dockerenv')
        self.systemctl = "/usr/bin/systemctl.py" if self.is_dockerized else "/usr/bin/systemctl"
        
        # Server state
        self._server_running = False
        self._shutdown_requested = False
        
        # API modules
        self.api_modules = []
        
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
        """Setup all application routes using modular API components."""
        # Static files and core pages
        self.app.route('/static/<filepath:path>')(self._serve_static)
        self.app.route('/tmp_static/<filepath:path>')(self._serve_tmp_static)
        self.app.route('/download/<filepath:path>')(self._serve_download)
        self.app.route('/favicon.ico', method='GET')(self._get_favicon)
        
        # Main pages
        self.app.route('/', method='GET')(self._index)
        self.app.route('/update', method='GET')(self._update_redirect)
        
        # Redirects (kept in main server for simplicity)
        self.app.route('/list/<type>', method='GET')(self._redirection_to_list)
        self.app.route('/ethoscope/<id>', method='GET')(self._redirection_to_ethoscope)
        self.app.route('/more/<action>', method='GET')(self._redirection_to_more)
        self.app.route('/experiments', method='GET')(self._redirection_to_experiments)
        self.app.route('/sensors_data', method='GET')(self._redirection_to_sensors)
        self.app.route('/resources', method='GET')(self._redirection_to_resources)
        
        # Initialize and register API modules
    
    def _setup_api_modules(self):
        """Initialize and register all API modules."""
        # Create and register API modules
        api_classes = [
            DeviceAPI,
            BackupAPI, 
            SensorAPI,
            ROITemplateAPI,
            NodeAPI,
            FileAPI,
            DatabaseAPI
        ]
        
        for api_class in api_classes:
            api_module = api_class(self)
            api_module.register_routes()
            self.api_modules.append(api_module)

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
            if self.config_dir:
                config_file = os.path.join(self.config_dir, 'ethoscope.conf')
                self.config = EthoscopeConfiguration(config_file)
                self.logger.info(f"Configuration loaded from {config_file}")
            else:
                self.config = EthoscopeConfiguration()
                self.logger.info("Configuration loaded from default location")
            
            # Ensure SSH keys exist
            try:
                if self.config_dir:
                    keys_dir = os.path.join(self.config_dir, 'keys')
                    private_key_path, public_key_path = ensure_ssh_keys(keys_dir)
                else:
                    private_key_path, public_key_path = ensure_ssh_keys()
                self.logger.info(f"SSH keys ready: {private_key_path}, {public_key_path}")
            except Exception as e:
                self.logger.error(f"Failed to setup SSH keys: {e}")
                # Continue without SSH keys for now
                pass
            
            # Setup results directory
            if not self.results_dir:
                self.results_dir = self.config.content['folders']['temporary']['path']
            
            # Create temporary images directory
            self.tmp_imgs_dir = tempfile.mkdtemp(prefix="ethoscope_node_imgs")
            self.logger.info(f"Created temporary images directory: {self.tmp_imgs_dir}")
            
            # Initialize database
            if self.config_dir:
                self.database = ExperimentalDB(self.config_dir)
            else:
                self.database = ExperimentalDB()
            self.logger.info("Database connection established")
            
            # Initialize device scanner
            try:
                if self.config_dir:
                    self.device_scanner = EthoscopeScanner(results_dir=self.results_dir, config_dir=self.config_dir, config=self.config)
                else:
                    self.device_scanner = EthoscopeScanner(results_dir=self.results_dir, config=self.config)
                self.device_scanner.start()
                self.logger.info("Ethoscope scanner started")
            except Exception as e:
                self.logger.error(f"Failed to start ethoscope scanner: {e}")
                raise
            
            # Initialize sensor scanner
            try:
                self.sensor_scanner = SensorScanner(results_dir=self.sensors_dir)
                self.sensor_scanner.start()
                self.logger.info("Sensor scanner started")
            except Exception as e:
                self.logger.warning(f"Failed to start sensor scanner: {e}")
                self.logger.warning("Continuing without sensor scanner")
                self.sensor_scanner = None
            
            self._setup_api_modules()
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

    # Static file serving methods

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
    parser.add_argument('-D', '--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help=f'Server port (default: {DEFAULT_PORT})')
    parser.add_argument('-e', '--data-dir', dest='ethoscope_data_dir', default="/ethoscope_data", help=f'Root directory for all result files (default: "/ethoscope_data")')
    parser.add_argument('-c', '--configuration', dest='config_dir', help='Path to configuration directory (default: /etc/ethoscope)')
    
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
            ethoscope_data_dir=args.ethoscope_data_dir,
            config_dir=args.config_dir
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