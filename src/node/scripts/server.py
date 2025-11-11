import logging
import os
import shutil
import signal
import sys
import tempfile
import time
import traceback
from typing import Optional

import bottle

from ethoscope_node.api import AuthAPI
from ethoscope_node.api import BackupAPI
from ethoscope_node.api import DatabaseAPI
from ethoscope_node.api import DeviceAPI
from ethoscope_node.api import FileAPI
from ethoscope_node.api import NodeAPI
from ethoscope_node.api import ROITemplateAPI
from ethoscope_node.api import SensorAPI
from ethoscope_node.api import SetupAPI
from ethoscope_node.api import TunnelUtils
from ethoscope_node.auth import AuthMiddleware
from ethoscope_node.scanner.ethoscope_scanner import EthoscopeScanner
from ethoscope_node.scanner.sensor_scanner import SensorScanner
from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.configuration import ensure_ssh_keys
from ethoscope_node.utils.etho_db import ExperimentalDB

# Constants
DEFAULT_PORT = 80
STATIC_DIR = "../static"
ETHOSCOPE_DATA_DIR = "/ethoscope_data"


class ServerError(Exception):
    """Custom exception for server errors."""

    pass


def error_decorator(func):
    """Decorator to return error dict for display in webUI."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logging.error(traceback.format_exc())
            return {"error": traceback.format_exc()}

    return wrapper


def warning_decorator(func):
    """Decorator to return warning dict for display in webUI."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {"error": str(e)}

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
        except ImportError as e:
            raise ImportError("Cheroot server requires 'cheroot' package") from e

        # Only use supported parameters
        server_options = {
            "bind_addr": (self.host, self.port),
            "wsgi_app": handler,
        }

        # Add SSL if certificates are provided
        certfile = self.options.get("certfile")
        keyfile = self.options.get("keyfile")
        chainfile = self.options.get("chainfile")

        server = wsgi.Server(**server_options)

        try:
            if certfile and keyfile:
                server.ssl_adapter = builtin.BuiltinSSLAdapter(
                    certfile, keyfile, chainfile
                )
        except (NameError, AttributeError):
            # cheroot < 6.0.0
            pass

        try:
            server.start()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                import time

                time.sleep(0.01)  # Give a moment for connections to close
                server.stop()
            except Exception as e:
                logging.warning(f"Error stopping Cheroot server: {e}")


