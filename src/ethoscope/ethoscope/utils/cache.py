import os
import time
import json
import logging
import sqlite3
import mysql.connector

class BaseDatabaseMetadataCache:
    """
    Abstract base class for database metadata caching and experiment information storage.
    
    This class provides a clean interface for:
    - Querying database metadata with accurate size calculation
    - Creating and managing cache files based on experiment timestamps
    - Reading cached metadata when database is unavailable
    - Reading old JSON cache files from previous experiments
    - Storing and retrieving experiment information (replaces last_run_info files)
    - Finalizing cache files when experiments end
    
    Subclasses must implement _query_database() for their specific database type.
    
    Key Features:
    - get_cached_metadata(cache_index=0): Read specific cache file by index
    - list_cache_files(): List all available cache files for this device
    - get_cache_summary(): Get summary of all cache files
    - store_experiment_info(): Store experiment details in cache (replaces pickle files)
    - get_last_experiment_info(): Get last experiment info (replaces pickle file reading)
    - has_last_experiment_info(): Check if last experiment info is available
    - get_experiment_history(): Get history of multiple experiments
    """
    
    def __init__(self, db_credentials, device_name="", cache_dir="/ethoscope_data/cache"):
        """
        Initialize the database metadata cache.
        
        Args:
            db_credentials (dict): Database connection credentials
            device_name (str): Name of the device for cache file naming
            cache_dir (str): Directory path for storing cache files
        """
        self.db_credentials = db_credentials
        self.device_name = device_name
        self.cache_dir = cache_dir
        self.current_cache_file_path = None  # Track current active cache file
        os.makedirs(cache_dir, exist_ok=True)
    
    def get_metadata(self, tracking_start_time=None):
        """
        Get database metadata, using cache when appropriate.
        
        Args:
            tracking_start_time: Experiment start timestamp for cache naming
            
        Returns:
            dict: Database metadata including size, table counts, etc.
        """
        cache_file_path = self._get_cache_file_path(tracking_start_time)
        
        # If no cache file path found and we have a current cache file, use it
        if not cache_file_path and self.current_cache_file_path:
            cache_file_path = self.current_cache_file_path
        
        try:
            # Try to query database for fresh metadata
            db_info = self._query_database()
            
            if cache_file_path:
                # Update cache with fresh data
                self._write_cache(cache_file_path, db_info, tracking_start_time)
            
            return db_info
            
        except Exception as e:
            logging.warning(f"Failed to query database: {e}")
            # Fall back to cached data
            return self._read_cache(cache_file_path)
    
    def finalize_cache(self, tracking_start_time):
        """Mark cache file as finalized when experiment ends."""
        cache_file_path = self._get_cache_file_path(tracking_start_time)
        if cache_file_path:
            self._write_cache(cache_file_path, finalise=True)
        
        # Clear current cache file path when session ends
        self.current_cache_file_path = None
    
    def get_cached_metadata(self, cache_index=0):
        """
        Get metadata from cached JSON files without querying the database.
        
        Args:
            cache_index (int): Index of cache file to read:
                              - 0 = most recent cache file (default)
                              - 1 = second most recent cache file  
                              - 2 = third most recent cache file, etc.
        
        Returns:
            dict: Cached metadata including size, table counts, timestamps, etc.
                 Returns empty dict if no cache files are available.
        
        Example:
            # Get most recent cached metadata
            recent_data = cache.get_cached_metadata()
            
            # Get previous experiment's metadata  
            prev_data = cache.get_cached_metadata(cache_index=1)
        """
        return self._read_cache(None, cache_index=cache_index)
    
    def list_cache_files(self):
        """
        List all available cache files for this device.
        
        Returns:
            list: List of dictionaries with cache file information, sorted by date (newest first).
                 Each dict contains: 'path', 'filename', 'modified_time', 'age_days'
        """
        cache_files = self._get_all_cache_files()
        file_info = []
        
        for i, cache_path in enumerate(cache_files):
            try:
                # Get file modification time
                mtime = os.path.getmtime(cache_path)
                age_days = (time.time() - mtime) / (24 * 60 * 60)
                
                # Try to get experiment info from filename
                filename = os.path.basename(cache_path)
                timestamp_match = filename.split('_')[2:5]  # Extract date/time from filename
                experiment_date = '_'.join(timestamp_match) if len(timestamp_match) >= 3 else "unknown"
                
                file_info.append({
                    'index': i,
                    'path': cache_path,
                    'filename': filename,
                    'experiment_date': experiment_date,
                    'modified_time': mtime,
                    'age_days': round(age_days, 1)
                })
            except Exception as e:
                logging.warning(f"Failed to get info for cache file {cache_path}: {e}")
        
        return file_info
    
    def get_cache_summary(self):
        """
        Get a summary of all available cache files for this device.
        
        Returns:
            dict: Summary containing:
                - total_files: Number of cache files
                - newest_date: Date of most recent cache file
                - oldest_date: Date of oldest cache file
                - files: List of cache file info (same as list_cache_files())
        """
        files = self.list_cache_files()
        
        if not files:
            return {
                'total_files': 0,
                'newest_date': None,
                'oldest_date': None,
                'files': []
            }
        
        newest_time = files[0]['modified_time']
        oldest_time = files[-1]['modified_time']
        
        return {
            'total_files': len(files),
            'newest_date': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(newest_time)),
            'oldest_date': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(oldest_time)),
            'files': files
        }
    
    def store_experiment_info(self, tracking_start_time, experiment_info):
        """
        Store experiment information in the cache file (replaces last_run_info functionality).
        
        Args:
            tracking_start_time: Experiment start timestamp for cache naming
            experiment_info (dict): Experiment information containing:
                - date_time: Experiment date/time
                - backup_filename: Database backup filename
                - user: User name who ran the experiment
                - location: Device location
                - result_writer_type: Type of result writer used
                - sqlite_source_path: Path to SQLite database (if applicable)
        """
        cache_file_path = self._get_cache_file_path(tracking_start_time)
        if cache_file_path:
            try:
                # Store current cache file path for future updates
                self.current_cache_file_path = cache_file_path
                
                # Format experiment info for storage
                formatted_info = {
                    "date_time": experiment_info.get("date_time"),
                    "backup_filename": experiment_info.get("backup_filename"),
                    "user": experiment_info.get("user"),
                    "location": experiment_info.get("location"),
                    "result_writer_type": experiment_info.get("result_writer_type"),
                    "sqlite_source_path": experiment_info.get("sqlite_source_path"),
                    "stored_timestamp": time.time()
                }
                
                # Update the cache file with experiment info
                self._write_cache(cache_file_path, experiment_info=formatted_info)
                logging.info(f"Stored experiment info for {self.device_name} in cache")
                
            except Exception as e:
                logging.warning(f"Failed to store experiment info in cache: {e}")
    
    def get_last_experiment_info(self):
        """
        Get information about the last experiment run (replaces last_run_info file).
        
        Returns:
            dict: Last experiment information containing:
                - previous_date_time: Date/time of last experiment
                - previous_backup_filename: Last backup filename  
                - previous_user: Last user name
                - previous_location: Last device location
                - result_writer_type: Type of result writer used
                - sqlite_source_path: SQLite database path (if applicable)
                - cache_file: Path to the cache file containing this info
                
            Always returns a dictionary, empty if no experiment info is available.
        """
        try:
            # Get the most recent cache file data
            recent_data = self.get_cached_metadata(cache_index=0)
            
            if recent_data.get('db_size_bytes', 0) > 0:
                # Check if this cache file has experiment info
                cache_file_path = recent_data.get('cache_file')
                if cache_file_path and os.path.exists(cache_file_path):
                    with open(cache_file_path, 'r') as f:
                        cache_data = json.load(f)
                    
                    experiment_info = cache_data.get('experiment_info', {})
                    if experiment_info:
                        # Return in the format expected by tracking.py (with "previous_" prefix)
                        return {
                            "previous_date_time": experiment_info.get("date_time"),
                            "previous_backup_filename": experiment_info.get("backup_filename"),
                            "previous_user": experiment_info.get("user"),
                            "previous_location": experiment_info.get("location"),
                            "result_writer_type": experiment_info.get("result_writer_type"),
                            "sqlite_source_path": experiment_info.get("sqlite_source_path"),
                            "cache_file": cache_file_path
                        }
            
            # If no experiment info in most recent, try other cache files
            for cache_index in range(1, 5):  # Check up to 5 previous experiments
                try:
                    data = self.get_cached_metadata(cache_index=cache_index)
                    cache_file_path = data.get('cache_file')
                    if cache_file_path and os.path.exists(cache_file_path):
                        with open(cache_file_path, 'r') as f:
                            cache_data = json.load(f)
                        
                        experiment_info = cache_data.get('experiment_info', {})
                        if experiment_info:
                            return {
                                "previous_date_time": experiment_info.get("date_time"),
                                "previous_backup_filename": experiment_info.get("backup_filename"),
                                "previous_user": experiment_info.get("user"),
                                "previous_location": experiment_info.get("location"),
                                "result_writer_type": experiment_info.get("result_writer_type"),
                                "sqlite_source_path": experiment_info.get("sqlite_source_path"),
                                "cache_file": cache_file_path
                            }
                except:
                    continue  # Try next cache file
            
        except Exception as e:
            logging.warning(f"Failed to get last experiment info from cache: {e}")
        
        # Always return a dictionary, even if empty
        return {}
    
    def has_last_experiment_info(self):
        """
        Check if information about the last experiment is available in cache.
        
        Returns:
            bool: True if last experiment info is available, False otherwise
        """
        last_info = self.get_last_experiment_info()
        return bool(last_info.get("previous_backup_filename"))
    
    def get_experiment_history(self, max_experiments=10):
        """
        Get history of multiple previous experiments.
        
        Args:
            max_experiments (int): Maximum number of experiments to retrieve
            
        Returns:
            list: List of experiment info dictionaries, ordered from newest to oldest
        """
        experiments = []
        
        for cache_index in range(max_experiments):
            try:
                data = self.get_cached_metadata(cache_index=cache_index)
                cache_file_path = data.get('cache_file')
                if cache_file_path and os.path.exists(cache_file_path):
                    with open(cache_file_path, 'r') as f:
                        cache_data = json.load(f)
                    
                    experiment_info = cache_data.get('experiment_info', {})
                    if experiment_info:
                        experiment_data = {
                            "index": cache_index,
                            "date_time": experiment_info.get("date_time"),
                            "backup_filename": experiment_info.get("backup_filename"),
                            "user": experiment_info.get("user"),
                            "location": experiment_info.get("location"),
                            "result_writer_type": experiment_info.get("result_writer_type"),
                            "db_size_bytes": data.get("db_size_bytes", 0),
                            "table_counts": data.get("table_counts", {}),
                            "db_status": data.get("db_status", "unknown"),
                            "cache_file": cache_file_path
                        }
                        experiments.append(experiment_data)
                else:
                    break  # No more cache files
            except:
                break  # Error reading cache file
        
        return experiments
    
    def _get_cache_file_path(self, tracking_start_time):
        """Determine cache file path based on experiment timing."""
        if not self.device_name:
            return None
            
        if tracking_start_time:
            # Use provided timestamp
            ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(tracking_start_time))
            cache_filename = f"db_metadata_{ts_str}_{self.device_name}_db.json"
            return os.path.join(self.cache_dir, cache_filename)
        
        # Don't try to read old database metadata when tracking_start_time is None
        # This prevents SQLite databases from using timestamps from previous experiments
        return None
    
    def _query_database(self):
        """
        Abstract method for querying database metadata.
        
        Subclasses must implement this method to provide database-specific
        metadata querying logic.
        
        Returns:
            dict: Database metadata including:
                - db_version (str): Database version string
                - db_size_bytes (int): Database size in bytes
                - table_counts (dict): Table name -> row count mapping
                - last_db_update (float): Timestamp of query
        """
        raise NotImplementedError("Subclasses must implement _query_database()")
    
    def _write_cache(self, cache_file_path, db_info=None, tracking_start_time=None, finalise=False, experiment_info=None):
        """Write or update cache file."""
        try:
            # Read existing cache file or create new one
            if os.path.exists(cache_file_path):
                with open(cache_file_path, 'r') as f:
                    cache_data = json.load(f)
            else:
                if finalise and not experiment_info:
                    logging.warning(f"Cannot finalize non-existent cache file: {cache_file_path}")
                    return
                # Create new cache file
                if tracking_start_time:
                    timestamp_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(tracking_start_time))
                else:
                    timestamp_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(time.time()))
                
                cache_data = {
                    "db_name": self.db_credentials["name"],
                    "device_name": self.device_name,
                    "tracking_start_time": timestamp_str,
                    "creation_timestamp": tracking_start_time or time.time(),
                    "db_status": "tracking"
                }
            
            if finalise:
                # Mark cache file as finalized
                cache_data["db_status"] = "finalised"
                cache_data["finalized_timestamp"] = time.time()
            elif db_info:
                # Update with current database info
                cache_data.update({
                    "last_updated": time.time(),
                    "db_size_bytes": db_info["db_size_bytes"],
                    "table_counts": db_info["table_counts"],
                    "last_db_update": db_info["last_db_update"],
                    "db_version": db_info["db_version"]
                })
            
            # Add experiment information if provided (replaces last_run_info functionality)
            if experiment_info:
                cache_data["experiment_info"] = experiment_info
                # Ensure we have basic cache structure when storing experiment info
                if "db_size_bytes" not in cache_data:
                    cache_data.update({
                        "db_size_bytes": 0,
                        "table_counts": {},
                        "last_db_update": time.time(),
                        "db_version": "Unknown"
                    })
            
            # Write cache file
            with open(cache_file_path, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
        except Exception as e:
            action = "finalize" if finalise else "update"
            logging.warning(f"Failed to {action} cache file {cache_file_path}: {e}")
    
    def _read_cache(self, cache_file_path, cache_index=None):
        """
        Read cache file, or find cache by index if path is None.
        
        Args:
            cache_file_path (str): Specific cache file path, or None to auto-find
            cache_index (int): Index of cache file to read (0=most recent, 1=second most recent, etc.)
                              If None, reads the most recent cache file
        
        Returns:
            dict: Cache data or empty dict if no cache available
        """
        if cache_file_path and os.path.exists(cache_file_path):
            # Read specific cache file
            try:
                return self._read_cache_file(cache_file_path)
            except Exception as e:
                logging.warning(f"Failed to read cache file {cache_file_path}: {e}")
        
        # Find and read cache file by index for this device
        try:
            cache_files = self._get_all_cache_files()
            
            if cache_files:
                # Determine which cache file to read based on index
                if cache_index is None or cache_index == 0:
                    # Default: most recent (index 0)
                    selected_cache = cache_files[0]
                elif cache_index < len(cache_files):
                    # Specific index requested
                    selected_cache = cache_files[cache_index]
                else:
                    # Index out of range, fallback to most recent
                    logging.warning(f"Cache index {cache_index} out of range (max: {len(cache_files)-1}), using most recent")
                    selected_cache = cache_files[0]
                
                logging.info(f"Reading cache file {cache_index or 0}: {os.path.basename(selected_cache)}")
                return self._read_cache_file(selected_cache)
                
        except Exception as e:
            logging.warning(f"Failed to find cache files for {self.device_name}: {e}")
        
        # Return empty data if no cache available
        return {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0}
    
    def _get_all_cache_files(self):
        """
        Get all cache files for this device, sorted by modification time (newest first).
        
        Returns:
            list: List of cache file paths sorted by modification time (newest first)
        """
        cache_files = []
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.endswith(f"_{self.device_name}_db.json") and filename.startswith("db_metadata_"):
                    cache_files.append(os.path.join(self.cache_dir, filename))
            
            # Sort by modification time (newest first)
            cache_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        except Exception as e:
            logging.warning(f"Failed to list cache files: {e}")
        
        return cache_files
    
    def _read_cache_file(self, cache_file_path):
        """
        Read and parse a specific cache file.
        
        Args:
            cache_file_path (str): Path to cache file
            
        Returns:
            dict: Parsed cache data
        """
        with open(cache_file_path, 'r') as f:
            cache_data = json.load(f)
        
        return {
            "db_size_bytes": cache_data.get("db_size_bytes", 0),
            "table_counts": cache_data.get("table_counts", {}),
            "last_db_update": cache_data.get("last_db_update", 0),
            "cache_file": cache_file_path,
            "db_status": cache_data.get("db_status", "unknown"),
            "db_version": cache_data.get("db_version", "Unknown"),
            "creation_timestamp": cache_data.get("creation_timestamp"),
            "tracking_start_time": cache_data.get("tracking_start_time"),
            "finalized_timestamp": cache_data.get("finalized_timestamp"),
            "experiment_info": cache_data.get("experiment_info", {})
        }
    
    def get_database_info(self):
        """
        Get structured database information for the current database.
        
        This is a convenience method that calls get_metadata() and adds
        additional status information.
        
        Returns:
            dict: Database information including:
                - db_name (str): Database name
                - db_size_bytes (int): Database size in bytes
                - table_counts (dict): Table name -> row count mapping
                - last_db_update (float): Timestamp of last update
                - db_status (str): Database status
                - db_version (str): Database version
        """
        try:
            # Use existing get_metadata() method to avoid code duplication
            db_info = self.get_metadata()
            
            # Add additional fields not provided by get_metadata()
            if "db_name" not in db_info:
                db_info["db_name"] = self.db_credentials.get("name", "unknown")
            if "db_status" not in db_info:
                db_info["db_status"] = "active"
            
            return db_info
        except Exception as e:
            logging.warning(f"Failed to get database info: {e}")
            return {
                "db_name": self.db_credentials.get("name", "unknown"),
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": 0,
                "db_status": "error",
                "db_version": "Unknown"
            }
    
    def get_backup_filename(self):
        """
        Get the backup filename for the current database.
        
        Returns:
            str or None: Backup filename if available, None otherwise
        """
        # This is a default implementation that subclasses can override
        # For now, return None as this is database-specific
        return None


class MySQLDatabaseMetadataCache(BaseDatabaseMetadataCache):
    """
    MySQL-specific implementation of database metadata caching.
    
    Handles MySQL/MariaDB database metadata querying including:
    - InnoDB tablespace size calculation
    - MySQL-specific table counting
    - MySQL version detection
    """
    
    def _query_database(self):
        """Query MySQL database for metadata including size and table counts."""
        with mysql.connector.connect(
            host='localhost',
            user=self.db_credentials["user"],
            password=self.db_credentials["password"],
            database=self.db_credentials["name"],
            charset='latin1',
            use_unicode=True,
            connect_timeout=10
        ) as conn:
            cursor = conn.cursor()
            
            # Get actual database file size (to match SQLite file size comparison)
            try:
                cursor.execute("""
                    SELECT SUM(size) * @@innodb_page_size as db_size
                    FROM information_schema.INNODB_SYS_TABLESPACES 
                    WHERE name LIKE %s
                """, (f"{self.db_credentials['name']}/%",))
                result = cursor.fetchone()
                db_size = result[0] if result and result[0] else 0
                
                # If InnoDB method fails or returns 0, use traditional method with overhead
                if db_size == 0:
                    cursor.execute("""
                        SELECT ROUND(SUM(data_length + index_length + data_free)) as db_size 
                        FROM information_schema.tables 
                        WHERE table_schema = %s
                    """, (self.db_credentials["name"],))
                    db_size = cursor.fetchone()[0] or 0
                    
            except mysql.connector.Error:
                # Fallback to traditional method if InnoDB queries fail
                cursor.execute("""
                    SELECT ROUND(SUM(data_length + index_length + data_free)) as db_size 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                """, (self.db_credentials["name"],))
                db_size = cursor.fetchone()[0] or 0
            
            # Get table counts using COUNT(*) for backup percentage calculation
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            
            table_counts = {}
            for table in tables:
                try:
                    # Use COUNT(*) for all tables to match backup percentage calculation expectations
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    
                    result = cursor.fetchone()
                    table_counts[table] = result[0] if result and result[0] is not None else 0
                except mysql.connector.Error:
                    table_counts[table] = 0
            
            # Get database version
            db_version = "Unknown"
            try:
                cursor.execute("SELECT VERSION();")
                result = cursor.fetchone()
                if result and result[0]:
                    db_version = result[0]
            except Exception as e:
                logging.warning(f"Failed to get database version: {e}")

            return {
                "db_version" : db_version,
                "db_size_bytes": int(db_size),
                "table_counts": table_counts,
                "last_db_update": time.time()
            }
    
    def get_backup_filename(self):
        """
        Get the backup filename for the MySQL database from the METADATA table.
        
        Returns:
            str or None: Backup filename if available, None otherwise
        """
        try:
            with mysql.connector.connect(
                host='localhost',
                user=self.db_credentials["user"],
                password=self.db_credentials["password"],
                database=self.db_credentials["name"],
                charset='latin1',
                use_unicode=True,
                connect_timeout=10
            ) as conn:
                cursor = conn.cursor()
                
                # Query the metadata table for the backup filename
                cursor.execute("SELECT DISTINCT value FROM METADATA WHERE field = 'backup_filename' AND value IS NOT NULL")
                result = cursor.fetchone()
                
                if result:
                    backup_filename = result[0]
                    logging.info(f"Found backup filename from metadata: {backup_filename}")
                    return backup_filename
                else:
                    logging.info("No backup filename found in metadata table")
                    return None
                    
        except mysql.connector.Error as e:
            logging.warning(f"Could not retrieve backup filename from metadata table: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error retrieving backup filename: {e}")
            return None

    def get_experimental_metadata(self):
        """
        Extract experimental metadata from MySQL database METADATA table.
        
        Returns:
            dict: Experimental metadata containing user, location, and other info
        """
        try:
            with mysql.connector.connect(
                host='localhost',
                user=self.db_credentials["user"],
                password=self.db_credentials["password"],
                database=self.db_credentials["name"],
                charset='latin1',
                use_unicode=True,
                connect_timeout=10
            ) as conn:
                cursor = conn.cursor()
                
                # Query the metadata table for experimental_info
                cursor.execute("SELECT value FROM METADATA WHERE field = 'experimental_info' AND value IS NOT NULL")
                result = cursor.fetchone()
                
                if result:
                    experimental_info_str = result[0]
                    try:
                        # Parse the experimental_info string - it's a string representation of a dict
                        import ast
                        experimental_info = ast.literal_eval(experimental_info_str)
                        
                        return {
                            "user": experimental_info.get("name", "unknown"),
                            "location": experimental_info.get("location", "unknown"),
                            "code": experimental_info.get("code", ""),
                            "run_id": experimental_info.get("run_id", "")
                        }
                    except (ValueError, SyntaxError) as e:
                        logging.warning(f"Could not parse experimental_info: {e}")
                        return {}
                else:
                    logging.info("No experimental_info found in metadata table")
                    return {}
                    
        except mysql.connector.Error as e:
            logging.warning(f"Could not retrieve experimental metadata from MySQL: {e}")
            return {}
        except Exception as e:
            logging.error(f"Unexpected error retrieving experimental metadata: {e}")
            return {}


class SQLiteDatabaseMetadataCache(BaseDatabaseMetadataCache):
    """
    SQLite-specific implementation of database metadata caching.
    
    Handles SQLite database metadata querying including:
    - File size calculation via os.path.getsize()
    - SQLite-specific table listing from sqlite_master
    - SQLite version detection
    """
    
    def _query_database(self):
        """Query SQLite database for metadata including size and table counts."""
        db_path = self.db_credentials["name"]
        
        # Get database file size
        try:
            db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        except OSError:
            db_size = 0
        
        # Connect to SQLite database and get table information
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Get list of tables (excluding sqlite_* system tables)
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = [row[0] for row in cursor.fetchall()]
            
            # Get table counts
            table_counts = {}
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    result = cursor.fetchone()
                    table_counts[table] = result[0] if result and result[0] is not None else 0
                except sqlite3.Error:
                    table_counts[table] = 0
            
            # Get SQLite version
            db_version = "Unknown"
            try:
                cursor.execute("SELECT sqlite_version()")
                result = cursor.fetchone()
                if result and result[0]:
                    db_version = f"SQLite {result[0]}"
            except Exception as e:
                logging.warning(f"Failed to get SQLite version: {e}")
        
        return {
            "db_version": db_version,
            "db_size_bytes": int(db_size),
            "table_counts": table_counts,
            "last_db_update": time.time()
        }
    
    def get_database_info(self):
        """
        Get structured database information for the SQLite database.
        
        Returns:
            dict: Database information including sqlite_source_path
        """
        try:
            db_info = super().get_database_info()
            # Add SQLite-specific information
            db_info["sqlite_source_path"] = self.db_credentials["name"]
            return db_info
        except Exception as e:
            logging.warning(f"Failed to get SQLite database info: {e}")
            return {
                "db_name": self.db_credentials.get("name", "unknown"),
                "sqlite_source_path": self.db_credentials.get("name", ""),
                "db_size_bytes": 0,
                "table_counts": {},
                "last_db_update": time.time(),
                "db_status": "error",
                "db_version": "SQLite 3.x"
            }
    
    def get_backup_filename(self):
        """
        Get the backup filename for the SQLite database.
        
        For SQLite databases, the backup filename is typically derived from the database path.
        
        Returns:
            str or None: Backup filename if available, None otherwise
        """
        try:
            db_path = self.db_credentials["name"]
            if db_path and os.path.exists(db_path):
                # Extract backup filename from the database path
                # Expected path format: /ethoscope_data/results/{machine_id}/{machine_name}/{date_time}/{backup_filename}
                backup_filename = os.path.basename(db_path)
                if backup_filename.endswith('.db'):
                    logging.info(f"Found SQLite backup filename: {backup_filename}")
                    return backup_filename
                else:
                    logging.warning(f"SQLite database path does not end with .db: {db_path}")
                    return None
            else:
                logging.warning(f"SQLite database path does not exist: {db_path}")
                return None
                
        except Exception as e:
            logging.error(f"Unexpected error retrieving SQLite backup filename: {e}")
            return None

    def get_experimental_metadata(self):
        """
        Extract experimental metadata from SQLite database METADATA table.
        
        Returns:
            dict: Experimental metadata containing user, location, and other info
        """
        try:
            db_path = self.db_credentials["name"]
            if not os.path.exists(db_path):
                logging.warning(f"SQLite database path does not exist: {db_path}")
                return {}
                
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Get experimental_info from METADATA table
                cursor.execute("SELECT value FROM METADATA WHERE field = 'experimental_info'")
                result = cursor.fetchone()
                
                if result:
                    experimental_info_str = result[0]
                    try:
                        # Parse the experimental_info string - it's a string representation of a dict
                        # Remove the outer quotes and evaluate safely
                        import ast
                        experimental_info = ast.literal_eval(experimental_info_str)
                        
                        return {
                            "user": experimental_info.get("name", "unknown"),
                            "location": experimental_info.get("location", "unknown"),
                            "code": experimental_info.get("code", ""),
                            "run_id": experimental_info.get("run_id", "")
                        }
                    except (ValueError, SyntaxError) as e:
                        logging.warning(f"Could not parse experimental_info: {e}")
                        return {}
                else:
                    logging.info("No experimental_info found in metadata table")
                    return {}
                    
        except Exception as e:
            logging.error(f"Unexpected error retrieving experimental metadata: {e}")
            return {}


def create_metadata_cache(db_credentials, device_name="", cache_dir="/ethoscope_data/cache", database_type=None):
    """
    Factory function to create appropriate metadata cache based on database type.
    
    Args:
        db_credentials (dict): Database connection credentials
        device_name (str): Name of the device for cache file naming  
        cache_dir (str): Directory path for storing cache files
        database_type (str): Database type - "MySQL", "SQLite3", or None for auto-detection
        
    Returns:
        BaseDatabaseMetadataCache: Appropriate metadata cache instance
    """
    # Auto-detect database type if not specified
    if database_type is None:
        db_name = db_credentials.get("name", "")
        if db_name.endswith('.db') or db_name.endswith('.sqlite') or db_name.endswith('.sqlite3'):
            database_type = "SQLite3"
        else:
            database_type = "MySQL"
    
    if database_type == "SQLite3":
        return SQLiteDatabaseMetadataCache(db_credentials, device_name, cache_dir)
    else:
        return MySQLDatabaseMetadataCache(db_credentials, device_name, cache_dir)


# Backward compatibility alias
DatabaseMetadataCache = MySQLDatabaseMetadataCache


def get_all_databases_info(device_name, cache_dir="/ethoscope_data/cache"):
    """
    Get comprehensive database information using existing cache methods.
    
    This function leverages existing cache infrastructure to provide a nested structure
    containing information about both SQLite and MariaDB databases:
    - SQLite databases: All historical databases from cache files
    - MariaDB databases: Most recent database (since it gets overwritten)
    
    Args:
        device_name (str): Name of the device (e.g., "ETHOSCOPE_265")
        cache_dir (str): Directory path for cache files
        
    Returns:
        dict: Nested structure with database information:
            {
                "SQLite": {
                    "db_backup_filename": {
                        "filesize": int,
                        "backup_filename": str,
                        "version": str,
                        "path": str,
                        "date": float,
                        "db_status": str,
                        "table_counts": dict,
                        "file_exists": bool
                    }
                },
                "MariaDB": {
                    "db_name": {
                        "table_counts": dict,
                        "backup_filename": str,
                        "version": str,
                        "date": float,
                        "db_status": str,
                        "db_size_bytes": int
                    }
                }
            }
    """
    databases = {"SQLite": {}, "MariaDB": {}}
    
    try:
        # Create one temporary cache instance to access existing methods
        # We'll use dummy credentials since we're only reading cache files
        temp_cache = SQLiteDatabaseMetadataCache(
            {"name": "temp"}, device_name, cache_dir
        )
        
        # Get all cache files for this device
        cache_files = temp_cache._get_all_cache_files()
        
        # Read each cache file only once and categorize by result writer type
        sqlite_experiments = []
        mysql_experiments = []
        
        for cache_file in cache_files:
            try:
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                experiment_info = cache_data.get('experiment_info', {})
                if experiment_info:
                    experiment_data = {
                        "date_time": experiment_info.get("date_time"),
                        "backup_filename": experiment_info.get("backup_filename"),
                        "user": experiment_info.get("user"),
                        "location": experiment_info.get("location"),
                        "result_writer_type": experiment_info.get("result_writer_type"),
                        "db_size_bytes": cache_data.get("db_size_bytes", 0),
                        "table_counts": cache_data.get("table_counts", {}),
                        "db_status": cache_data.get("db_status", "unknown"),
                        "db_version": cache_data.get("db_version", "Unknown"),
                        "db_name": cache_data.get("db_name", ""),
                        "sqlite_source_path": experiment_info.get("sqlite_source_path", "")
                    }
                    
                    # Categorize by result writer type
                    if experiment_info.get("result_writer_type") == "SQLiteResultWriter":
                        sqlite_experiments.append(experiment_data)
                    elif experiment_info.get("result_writer_type") == "MySQLResultWriter":
                        mysql_experiments.append(experiment_data)
                        
            except Exception as e:
                logging.warning(f"Failed to read cache file {cache_file}: {e}")
                continue
        
        # Process SQLite databases (all historical databases)
        for experiment in sqlite_experiments:
            backup_filename = experiment.get("backup_filename", "unknown")
            sqlite_path = experiment.get("sqlite_source_path", "")
            
            # Check if SQLite file exists
            file_exists = False
            if sqlite_path and os.path.exists(sqlite_path):
                file_exists = True
            
            databases["SQLite"][backup_filename] = {
                "filesize": experiment.get("db_size_bytes", 0),
                "backup_filename": backup_filename,
                "version": experiment.get("db_version", "Unknown"),
                "path": sqlite_path,
                "date": experiment.get("date_time", 0),
                "db_status": experiment.get("db_status", "unknown"),
                "table_counts": experiment.get("table_counts", {}),
                "file_exists": file_exists
            }
        
        # Process MariaDB databases (only most recent)
        # Sort by date_time to get the most recent first
        mysql_experiments.sort(key=lambda x: x.get("date_time", 0), reverse=True)
        
        if mysql_experiments:
            # Only take the most recent MariaDB database
            experiment = mysql_experiments[0]
            db_name = experiment.get("db_name", f"{device_name}_db")
            
            databases["MariaDB"][db_name] = {
                "table_counts": experiment.get("table_counts", {}),
                "backup_filename": experiment.get("backup_filename", ""),
                "version": experiment.get("db_version", "Unknown"),
                "date": experiment.get("date_time", 0),
                "db_status": experiment.get("db_status", "unknown"),
                "db_size_bytes": experiment.get("db_size_bytes", 0)
            }
        
    except Exception as e:
        logging.warning(f"Failed to get databases info: {e}")
    
    return databases