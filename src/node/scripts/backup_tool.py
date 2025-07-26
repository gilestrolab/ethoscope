from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.backup.helpers import GenericBackupWrapper
from ethoscope_node.backup.mysql import get_backup_path_from_database
import logging
import optparse
import signal
import sys
import os
import json
import bottle
import threading
import time
import re
from contextlib import contextmanager

# Global variables
app = bottle.Bottle()
gbw = None

def enable_cors():
    """Add CORS headers to allow cross-origin requests"""
    bottle.response.headers['Access-Control-Allow-Origin'] = '*'
    bottle.response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    bottle.response.headers['Access-Control-Allow-Headers'] = 'Content-Type'

@app.route('/')
def home():
    enable_cors()
    bottle.response.content_type = 'application/json'
    
    if gbw is None:
        return json.dumps({
            'status': 'initializing',
            'error': 'Backup wrapper not initialized'
        }, indent=2)
    
    try:
        with gbw._lock:
            # Get basic backup wrapper stats
            active_jobs = sum(1 for status in gbw.backup_status.values() 
                            if getattr(status, 'processing', False))
            
            # Get device discovery information
            try:
                # Get fresh device count by actually discovering devices
                current_devices = gbw.find_devices() if hasattr(gbw, 'find_devices') else []
                current_active_count = len(current_devices)
            except Exception as discovery_error:
                current_active_count = getattr(gbw, '_last_device_count', 0)
                
            device_stats = {
                'total_discovered': getattr(gbw, '_last_device_count', 0),
                'active_eligible': current_active_count,
                'devices_with_status': len(gbw.backup_status) if hasattr(gbw, 'backup_status') else 0,
                'discovery_source': getattr(gbw, '_last_discovery_source', 'unknown'),
                'last_discovery_time': getattr(gbw, '_last_discovery_time', None)
            }
            
            # Get backup cycle information
            backup_stats = {
                'cycle_number': getattr(gbw, '_cycle_count', 0),
                'last_cycle_start': getattr(gbw, '_last_cycle_start', None),
                'active_backup_jobs': active_jobs,
                'total_devices_tracked': len(gbw.backup_status) if hasattr(gbw, 'backup_status') else 0
            }
            
            # Get configuration information
            config_info = {
                'node_address': getattr(gbw, '_node_address', 'unknown'),
                'results_dir': getattr(gbw, '_results_dir', 'unknown'),
                'video_backup_enabled': getattr(gbw, '_video', False),
                'max_threads': getattr(gbw, '_max_threads', 0),
                'backup_interval': 300  # Default 5 minutes
            }
            
            # Count recent errors (last hour)
            import time
            current_time = time.time()
            recent_errors = 0
            error_types = {}
            
            for device_id, status in gbw.backup_status.items():
                if hasattr(status, 'status') and hasattr(status, 'ended'):
                    if (status.status == 'error' and 
                        status.ended and 
                        current_time - status.ended < 3600):  # Last hour
                        recent_errors += 1
                        # Try to categorize error type from device name/status
                        error_type = 'unknown'
                        if hasattr(status, 'progress') and status.progress:
                            if 'VAR_MAP' in str(status.progress):
                                error_type = 'database_not_ready'
                            elif 'connection' in str(status.progress).lower():
                                error_type = 'connection_error'
                        error_types[error_type] = error_types.get(error_type, 0) + 1
            
            status_response = {
                'status': 'running',
                'service': 'ethoscope_backup_tool',
                'timestamp': current_time,
                'device_discovery': device_stats,
                'backup_progress': backup_stats,
                'configuration': config_info,
                'legacy_error_analysis': {
                    'count_last_hour': recent_errors,
                    'error_types': error_types
                },
                'thread_status': {
                    'is_alive': gbw.is_alive() if hasattr(gbw, 'is_alive') else False,
                    'is_running': gbw.is_running() if hasattr(gbw, 'is_running') else False,
                    'stop_event_set': gbw._stop_event.is_set() if hasattr(gbw, '_stop_event') else None
                },
                'health_status': gbw.get_health_status() if hasattr(gbw, 'get_health_status') else {}
            }
            
            return json.dumps(status_response, indent=2, default=str)
    
    except Exception as e:
        logging.error(f"Error getting home status: {e}")
        return json.dumps({
            'status': 'error',
            'error': f'Failed to get status: {str(e)}',
            'timestamp': time.time()
        }, indent=2)

@app.route('/status', method='OPTIONS')
@app.route('/', method='OPTIONS')
def options_handler():
    enable_cors()
    return ""