class EthoscopeNodeServer:
    """Main server class for Ethoscope Node."""

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        debug: bool = False,
        ethoscope_data_dir: Optional[str] = None,
        config_dir: Optional[str] = None,
    ):
        self.port = port
        self.debug = debug
        self.app = bottle.Bottle()
        self.logger = logging.getLogger(self.__class__.__name__)

        # Core components
        self.config: Optional[EthoscopeConfiguration] = None
        self.device_scanner: Optional[EthoscopeScanner] = None
        self.sensor_scanner: Optional[SensorScanner] = None
        self.database: Optional[ExperimentalDB] = None
        self.tunnel_utils: Optional[TunnelUtils] = None

        # Paths and directories
        self.tmp_imgs_dir: Optional[str] = None
        self.results_dir: Optional[str] = os.path.join(ethoscope_data_dir, "results")
        self.sensors_dir: Optional[str] = os.path.join(ethoscope_data_dir, "sensors")
        self.roi_templates_dir: Optional[str] = os.path.join(
            ethoscope_data_dir, "roi_templates"
        )

        self.config_dir: Optional[str] = config_dir

        # Set module-level defaults for configuration and database paths if custom config_dir provided
        if config_dir:
            from ethoscope_node.utils.configuration import set_default_config_file
            from ethoscope_node.utils.etho_db import set_default_config_dir

            set_default_config_dir(config_dir)
            set_default_config_file(os.path.join(config_dir, "ethoscope.conf"))
            self.logger.info(
                f"Set module-level defaults to use config directory: {config_dir}"
            )

        # System configuration
        self.is_dockerized = os.path.exists("/.dockerenv")
        self.systemctl = (
            "/usr/bin/systemctl.py" if self.is_dockerized else "/usr/bin/systemctl"
        )

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
            ("paste", "paste.httpserver"),
            ("cheroot", "cheroot.wsgi"),
            ("cherrypy", "cherrypy.wsgiserver"),
            ("wsgiref", "wsgiref.simple_server"),  # Built-in fallback
        ]

        for server_name, module_name in servers:
            try:
                __import__(module_name)
                self.logger.debug(f"Server {server_name} is available")
                return server_name
            except ImportError:
                continue

        # If nothing else, use built-in wsgiref
        return "wsgiref"

    def _setup_routes(self):
        """Setup all application routes using modular API components."""
        # Static files and core pages
        self.app.route("/static/<filepath:path>")(self._serve_static)
        self.app.route("/tmp_static/<filepath:path>")(self._serve_tmp_static)
        self.app.route("/download/<filepath:path>")(self._serve_download)
        self.app.route("/favicon.ico", method="GET")(self._get_favicon)

        # Main pages
        self.app.route("/", method="GET")(self._index)
        self.app.route("/installation-wizard", method="GET")(self._installation_wizard)
        self.app.route("/setup", method="GET")(self._setup_redirect)
        self.app.route("/reconfigure", method="GET")(self._reconfigure_redirect)
        self.app.route("/update", method="GET")(self._update_redirect)

        # Redirects (kept in main server for simplicity)
        self.app.route("/list/<type>", method="GET")(self._redirection_to_list)
        self.app.route("/ethoscope/<id>", method="GET")(self._redirection_to_ethoscope)
        self.app.route("/more/<action>", method="GET")(self._redirection_to_more)
        self.app.route("/experiments", method="GET")(self._redirection_to_experiments)
        self.app.route("/sensors_data", method="GET")(self._redirection_to_sensors)
        self.app.route("/resources", method="GET")(self._redirection_to_resources)

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
            DatabaseAPI,
            SetupAPI,
            TunnelUtils,
            AuthAPI,
        ]

        for api_class in api_classes:
            api_module = api_class(self)
            api_module.register_routes()
            self.api_modules.append(api_module)

            # Create special reference to tunnel utils for easier access
            if isinstance(api_module, TunnelUtils):
                self.tunnel_utils = api_module

    def _setup_hooks(self):
        """Setup application hooks."""

        @self.app.hook("after_request")
        def enable_cors():
            bottle.response.headers["Access-Control-Allow-Origin"] = "*"
            bottle.response.headers["Access-Control-Allow-Methods"] = (
                "PUT, GET, POST, DELETE, OPTIONS"
            )
            bottle.response.headers["Access-Control-Allow-Headers"] = (
                "Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token"
            )

    def initialize(self):
        """Initialize all server components."""
        try:
            self.logger.info("Initializing Ethoscope Node Server...")

            # Load configuration (uses module-level default set in __init__)
            self.config = EthoscopeConfiguration()
            self.logger.info(f"Configuration loaded from {self.config._config_file}")

            # Ensure SSH keys exist
            try:
                keys_dir = (
                    os.path.join(self.config_dir, "keys")
                    if self.config_dir
                    else "/etc/ethoscope/keys"
                )
                private_key_path, public_key_path = ensure_ssh_keys(keys_dir)
                self.logger.info(
                    f"SSH keys ready: {private_key_path}, {public_key_path}"
                )
            except Exception as e:
                self.logger.error(f"Failed to setup SSH keys: {e}")
                # Continue without SSH keys for now
                pass

            # Setup results directory
            if not self.results_dir:
                self.results_dir = self.config.content["folders"]["temporary"]["path"]

            # Create temporary images directory
            self.tmp_imgs_dir = tempfile.mkdtemp(prefix="ethoscope_node_imgs")
            self.logger.info(f"Created temporary images directory: {self.tmp_imgs_dir}")

            # Initialize database (uses module-level default set in __init__)
            self.database = ExperimentalDB()
            self.logger.info(
                f"Database connection established at {self.database._db_name}"
            )

            # Initialize authentication middleware
            try:
                self.auth_middleware = AuthMiddleware(self.database, self.config)
                # Make auth middleware available to the bottle app
                self.app.auth_middleware = self.auth_middleware
                self.logger.info("Authentication middleware initialized")
            except Exception as e:
                self.logger.error(
                    f"Failed to initialize authentication middleware: {e}"
                )
                # Continue without authentication for now (backward compatibility)
                self.auth_middleware = None

            # Retire inactive devices at startup
            try:
                retired_count = self.database.retire_inactive_devices()
                self.logger.info(f"Retired {retired_count} inactive devices at startup")
            except Exception as e:
                self.logger.warning(
                    f"Failed to retire inactive devices at startup: {e}"
                )

            # Clean up offline busy devices at startup
            try:
                cleaned_count = self.database.cleanup_offline_busy_devices()
                self.logger.info(
                    f"Cleaned up {cleaned_count} offline busy devices at startup"
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to cleanup offline busy devices at startup: {e}"
                )

            # Clean up orphaned running sessions at startup
            try:
                orphaned_count = self.database.cleanup_orphaned_running_sessions()
                self.logger.info(
                    f"Cleaned up {orphaned_count} orphaned running sessions at startup"
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to cleanup orphaned running sessions at startup: {e}"
                )

            # Initialize device scanner
            try:
                # Pass config_dir explicitly to scanner as it needs it for SSH key management
                self.device_scanner = EthoscopeScanner(
                    results_dir=self.results_dir,
                    config_dir=self.config_dir or "/etc/ethoscope",
                    config=self.config,
                )
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

            # Ensure tunnel environment file is up to date (after API modules are setup)
            self._update_tunnel_environment()

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
            if available_server == "cheroot":
                # Register our custom Cheroot server
                bottle.server_names["cheroot"] = CherootServer

            self.logger.info(f"Using {available_server} server")

            bottle.run(
                self.app,
                host="0.0.0.0",
                port=self.port,
                debug=self.debug,
                server=available_server,
                quiet=not self.debug,
            )

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
        return self._serve_static("img/favicon.ico")

    def _index(self):
        # Check for reconfigure parameter to bypass setup check
        reconfigure = bottle.request.query.get("reconfigure", "").lower() == "true"

        # Check if setup is required and redirect to installation wizard
        # (but skip if reconfigure is explicitly requested)
        if not reconfigure:
            try:
                if self.config and self.config.is_setup_required():
                    self.logger.info(
                        "Setup required, redirecting to installation wizard"
                    )
                    return bottle.redirect("/#!/installation-wizard")
            except Exception as e:
                self.logger.warning(f"Error checking setup status: {e}")
                # Continue to serve index.html if there's an error checking setup

        return bottle.static_file("index.html", root=STATIC_DIR)

    def _installation_wizard(self):
        # Always serve the main index.html for the installation wizard
        # Angular routing will handle showing the wizard component
        return bottle.static_file("index.html", root=STATIC_DIR)

    def _setup_redirect(self):
        """Direct access to setup wizard (respects setup completion status)"""
        return bottle.redirect("/#!/installation-wizard")

    def _reconfigure_redirect(self):
        """Direct access to setup wizard in reconfigure mode"""
        return bottle.redirect("/#!/installation-wizard?reconfigure=true")

    def _update_redirect(self):
        """Redirect to update service URL with hostname-aware logic."""
        try:
            if not self.tunnel_utils:
                # Fallback to configured URL if tunnel utils not available
                return bottle.redirect(self.config.custom("UPDATE_SERVICE_URL"))

            # Get the current request hostname
            current_host = bottle.request.environ.get("HTTP_HOST", "").lower()
            fallback_url = self.config.custom("UPDATE_SERVICE_URL")

            # Use tunnel utils to determine appropriate redirect URL
            redirect_url = self.tunnel_utils.get_hostname_aware_redirect_url(
                current_host, fallback_url
            )
            return bottle.redirect(redirect_url)

        except Exception as e:
            self.logger.warning(f"Error in update redirect: {e}")
            # Fallback to configured URL
            return bottle.redirect(self.config.custom("UPDATE_SERVICE_URL"))

    # Route handlers - Redirects
    def _redirection_to_list(self, type):
        return bottle.redirect(f"/#/list/{type}")

    def _redirection_to_ethoscope(self, id):
        return bottle.redirect(f"/#/ethoscope/{id}")

    def _redirection_to_more(self, action):
        return bottle.redirect(f"/#/more/{action}")

    def _redirection_to_experiments(self):
        return bottle.redirect("/#/experiments")

    def _redirection_to_sensors(self):
        return bottle.redirect("/#/sensors_data")

    def _redirection_to_resources(self):
        return bottle.redirect("/#/resources")

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

    def _update_tunnel_environment(self):
        """Update tunnel environment file from configuration using tunnel utils."""
        try:
            if self.tunnel_utils:
                # Use tunnel utils to handle the environment update
                self.tunnel_utils.update_tunnel_environment()
            else:
                self.logger.warning(
                    "Tunnel utils not available, skipping tunnel environment update"
                )

        except Exception as e:
            self.logger.warning(f"Failed to update tunnel environment file: {e}")

    def _shutdown(self, exit_status=0):
        """Shutdown the server."""
        self.logger.info("Shutting down server")
        self.cleanup()
        os._exit(exit_status)


