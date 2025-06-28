from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
import logging
import argparse
import signal
import sys
import json
import bottle
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
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    if debug:
        logging.info("Debug logging enabled")

def parse_arguments():
    """Parse command line arguments using argparse."""
    parser = argparse.ArgumentParser(description='Ethoscope Backup Tool')
    parser.add_argument('-D', '--debug', action='store_true', 
                       help='Enable debug mode')
    parser.add_argument('-r', '--results-dir', 
                       help='Directory where result files are stored')
    parser.add_argument('-i', '--server', default='localhost',
                       help='Server address for node interrogation')
    parser.add_argument('-e', '--ethoscope', 
                       help='Force backup of specific ethoscope numbers (e.g., 007,010,102)')
    return parser.parse_args()

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
        return
    
    devices = gbw.find_devices()
    device_map = {device['name']: device for device in devices}
    
    for ethoscope_num in ethoscope_list:
        ethoscope_name = f"ETHOSCOPE_{ethoscope_num:03d}"
        logging.info(f"Forcing backup for {ethoscope_name}")
        
        device = device_map.get(ethoscope_name)
        if device is None:
            logging.error(f"{ethoscope_name} is not online or not detected")
            sys.exit(1)
        
        success = gbw.initiate_backup_job(device)
        if not success:
            logging.error(f"Backup failed for {ethoscope_name}")
            sys.exit(1)

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(sig, frame):
        logging.info("Received shutdown signal. Stopping backup thread...")
        if gbw:
            gbw.stop()
            gbw.join(timeout=10)
        logging.info("Shutdown complete.")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

@contextmanager
def backup_wrapper_context(results_dir, node_address):
    """Context manager for backup wrapper initialization and cleanup."""
    global gbw
    try:
        gbw = GenericBackupWrapper(results_dir, node_address)
        yield gbw
    finally:
        if gbw:
            gbw.stop()
            gbw.join(timeout=10)

def main():
    """Main function with improved structure and error handling."""
    try:
        # Parse arguments and setup configuration
        args = parse_arguments()
        setup_logging(args.debug)
        setup_signal_handlers()
        
        cfg = EthoscopeConfiguration()
        results_dir = args.results_dir or cfg.content['folders']['results']['path']
        
        # Parse ethoscope list if provided
        ethoscope_list = parse_ethoscope_list(args.ethoscope)
        
        with backup_wrapper_context(results_dir, args.server) as wrapper:
            if ethoscope_list:
                # Force backup for specific ethoscopes
                force_backup_ethoscopes(ethoscope_list)
            else:
                # Start server mode
                logging.info("Starting backup server...")
                wrapper.start()
                bottle.run(app, host='0.0.0.0', port=8090, quiet=not args.debug)
                
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()