@app.route('/status')
def status():
    enable_cors()
    bottle.response.content_type = 'application/json'
    if gbw is None:
        return json.dumps({'error': 'Backup wrapper not initialized'}, indent=2)
    
    try:
        with gbw._lock:
            # Convert BackupStatus objects to dictionaries for JSON serialization
            status_dict = {}
            for device_id, backup_status in gbw.backup_status.items():
                if hasattr(backup_status, '__dict__'):
                    # If it's a BackupStatus dataclass, convert to dict
                    status_dict[device_id] = {
                        'name': getattr(backup_status, 'name', ''),
                        'status': getattr(backup_status, 'status', ''),
                        'started': getattr(backup_status, 'started', 0),
                        'ended': getattr(backup_status, 'ended', 0),
                        'processing': getattr(backup_status, 'processing', False),
                        'count': getattr(backup_status, 'count', 0),
                        'synced': getattr(backup_status, 'synced', {}),
                        'progress': getattr(backup_status, 'progress', {}),
                        'data_duplication': getattr(backup_status, 'data_duplication', False)
                    }
                else:
                    # If it's already a dictionary, use as-is
                    status_dict[device_id] = backup_status
        
        return json.dumps(status_dict, indent=2, default=str)
    
    except Exception as e:
        logging.error(f"Error serializing backup status: {e}")
        return json.dumps({'error': f'Failed to get backup status: {str(e)}'}, indent=2)

def setup_logging(debug=False):
    """Configure logging with appropriate level and format."""
    level = logging.DEBUG if debug else logging.INFO
    
    # Configure the root logger
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True  # Force reconfiguration
    )
    
    # Also configure specific loggers to ensure they all use the same level
    for logger_name in ['BackupWrapper.GenericBackupWrapper', 'BackupClass', 'VideoBackupClass']:
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        logger.propagate = True
    
    if debug:
        logging.info("Debug logging enabled for all loggers")

def parse_arguments():
    """Parse command line arguments using optparse."""
    parser = optparse.OptionParser(description='Ethoscope Backup Tool')
    parser.add_option('-D', '--debug', dest='debug', default=False, 
                     action='store_true', help='Enable debug mode')
    parser.add_option('-r', '--results-dir', dest='results_dir',
                     help='Directory where result files are stored')
    parser.add_option('-i', '--server', dest='server', default='localhost',
                     help='Server address for node interrogation')
    parser.add_option('-e', '--ethoscope', dest='ethoscope',
                     help='Force backup of specific ethoscopes by number (007,010), IP (192.168.1.29), or hostname (ethoscope070.local). Uses direct database access, bypassing device discovery.')
    parser.add_option('-s', '--safe', dest='safe', default=False,
                     action='store_true', help='Set Safe mode ON (currently unused)')
    parser.add_option('-p', '--port', dest='port', default=8090, type='int',
                     help='Port for HTTP status server (default: 8090)')
    parser.add_option('-c', '--configuration', dest='config_dir',
                     help='Path to configuration directory (default: /etc/ethoscope)')
    
    (options, args) = parser.parse_args()
    return options

def parse_ethoscope_list(ethoscope_arg):
    """Parse ethoscope targets from command line argument (numbers, IPs, or hostnames)."""
    if not ethoscope_arg:
        return []
    
    targets = []
    entries = [e.strip() for e in ethoscope_arg.split(',')]
    
    for entry in entries:
        if not entry:
            continue
            
        # Try to parse as number first
        try:
            num = int(entry)
            targets.append(('number', num))
            continue
        except ValueError:
            pass
        
        # Check if it looks like an IP address
        ip_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
        if re.match(ip_pattern, entry):
            targets.append(('ip', entry))
            continue
        
        # Otherwise treat as hostname
        targets.append(('hostname', entry))
    
    if not targets:
        logging.error(f"No valid ethoscope targets found in: {ethoscope_arg}")
        sys.exit(1)
    
    return targets


def resolve_ethoscope_host(identifier_type, value):
    """Convert ethoscope identifier to host address."""
    if identifier_type == 'number':
        # Convert ethoscope number to hostname format
        hostname = f"ethoscope{value:03d}.local"
        logging.info(f"Resolved ethoscope {value:03d} to hostname: {hostname}")
        return hostname
    elif identifier_type == 'ip':
        logging.info(f"Using provided IP: {value}")
        return value
    elif identifier_type == 'hostname':
        logging.info(f"Using provided hostname: {value}")
        return value
    else:
        raise ValueError(f"Unknown identifier type: {identifier_type}")

