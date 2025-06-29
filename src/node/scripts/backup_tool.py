from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
import logging
import optparse
import signal
import sys
import os
import json
import bottle
import threading
import time
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
    return json.dumps({'status': 'running'}, indent=2)

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
                        'progress': getattr(backup_status, 'progress', {})
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
                     help='Force backup of specific ethoscope numbers (e.g., 007,010,102)')
    parser.add_option('-s', '--safe', dest='safe', default=False,
                     action='store_true', help='Set Safe mode ON (currently unused)')
    parser.add_option('-p', '--port', dest='port', default=8090, type='int',
                     help='Port for HTTP status server (default: 8090)')
    
    (options, args) = parser.parse_args()
    return options

def parse_ethoscope_list(ethoscope_arg):
    """Parse ethoscope numbers from command line argument."""
    if not ethoscope_arg:
        return []
    
    try:
        # Handle single number
        if ',' not in ethoscope_arg:
            return [int(ethoscope_arg)]
        # Handle comma-separated list
        return [int(e.strip()) for e in ethoscope_arg.split(',')]
    except ValueError as e:
        logging.error(f"Invalid ethoscope number format: {ethoscope_arg}")
        sys.exit(1)

def force_backup_ethoscopes(ethoscope_list):
    """Force backup for specified ethoscopes."""
    if not ethoscope_list:
        logging.warning("No ethoscopes specified for forced backup")
        return
    
    logging.info(f"Starting device discovery for {len(ethoscope_list)} ethoscopes...")
    try:
        devices = gbw.find_devices()
        logging.info(f"Found {len(devices)} devices total")
        device_map = {device['name']: device for device in devices}
        
        # Log all discovered devices
        logging.info("=== DISCOVERED DEVICES ===")
        for device_name in sorted(device_map.keys()):
            device_status = device_map[device_name].get('status', 'unknown')
            device_ip = device_map[device_name].get('ip', 'unknown')
            logging.info(f"  {device_name}: status={device_status}, ip={device_ip}")
        logging.info("=== END DEVICE LIST ===")
        
    except Exception as e:
        logging.error(f"Failed to discover devices: {e}")
        sys.exit(1)
    
    for ethoscope_num in ethoscope_list:
        ethoscope_name = f"ETHOSCOPE_{ethoscope_num:03d}"
        logging.info(f"=== PROCESSING {ethoscope_name} ===")
        
        device = device_map.get(ethoscope_name)
        if device is None:
            logging.error(f"{ethoscope_name} is not online or not detected")
            logging.error(f"Available devices: {list(device_map.keys())}")
            sys.exit(1)
        
        logging.info(f"Device found: {device}")
        logging.info(f"Starting backup job for {ethoscope_name}...")
        
        try:
            logging.info(f"Initiating backup job for {ethoscope_name}...")
            success = gbw.initiate_backup_job(device)
            
            if success:
                logging.info(f"=== BACKUP COMPLETED SUCCESSFULLY for {ethoscope_name} ===")
            else:
                logging.error(f"=== BACKUP FAILED for {ethoscope_name} ===")
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