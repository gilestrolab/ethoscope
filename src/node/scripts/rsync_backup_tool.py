import json
import logging
import optparse
import traceback
import sys
import signal
import time
import os
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper, UnifiedRsyncBackupClass
from ethoscope_node.utils.configuration import EthoscopeConfiguration

gbw = None  # This will be initialized later

# Global cache for file enumeration with background refresh
file_enumeration_cache = {
    'sqlite': {},  # device_id -> cached data
    'videos': {},  # device_id -> cached data
    'cache_ttl': 300,  # 5 minutes cache TTL
    'last_refresh': {},  # device_id -> last refresh timestamp
    'refresh_lock': threading.Lock(),
    'background_refresh_active': {}  # device_id -> boolean to prevent multiple refreshes
}

class RequestHandler(BaseHTTPRequestHandler):
    def _send_response(self, content):
        """Helper function to send a JSON response"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(content).encode('utf-8'))

    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/':
            self._send_response({'status': 'running', 'last_backup': gbw.last_backup})
        elif self.path == '/status':
            with gbw._lock:
                status_copy = gbw.backup_status.copy()
            # Convert BackupStatus objects to dictionaries for JSON serialization
            status_dict = {key: asdict(value) for key, value in status_copy.items()}
            
            # Enhance with individual file information  
            enhanced_status = self._enhance_backup_status_with_files(status_dict)
            
            # Add disk usage summary
            disk_usage_summary = self._calculate_disk_usage_summary(enhanced_status)
            response = {
                'devices': enhanced_status,
                'disk_usage_summary': disk_usage_summary
            }
            self._send_response(response)
        elif self.path.startswith('/status/'):
            # Handle device-specific status requests
            device_id = self.path.split('/')[-1]
            self._handle_device_status(device_id)
        else:
            self.send_error(404, "File not found")
    
    def _handle_device_status(self, device_id):
        """Handle device-specific status requests - much more efficient than full status"""
        try:
            with gbw._lock:
                status_copy = gbw.backup_status.copy()
            
            # Check if the device exists
            if device_id not in status_copy:
                self._send_response({
                    'error': f'Device {device_id} not found',
                    'device_id': device_id
                })
                return
            
            # Convert only the specific device's BackupStatus to dictionary
            device_status = asdict(status_copy[device_id])
            
            # Enhance with individual file information for this device only
            enhanced_device_status = self._enhance_device_backup_status_with_files(device_id, device_status)
            
            response = {
                'device': enhanced_device_status,
                'device_id': device_id
            }
            self._send_response(response)
            
        except Exception as e:
            logging.error(f"Error handling device status for {device_id}: {e}")
            self._send_response({
                'error': f'Internal error processing device {device_id}',
                'device_id': device_id
            })
    
    def _enhance_device_backup_status_with_files(self, device_id, device_status):
        """Enhance backup status with individual file information for a single device"""
        synced_info = device_status.get('synced', {})
        
        # Add individual file information for this device only
        device_status['individual_files'] = {
            'sqlite': self._enumerate_sqlite_files(device_id, synced_info.get('results', {})),
            'videos': self._enumerate_video_files(device_id, synced_info.get('videos', {}))
        }
        
        # Update the backup_types structure to include individual file counts
        if 'backup_types' not in device_status:
            device_status['backup_types'] = {}
        
        # Update SQLite information with individual files
        sqlite_files = device_status['individual_files']['sqlite']
        if sqlite_files['count'] > 0:
            device_status['backup_types']['sqlite'] = {
                'available': True,
                'status': 'completed',
                'last_backup': synced_info.get('results', {}).get('last_sync_time', None),
                'processing': False,
                'message': 'Backup completed successfully',
                'size': sqlite_files['total_size'],
                'size_human': self._format_bytes(sqlite_files['total_size']),
                'files': sqlite_files['count'],
                'directory': synced_info.get('results', {}).get('local_path', ''),
                'individual_files': sqlite_files['files']
            }
        else:
            device_status['backup_types']['sqlite'] = {
                'available': False,
                'status': 'not_available',
                'last_backup': None,
                'size': 0,
                'files': 0
            }
        
        # Update Video information with individual files
        video_files = device_status['individual_files']['videos']
        if video_files['count'] > 0:
            device_status['backup_types']['video'] = {
                'available': True,
                'status': 'completed',
                'last_backup': synced_info.get('videos', {}).get('last_sync_time', None),
                'processing': False,
                'message': 'Backup completed successfully',
                'size': video_files['total_size'],
                'size_human': self._format_bytes(video_files['total_size']),
                'files': video_files['count'],
                'directory': synced_info.get('videos', {}).get('local_path', ''),
                'individual_files': video_files['files']
            }
        else:
            device_status['backup_types']['video'] = {
                'available': False,
                'status': 'not_available',
                'last_backup': None,
                'size': 0,
                'files': 0,
                'size_human': '0 B'
            }
        
        # Add MySQL backup information if available
        # MySQL backups are handled by backup_tool.py service, so we inherit existing status
        if 'mysql' not in device_status.get('backup_types', {}):
            device_status['backup_types']['mysql'] = {
                'available': False,
                'status': 'handled_by_mysql_service',
                'last_backup': None,
                'processing': False,
                'message': 'MySQL backups handled by separate backup_tool.py service',
                'size': 0,
                'files': 0,
                'size_human': '0 B'
            }
        
        return device_status
    
    def _calculate_disk_usage_summary(self, status_dict):
        """Calculate overall disk usage summary from device statuses"""
        total_results_bytes = 0
        total_videos_bytes = 0
        total_results_files = 0
        total_videos_files = 0
        
        for device_id, device_status in status_dict.items():
            synced_info = device_status.get('synced', {})
            
            # Results data
            results_info = synced_info.get('results', {})
            if isinstance(results_info, dict):
                total_results_bytes += results_info.get('disk_usage_bytes', 0)
                total_results_files += results_info.get('local_files', 0)
            
            # Videos data
            videos_info = synced_info.get('videos', {})
            if isinstance(videos_info, dict):
                total_videos_bytes += videos_info.get('disk_usage_bytes', 0)
                total_videos_files += videos_info.get('local_files', 0)
        
        # Format totals
        def format_bytes(bytes_value):
            if bytes_value == 0:
                return "0 B"
            units = ['B', 'KB', 'MB', 'GB', 'TB']
            unit_index = 0
            size = float(bytes_value)
            while size >= 1024 and unit_index < len(units) - 1:
                size /= 1024
                unit_index += 1
            if unit_index == 0:
                return f"{int(size)} {units[unit_index]}"
            else:
                return f"{size:.1f} {units[unit_index]}"
        
        return {
            'results': {
                'total_files': total_results_files,
                'total_size_bytes': total_results_bytes,
                'total_size_human': format_bytes(total_results_bytes)
            },
            'videos': {
                'total_files': total_videos_files,
                'total_size_bytes': total_videos_bytes,
                'total_size_human': format_bytes(total_videos_bytes)
            },
            'combined': {
                'total_files': total_results_files + total_videos_files,
                'total_size_bytes': total_results_bytes + total_videos_bytes,
                'total_size_human': format_bytes(total_results_bytes + total_videos_bytes)
            }
        }
    
    def _enhance_backup_status_with_files(self, status_dict):
        """Enhance backup status with individual file information"""
        for device_id, device_status in status_dict.items():
            synced_info = device_status.get('synced', {})
            
            # Add individual file information
            device_status['individual_files'] = {
                'sqlite': self._enumerate_sqlite_files(device_id, synced_info.get('results', {})),
                'videos': self._enumerate_video_files(device_id, synced_info.get('videos', {}))
            }
            
            # Update the backup_types structure to include individual file counts
            if 'backup_types' not in device_status:
                device_status['backup_types'] = {}
            
            # Update SQLite information with individual files
            sqlite_files = device_status['individual_files']['sqlite']
            if sqlite_files['count'] > 0:
                device_status['backup_types']['sqlite'] = {
                    'available': True,
                    'status': 'completed',
                    'last_backup': synced_info.get('results', {}).get('last_sync_time', None),
                    'processing': False,
                    'message': 'Backup completed successfully',
                    'size': sqlite_files['total_size'],
                    'size_human': self._format_bytes(sqlite_files['total_size']),
                    'files': sqlite_files['count'],
                    'directory': synced_info.get('results', {}).get('local_path', ''),
                    'individual_files': sqlite_files['files']
                }
            else:
                device_status['backup_types']['sqlite'] = {
                    'available': False,
                    'status': 'not_available',
                    'last_backup': None,
                    'size': 0,
                    'files': 0
                }
            
            # Update Video information with individual files
            video_files = device_status['individual_files']['videos']
            if video_files['count'] > 0:
                device_status['backup_types']['video'] = {
                    'available': True,
                    'status': 'completed',
                    'last_backup': synced_info.get('videos', {}).get('last_sync_time', None),
                    'processing': False,
                    'message': 'Backup completed successfully',
                    'size': video_files['total_size'],
                    'size_human': self._format_bytes(video_files['total_size']),
                    'files': video_files['count'],
                    'directory': synced_info.get('videos', {}).get('local_path', ''),
                    'individual_files': video_files['files']
                }
            else:
                device_status['backup_types']['video'] = {
                    'available': False,
                    'status': 'not_available',
                    'last_backup': None,
                    'size': 0,
                    'files': 0,
                    'size_human': '0 B'
                }
            
            # Add MySQL backup information if available
            # MySQL backups are handled by backup_tool.py service, so we inherit existing status
            if 'mysql' not in device_status.get('backup_types', {}):
                device_status['backup_types']['mysql'] = {
                    'available': False,
                    'status': 'handled_by_mysql_service',
                    'last_backup': None,
                    'processing': False,
                    'message': 'MySQL backups handled by separate backup_tool.py service',
                    'size': 0,
                    'files': 0,
                    'size_human': '0 B'
                }
        
        return status_dict
    
    def _get_cached_file_enumeration(self, cache_type, device_id, directory_path):
        """Get cached file enumeration, always return existing cache or empty result"""
        with file_enumeration_cache['refresh_lock']:
            cache = file_enumeration_cache[cache_type].get(device_id)
            current_time = time.time()
            
            # If no cache exists, return empty result and trigger background refresh
            if not cache:
                self._trigger_background_refresh(cache_type, device_id, directory_path)
                return {
                    'count': 0,
                    'total_size': 0,
                    'total_size_human': '0 B',
                    'files': []
                }
            
            # Check if cache needs refresh (but don't block - serve existing cache)
            cache_age = current_time - cache['timestamp']
            if cache_age > file_enumeration_cache['cache_ttl']:
                # Cache is stale, trigger background refresh but serve existing data
                self._trigger_background_refresh(cache_type, device_id, directory_path)
            
            # Always return cached data (even if stale)
            return cache['data']
    
    def _trigger_background_refresh(self, cache_type, device_id, directory_path):
        """Trigger background refresh if not already running"""
        refresh_key = f"{cache_type}_{device_id}"
        
        # Check if refresh is already running for this device/type
        if file_enumeration_cache['background_refresh_active'].get(refresh_key, False):
            return
        
        # Mark refresh as active
        file_enumeration_cache['background_refresh_active'][refresh_key] = True
        
        # Start background thread
        refresh_thread = threading.Thread(
            target=self._background_refresh_worker,
            args=(cache_type, device_id, directory_path, refresh_key),
            daemon=True
        )
        refresh_thread.start()
    
    def _background_refresh_worker(self, cache_type, device_id, directory_path, refresh_key):
        """Background worker to refresh file enumeration cache"""
        try:
            logging.info(f"Background refresh started for {cache_type} files on device {device_id}")
            
            # Perform the expensive filesystem operation
            if cache_type == 'sqlite':
                data = self._enumerate_files_from_filesystem(directory_path, '.db')
            else:  # videos
                video_extensions = ('.mp4', '.avi', '.h264', '.mkv', '.mov', '.webm')
                data = self._enumerate_files_from_filesystem(directory_path, video_extensions)
            
            # Update cache with new data
            with file_enumeration_cache['refresh_lock']:
                file_enumeration_cache[cache_type][device_id] = {
                    'timestamp': time.time(),
                    'directory_path': directory_path,
                    'data': data
                }
                file_enumeration_cache['last_refresh'][device_id] = time.time()
            
            logging.info(f"Background refresh completed for {cache_type} files on device {device_id}: {data['count']} files, {data['total_size_human']}")
            
        except Exception as e:
            logging.error(f"Background refresh failed for {cache_type} files on device {device_id}: {e}")
        finally:
            # Mark refresh as completed
            with file_enumeration_cache['refresh_lock']:
                file_enumeration_cache['background_refresh_active'][refresh_key] = False
    
    def _enumerate_files_from_filesystem(self, directory_path, extensions):
        """Perform actual filesystem enumeration (expensive operation)"""
        files = []
        
        if not directory_path or not os.path.exists(directory_path):
            return {
                'count': 0,
                'total_size': 0,
                'total_size_human': '0 B',
                'files': []
            }
        
        try:
            # Normalize extensions to tuple for endswith check
            if isinstance(extensions, str):
                extensions = (extensions,)
            
            for root, dirs, filenames in os.walk(directory_path):
                for filename in filenames:
                    if filename.lower().endswith(extensions):
                        file_path = os.path.join(root, filename)
                        try:
                            file_stat = os.stat(file_path)
                            files.append({
                                'name': filename,
                                'path': file_path,
                                'relative_path': os.path.relpath(file_path, directory_path),
                                'size': file_stat.st_size,
                                'size_human': self._format_bytes(file_stat.st_size),
                                'modified': file_stat.st_mtime,
                                'status': 'backed_up'
                            })
                        except OSError as e:
                            logging.warning(f"Could not stat file {file_path}: {e}")
                            continue
        except OSError as e:
            logging.error(f"Could not scan directory {directory_path}: {e}")
        
        return {
            'count': len(files),
            'total_size': sum(f['size'] for f in files),
            'total_size_human': self._format_bytes(sum(f['size'] for f in files)),
            'files': sorted(files, key=lambda x: x['modified'], reverse=True)
        }
    
    def _enumerate_sqlite_files(self, device_id, results_info):
        """Enumerate individual SQLite database files with background refresh caching"""
        # Use directory from results_info, or construct path from device_id
        results_path = results_info.get('local_path', '')
        if not results_path:
            results_path = results_info.get('directory', '')
        
        # If still no path, construct from device_id and known structure
        if not results_path and device_id:
            results_path = f"/ethoscope_data/results/{device_id}"
        
        # Always get from cache (triggers background refresh if needed)
        return self._get_cached_file_enumeration('sqlite', device_id, results_path)
    
    def _enumerate_video_files(self, device_id, videos_info):
        """Enumerate individual video files with background refresh caching"""
        # Use directory from videos_info, or construct path from device_id
        videos_path = videos_info.get('local_path', '')
        if not videos_path:
            videos_path = videos_info.get('directory', '')
        
        # If still no path, construct from device_id and known structure
        if not videos_path and device_id:
            videos_path = f"/ethoscope_data/videos/{device_id}"
        
        # Always get from cache (triggers background refresh if needed)
        return self._get_cached_file_enumeration('videos', device_id, videos_path)
    
    def _format_bytes(self, bytes_value):
        """Format bytes in human readable format"""
        if bytes_value == 0:
            return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        size = float(bytes_value)
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        else:
            return f"{size:.1f} {units[unit_index]}"

def signal_handler(sig, frame):
    logging.info("Received shutdown signal. Stopping backup thread...")
    gbw.stop()  # Signal the thread to stop
    gbw.join(timeout=10)  # Wait for the thread to finish
    logging.info("Shutdown complete.")
    sys.exit(0)

class UnifiedBackupWrapper(GenericBackupWrapper):
    """
    Extended backup wrapper that uses UnifiedRsyncBackupClass for rsync-based backups.
    """
    
    def __init__(self, results_dir: str, videos_dir: str, node_address: str, 
                 backup_results: bool = True, backup_videos: bool = True, 
                 max_threads: int = None):
        # Initialize with results_dir for base compatibility
        super().__init__(results_dir, node_address, video=False, max_threads=max_threads)
        
        # Override the video flag behavior since we're handling both
        self._is_video_backup = False  # We handle both, not just video
        self._is_unified_backup = True
        
        # Store unified backup configuration
        self._results_dir = results_dir
        self._videos_dir = videos_dir
        self._backup_results = backup_results
        self._backup_videos = backup_videos
        
        self._logger = logging.getLogger(f"UnifiedBackupWrapper")
        self._logger.propagate = True
    
    def initiate_backup_job(self, device_info: dict) -> bool:
        """
        Override to use UnifiedRsyncBackupClass instead of BackupClass or VideoBackupClass.
        
        Args:
            device_info: Device information dictionary
            
        Returns:
            bool: True if backup completed successfully
        """
        device_id = device_info.get('id', 'unknown')
        device_name = device_info.get('name', 'unknown')
        device_ip = device_info.get('ip', 'unknown')
        device_status = device_info.get('status', 'unknown')
        
        job_start_time = time.time()
        
        try:
            backup_types = []
            if self._backup_results:
                backup_types.append("results")
            if self._backup_videos:
                backup_types.append("videos")
            
            self._logger.info(f"=== INITIATING UNIFIED BACKUP JOB for {device_name} (ID: {device_id}) ===")
            self._logger.info(f"Device details: IP={device_ip}, Status={device_status}, Backup types={backup_types}")
            
            # Create unified backup job
            self._logger.info(f"Creating UnifiedRsyncBackupClass for device {device_id}")
            backup_job = UnifiedRsyncBackupClass(
                device_info, 
                self._results_dir, 
                self._videos_dir,
                backup_results=self._backup_results,
                backup_videos=self._backup_videos
            )
            
            self._logger.info(f"Unified backup job object created successfully for device {device_id}")
            
            # Initialize backup status
            self._logger.info(f"Initializing backup status for device {device_id}")
            self._initialize_backup_status(device_id, device_info)
            
            # Perform backup with real-time status updates
            self._logger.info(f"Starting unified backup execution for device {device_id}")
            success = self._execute_backup_job(device_id, backup_job)
            
            job_elapsed_time = time.time() - job_start_time
            
            # Update final status
            self._logger.info(f"Finalizing backup status for device {device_id} (success={success}, elapsed={job_elapsed_time:.1f}s)")
            self._finalize_backup_status(device_id, backup_job, success)
            
            if success:
                self._logger.info(f"=== UNIFIED BACKUP JOB COMPLETED SUCCESSFULLY for {device_name} in {job_elapsed_time:.1f}s ===")
            else:
                self._logger.error(f"=== UNIFIED BACKUP JOB FAILED for {device_name} after {job_elapsed_time:.1f}s ===")
            
            return success
            
        except Exception as e:
            job_elapsed_time = time.time() - job_start_time
            self._logger.error(f"=== UNIFIED BACKUP JOB CRASHED for {device_name} after {job_elapsed_time:.1f}s ===")
            self._logger.error(f"Unified backup job failed for device {device_id}: {e}")
            self._logger.error("Full traceback:", exc_info=True)
            self._handle_backup_failure(device_id, str(e))
            return False

def main():
    global gbw

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logging.getLogger().setLevel(logging.INFO)

    try:
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, 
                         help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-i", "--server", dest="server", default="localhost", 
                         help="The server on which the node is running will be interrogated first for the device list")
        parser.add_option("-r", "--results-dir", dest="results_dir", 
                         help="Destination directory for results/database files")
        parser.add_option("-v", "--videos-dir", dest="videos_dir", 
                         help="Destination directory for video files")
        parser.add_option("-s", "--safe", dest="safe", default=False, 
                         help="Set Safe mode ON", action="store_true")
        parser.add_option("-e", "--ethoscope", dest="ethoscope", 
                         help="Force backup of given ethoscope number (eg: 007)")
        
        # Unified backup options
        parser.add_option("--unified", dest="unified", default=True,
                         help="Use unified rsync for both results and videos (default)", action="store_true")
        parser.add_option("--results-only", dest="results_only", default=False,
                         help="Backup only database/results files", action="store_true")
        parser.add_option("--videos-only", dest="videos_only", default=False,
                         help="Backup only video files", action="store_true")
        parser.add_option("-c", "--configuration", dest="config_dir",
                         help="Path to configuration directory (default: /etc/ethoscope)")

        (options, args) = parser.parse_args()
        option_dict = vars(options)
        
        # Initialize configuration
        if option_dict["config_dir"]:
            config_file = os.path.join(option_dict["config_dir"], 'ethoscope.conf')
            CFG = EthoscopeConfiguration(config_file)
        else:
            CFG = EthoscopeConfiguration()
        
        # Configuration
        RESULTS_DIR = option_dict["results_dir"] or CFG.content['folders']['results']['path']
        VIDEOS_DIR = option_dict["videos_dir"] or CFG.content['folders']['video']['path']
        SAFE_MODE = option_dict["safe"]
        DEBUG = option_dict["debug"]
        ETHO_TO_BACKUP = option_dict["ethoscope"]
        NODE_ADDRESS = option_dict["server"]
        
        # Backup type selection
        BACKUP_RESULTS = not option_dict["videos_only"]  # Default True unless videos-only
        BACKUP_VIDEOS = not option_dict["results_only"]  # Default True unless results-only
        
        # Ensure at least one backup type is selected
        if not (BACKUP_RESULTS or BACKUP_VIDEOS):
            print("Error: At least one backup type must be selected")
            sys.exit(1)

        if DEBUG:
            logging.basicConfig()
            logging.getLogger().setLevel(logging.DEBUG)
            logging.info("Logging using DEBUG SETTINGS")

        backup_types = []
        if BACKUP_RESULTS:
            backup_types.append("results")
        if BACKUP_VIDEOS:
            backup_types.append("videos")
        
        logging.info(f"Starting unified rsync backup for: {', '.join(backup_types)}")
        logging.info(f"Results directory: {RESULTS_DIR}")
        logging.info(f"Videos directory: {VIDEOS_DIR}")

        # Start the unified backup wrapper
        gbw = UnifiedBackupWrapper(
            RESULTS_DIR, 
            VIDEOS_DIR, 
            NODE_ADDRESS, 
            backup_results=BACKUP_RESULTS,
            backup_videos=BACKUP_VIDEOS
        )

        if ETHO_TO_BACKUP:
            # We have provided an ethoscope or a comma separated list of ethoscopes to backup
            try:
                ETHO_TO_BACKUP_LIST = [int(ETHO_TO_BACKUP)]
            except ValueError:
                ETHO_TO_BACKUP_LIST = [int(e) for e in ETHO_TO_BACKUP.split(",")]

            for ethoscope in ETHO_TO_BACKUP_LIST:
                print(f"Forcing unified backup for ethoscope %03d" % ethoscope)

                bj = None
                for device in gbw.find_devices():
                    if device['name'] == ("ETHOSCOPE_%03d" % ethoscope):
                        # Validate device has SQLite database before attempting backup
                        # Check both old format (database_info) and new format (databases.SQLite)
                        has_sqlite = False
                        
                        # Check new format first
                        databases = device.get("databases", {})
                        sqlite_databases = databases.get("SQLite", {})
                        if sqlite_databases and len(sqlite_databases) > 0:
                            has_sqlite = True
                            print(f"SQLite databases found (new format): {list(sqlite_databases.keys())}")
                        
                        # Fallback to old format
                        if not has_sqlite:
                            database_info = device.get("database_info", {})
                            active_type = database_info.get("active_type", "none")
                            sqlite_exists = database_info.get("sqlite", {}).get("exists", False)
                            if sqlite_exists or active_type == "sqlite":
                                has_sqlite = True
                                print(f"SQLite database found (old format): active_type={active_type}")
                        
                        if not has_sqlite:
                            print(f"Skipping ETHOSCOPE_%03d - no SQLite database found" % ethoscope)
                            print(f"This device should be backed up by the MariaDB backup service instead")
                            exit("ETHOSCOPE_%03d has no SQLite database for rsync backup" % ethoscope)
                        
                        print(f"SQLite database validated for ETHOSCOPE_%03d - starting backup..." % ethoscope)
                        bj = gbw.initiate_backup_job(device)
                if bj is None:
                    exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)
        else:
            # Start the HTTP server
            server_address = ('', 8093)  # Serve on all interfaces at port 8093 (different from video backup)
            httpd = HTTPServer(server_address, RequestHandler)

            try:
                logging.info("Starting unified backup HTTP server on port 8093...")
                gbw.start()
                httpd.serve_forever()
            except KeyboardInterrupt:
                logging.info("Stopping unified backup server cleanly")
                gbw.stop()
                gbw.join(timeout=10)

    except Exception as e:
        logging.error(traceback.format_exc())

if __name__ == '__main__':
    main()