def create_device_info_from_backup(ethoscope_name, host, backup_filename):
    """Create minimal device_info dict required for BackupClass from backup filename."""
    
    # Extract device ID from backup filename if possible
    # Format: YYYY-MM-DD_HH-MM-SS_device_id.db
    device_id = "unknown"
    try:
        if backup_filename and '_' in backup_filename:
            parts = backup_filename.split('_')
            if len(parts) >= 3:
                # Take the part before .db extension
                device_id = parts[2].replace('.db', '')
        logging.info(f"Extracted device ID from backup filename: {device_id}")
    except Exception as e:
        logging.warning(f"Could not extract device ID from backup filename {backup_filename}: {e}")
    
    device_info = {
        'id': device_id,
        'name': ethoscope_name,
        'ip': host,
        'status': 'forced_backup',  # Indicate this is a forced backup
        'databases': {
            'SQLite': {},  # Empty for MariaDB backups
            'MariaDB': {
                backup_filename: {
                    'backup_filename': backup_filename,
                    'filesize': 0,  # Unknown for forced backups
                    'version': 'Unknown',
                    'date': time.time(),  # Current time as fallback
                    'db_status': 'forced_backup',
                    'table_counts': {},
                    'file_exists': True
                }
            }
        },
        'backup_status': 0.0,
        'backup_size': 0,
        'time_since_backup': 0.0,
        'backup_type': 'mariadb_dump',
        'backup_method': 'mysql_dump'
    }
    
    logging.info(f"Created device info for forced backup: {device_info}")
    return device_info

def force_backup_ethoscopes(ethoscope_list):
    """Force backup for specified ethoscopes using direct database access."""
    if not ethoscope_list:
        logging.warning("No ethoscopes specified for forced backup")
        return
    
    logging.info(f"Starting direct database backup for {len(ethoscope_list)} targets...")
    logging.info("Skipping device discovery - using direct database connection method")
    
    for identifier_type, value in ethoscope_list:
        try:
            # Resolve target to hostname/IP
            host = resolve_ethoscope_host(identifier_type, value)
            
            # Generate ethoscope name and extract number for database lookup
            ethoscope_number = None
            if identifier_type == 'number':
                ethoscope_name = f"ETHOSCOPE_{value:03d}"
                ethoscope_number = value
            else:
                # For IP/hostname, try to extract ethoscope number from hostname
                import re
                
                # Try to extract from hostname like "ethoscope265.local"
                hostname_match = re.search(r'ethoscope(\d+)', host)
                if hostname_match:
                    ethoscope_number = int(hostname_match.group(1))
                    ethoscope_name = f"ETHOSCOPE_{ethoscope_number:03d}"
                else:
                    # For IP addresses or other hostnames, we can't determine the ethoscope number
                    # Use the host as the ethoscope name and let the database lookup handle it
                    ethoscope_name = f"ETHOSCOPE_{host.replace('.', '_')}"
                    ethoscope_number = None  # Will rely on database name extraction in get_backup_path_from_database
            
            logging.info(f"=== PROCESSING {ethoscope_name} at {host} ===")
            
            # Get backup filename directly from database
            logging.info(f"Connecting to database on {host} to retrieve backup path...")
            backup_filename = get_backup_path_from_database(host, ethoscope_number)
            
            if not backup_filename:
                logging.error(f"No backup filename found for {ethoscope_name}")
                sys.exit(1)
            
            # Create device info for backup
            device_info = create_device_info_from_backup(ethoscope_name, host, backup_filename)
            
            logging.info(f"MariaDB database confirmed for {ethoscope_name} - starting forced backup job...")
            
            # Initiate backup using the synthetic device info
            logging.info(f"Initiating forced MariaDB backup job for {ethoscope_name}...")
            success = gbw.initiate_backup_job(device_info)
            
            if success:
                logging.info(f"=== BACKUP COMPLETED SUCCESSFULLY for {ethoscope_name} ===")
            else:
                logging.error(f"=== BACKUP FAILED for {ethoscope_name} ===")
                sys.exit(1)
                
        except ConnectionError as e:
            logging.error(f"Database connection failed for {ethoscope_name}: {e}")
            logging.error("This could mean the ethoscope is offline or database is not accessible")
            sys.exit(1)
        except ValueError as e:
            logging.error(f"Database query failed for {ethoscope_name}: {e}")
            logging.error("This could mean no experiment is running or backup_filename is not set")
            sys.exit(1)
        except Exception as e:
            logging.error(f"Backup job crashed for {ethoscope_name}: {e}")
            logging.error("Full traceback:", exc_info=True)
            sys.exit(1)

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(sig, frame):
        logging.info("Received shutdown signal. Stopping backup thread...")
        if gbw:
            gbw.stop()
            if gbw.is_alive() or hasattr(gbw, '_started') and gbw._started.is_set():
                gbw.join(timeout=5)
        logging.info("Shutdown complete.")
        # Force exit if graceful shutdown takes too long
        os._exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