def setup_logging(debug: bool = False):
    """Setup logging configuration."""
    level = logging.INFO if debug else logging.ERROR
    format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Force configure logging even if already initialized
    logging.basicConfig(level=level, format=format_string, force=True)

    # Explicitly set root logger level to ensure it takes effect
    logging.getLogger().setLevel(level)

    if debug:
        logging.info("Debug logging enabled")


def parse_command_line():
    """Parse command line arguments with environment variable fallbacks."""
    import argparse

    # Get defaults from environment variables
    env_port = int(os.getenv("NODE_PORT", DEFAULT_PORT))
    env_debug = os.getenv("NODE_DEBUG", "false").lower() == "true"
    env_data_dir = os.getenv("ETHOSCOPE_DATA_DIR", "/ethoscope_data")
    env_config_dir = os.getenv("ETHOSCOPE_CONFIG_DIR")

    parser = argparse.ArgumentParser(description="Ethoscope Node Server")
    parser.add_argument(
        "-D",
        "--debug",
        action="store_true",
        default=env_debug,
        help=f"Enable debug mode (default: {env_debug})",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=env_port,
        help=f"Server port (default: {env_port})",
    )
    parser.add_argument(
        "-e",
        "--data-dir",
        dest="ethoscope_data_dir",
        default=env_data_dir,
        help=f'Root directory for all result files (default: "{env_data_dir}")',
    )
    parser.add_argument(
        "-c",
        "--configuration",
        dest="config_dir",
        default=env_config_dir,
        help=f"Path to configuration directory (default: {env_config_dir or '/etc/ethoscope'})",
    )

    return parser.parse_args()


def main():
    """Main entry point with improved cleanup."""
    # Parse arguments and setup logging
    args = parse_command_line()
    setup_logging(args.debug)
    logger = logging.getLogger("EthoscopeNodeServer")

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
            config_dir=args.config_dir,
        )

        server.initialize()
        server.run()

    except KeyboardInterrupt:
        logger.info("Server interrupted by user")

    except OSError as e:
        logger.error(f"Socket error: {e}")
        logger.error(
            f"Port {args.port} is probably not accessible. Try another port with -p option"
        )
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


if __name__ == "__main__":
    main()