@contextmanager
def backup_wrapper_context(results_dir, node_address):
    """Context manager for backup wrapper initialization and cleanup."""
    global gbw
    try:
        logging.info(f"Creating GenericBackupWrapper with results_dir='{results_dir}', node_address='{node_address}'")
        gbw = GenericBackupWrapper(results_dir, node_address)
        logging.info("GenericBackupWrapper created successfully")
        yield gbw
    except Exception as e:
        logging.error(f"Failed to create GenericBackupWrapper: {e}")
        logging.error("Full traceback:", exc_info=True)
        raise
    finally:
        if gbw:
            logging.info("Stopping GenericBackupWrapper...")
            gbw.stop()
            
            # Only try to join if the thread was actually started
            if gbw.is_alive() or hasattr(gbw, '_started') and gbw._started.is_set():
                logging.info("Waiting for GenericBackupWrapper to join (timeout=10s)...")
                gbw.join(timeout=10)
                if gbw.is_alive():
                    logging.warning("GenericBackupWrapper did not stop within timeout!")
                else:
                    logging.info("GenericBackupWrapper stopped successfully")
            else:
                logging.info("GenericBackupWrapper was not started, no need to join")

def main():
    """Main function with improved structure and error handling."""
    
    try:
        # Parse arguments FIRST before any logging
        options = parse_arguments()
        
        # Setup logging configuration IMMEDIATELY
        setup_logging(options.debug)
        
        logging.info("=== ETHOSCOPE BACKUP TOOL STARTING ===")
        logging.info("Command line arguments parsed successfully")
        
        logging.info("Setting up signal handlers...")
        setup_signal_handlers()
        
        logging.info("Loading ethoscope configuration...")
        if options.config_dir:
            config_file = os.path.join(options.config_dir, 'ethoscope.conf')
            cfg = EthoscopeConfiguration(config_file)
        else:
            cfg = EthoscopeConfiguration()
        results_dir = options.results_dir or cfg.content['folders']['results']['path']
        logging.info(f"Results directory: {results_dir}")
        logging.info(f"Node server address: {options.server}")
        logging.info(f"HTTP status port: {options.port}")
        logging.info(f"Safe mode: {options.safe}")
        
        # Parse ethoscope list if provided
        ethoscope_list = parse_ethoscope_list(options.ethoscope)
        if ethoscope_list:
            logging.info(f"Specific ethoscopes requested for backup: {ethoscope_list}")
        else:
            logging.info("Starting in continuous backup mode")
        
        logging.info("Initializing backup wrapper...")
        with backup_wrapper_context(results_dir, options.server) as wrapper:
            if ethoscope_list:
                # Force backup for specific ethoscopes
                logging.info("Starting forced backup mode...")
                force_backup_ethoscopes(ethoscope_list)
                logging.info("Forced backup completed successfully")
            else:
                # Start server mode
                logging.info("Starting backup server in daemon mode...")
                logging.info("Starting backup worker thread...")
                wrapper.start()
                logging.info("Backup worker thread started successfully")
                
                # Give the thread a moment to start and log its initial state
                import time
                time.sleep(2)
                logging.info(f"Backup worker thread status: alive={wrapper.is_alive()}, running={wrapper.is_running()}")
                
                logging.info(f"Starting HTTP status server on port {options.port}...")
                
                # Run bottle server in a separate thread to allow proper signal handling
                server_thread = threading.Thread(
                    target=bottle.run,
                    kwargs={
                        'app': app,
                        'host': '0.0.0.0', 
                        'port': options.port,
                        'quiet': not options.debug
                    },
                    daemon=True
                )
                server_thread.start()
                logging.info(f"HTTP status server started in background thread on port {options.port}")
                
                # Keep main thread alive and responsive to signals
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    logging.info("HTTP server interrupted by user")
                    raise
                
    except KeyboardInterrupt:
        logging.info("=== BACKUP TOOL INTERRUPTED BY USER ===")
        sys.exit(0)
    except Exception as e:
        logging.error(f"=== BACKUP TOOL FATAL ERROR: {e} ===")
        logging.error("Full traceback:", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()