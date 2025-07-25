
import os
import time
import logging
import traceback
import sqlite3
from .base import BaseAsyncSQLWriter, BaseResultWriter
from .helpers import Null

class AsyncSQLiteWriter(BaseAsyncSQLWriter):
    """
    Asynchronous SQLite database writer running in a separate process.
    
    Similar to AsyncMySQLWriter but for SQLite databases. Uses specific
    PRAGMA settings for optimal performance with single-writer pattern.
    Each experiment creates a unique database file, preserving historical data.
    
    Attributes:
        _pragmas (dict): SQLite PRAGMA settings for performance optimization
        _db_name (str): Path to SQLite database file
    """
    
    _database_type = "SQLite3"
    _pragmas = {"temp_store": "MEMORY",
                "journal_mode": "WAL",
                "locking_mode":  "NORMAL",
                "busy_timeout": "30000",
                "synchronous": "NORMAL"}
                
    def __init__(self, db_name, queue, erase_old_db=True):
        """
        Initialize the async SQLite writer.
        
        Args:
            db_name (str): Path to SQLite database file (typically unique per experiment)
            queue (multiprocessing.Queue): Queue for receiving SQL commands
            erase_old_db (bool): Whether to delete existing database (typically False since 
                                filenames are unique per experiment)
        """
        super(AsyncSQLiteWriter, self).__init__(queue, erase_old_db)
        self._db_name = db_name
        
    def _get_connection(self):
        """
        Create SQLite database connection.
        
        Returns:
            sqlite3.Connection: Database connection object
            
        Raises:
            Exception: If SQLite connection fails
        """
        try:
            db = sqlite3.connect(self._db_name, timeout=30.0)
            return db
        except sqlite3.Error as e:
            raise Exception(f"Failed to connect to SQLite database {self._db_name}: {e}")
    
    # Implementation of abstract methods from BaseAsyncSQLWriter
    def _initialize_database(self):
        """Initialize SQLite database setup - delete file and set PRAGMAs if needed."""
        if self._erase_old_db:
            try:
                os.remove(self._db_name)
            except:
                pass
            
            # Ensure directory exists before creating database connection
            db_dir = os.path.dirname(self._db_name)
            if db_dir:  # Only create directory if path contains a directory component
                os.makedirs(db_dir, exist_ok=True)
                logging.info(f"Created SQLite directory: {db_dir}")
            
            conn = self._get_connection()
            c = conn.cursor()
            logging.info("Setting DB parameters")
            for k,v in list(self._pragmas.items()):
                command = "PRAGMA %s = %s" %(str(k), str(v))
                c.execute(command)
            conn.close()
    
    def _get_db_type_name(self):
        """Return database type name for logging."""
        return "SQLite"
    
    def _should_retry_on_error(self, error):
        """
        Determine if SQLite writer should continue after an error.
        
        Retries on transient errors like database locks, but stops on critical errors.
        """
        import sqlite3
        
        # Retry on transient SQLite errors
        if isinstance(error, sqlite3.OperationalError):
            error_msg = str(error).lower()
            # Retry on database lock, busy, or temporary errors
            if any(keyword in error_msg for keyword in ['locked', 'busy', 'cannot commit']):
                logging.warning(f"SQLite transient error, will retry: {error}")
                return True
        
        # Stop on all other errors (corrupted database, disk full, etc.)
        logging.error(f"SQLite critical error, stopping writer: {error}")
        return False



class SQLiteResultWriter(BaseResultWriter):
    """
    SQLite-specific result writer.
    
    Extends BaseResultWriter with SQLite-specific modifications including:
    - Use of AsyncSQLiteWriter instead of AsyncMySQLWriter
    - NULL instead of 0 for auto-increment fields
    - Removal of MySQL-specific table options
    - Automatic placeholder conversion from MySQL (%s) to SQLite (?)
    """
    _description = {
        "overview": "SQLite result writer - stores tracking data to local SQLite database file using consistent directory structure. Each experiment creates a unique file, preserving historical data. Compatible with rsync-based backups. Supports sensor data collection when sensors are available.",
        "arguments": [
            {"name": "take_frame_shots", "description": "Save periodic frame snapshots", "type": "boolean", "default": True},
            {"name": "make_dam_like_table", "description": "Create DAM-compatible activity summary table", "type": "boolean", "default": False}
        ]
    }
    
    _database_type = "SQLite3"
    _async_writing_class = AsyncSQLiteWriter
    _null = Null()
    
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=False, 
                 take_frame_shots=False, erase_old_db=True, sensor=None, *args, **kwargs):
        """
        Initialize SQLite result writer.
        
        Note: DAM-like tables are disabled by default for SQLite.
        Args:
            sensor: Optional sensor object for environmental data collection
        """
        # SQLite-specific parameter overrides
        # Remove any conflicting arguments from kwargs to avoid duplicate argument errors
        kwargs.pop('erase_old_db', None)
        
        # SQLite databases are unique per experiment, don't erase them
        
        # Call parent initialization with all common logic
        super(SQLiteResultWriter, self).__init__(db_credentials, rois, metadata, make_dam_like_table, 
                                                 take_frame_shots, erase_old_db, sensor, **kwargs)
    
    def get_last_timestamp(self):
        """
        Connects to the database and retrieves the last timestamp
        from all ROI tables with enhanced error handling and validation.
        Returns:
            int: The last timestamp in milliseconds, or 0 if not found.
        """
        db_path = self._db_credentials["name"]
        
        # Check if database file exists
        if not os.path.exists(db_path):
            logging.error(f"SQLite database file does not exist: {db_path}")
            return 0
        
        # Check if database file is readable and not empty
        try:
            file_size = os.path.getsize(db_path)
            if file_size == 0:
                logging.error(f"SQLite database file is empty: {db_path}")
                return 0
        except OSError as e:
            logging.error(f"Cannot access SQLite database file {db_path}: {e}")
            return 0
        
        try:
            # Use a timeout to prevent hanging on locked databases
            db = sqlite3.connect(db_path, timeout=30.0)
            cursor = db.cursor()
            
            # Check if database has the expected structure by looking for required tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ROI_%'")
            existing_roi_tables = {row[0] for row in cursor.fetchall()}
            
            if not existing_roi_tables:
                logging.warning(f"No ROI tables found in SQLite database: {db_path}")
                cursor.close()
                db.close()
                return 0
            
            last_ts = 0
            successful_queries = 0
            
            for roi in self._rois:
                table_name = f"ROI_{roi.idx}"
                
                # Check if this specific ROI table exists
                if table_name not in existing_roi_tables:
                    logging.warning(f"ROI table {table_name} not found in database, skipping")
                    continue
                
                try:
                    # Validate table structure by checking for required columns
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = [col[1] for col in cursor.fetchall()]  # col[1] is the column name
                    
                    if 't' not in columns:
                        logging.error(f"Table {table_name} missing required 't' column")
                        continue
                    
                    # Get the maximum timestamp from this table
                    cursor.execute(f"SELECT MAX(t) FROM {table_name} WHERE t IS NOT NULL")
                    result = cursor.fetchone()
                    
                    if result and result[0] is not None:
                        table_max_ts = int(result[0])  # Ensure it's an integer
                        last_ts = max(last_ts, table_max_ts)
                        successful_queries += 1
                        logging.debug(f"Table {table_name} max timestamp: {table_max_ts}")
                    else:
                        logging.info(f"Table {table_name} has no data or null timestamps")
                        
                except sqlite3.Error as table_err:
                    logging.error(f"Error querying table {table_name}: {table_err}")
                    continue
            
            cursor.close()
            db.close()
            
            if successful_queries == 0:
                logging.warning("No ROI tables could be successfully queried")
                return 0
            
            logging.info(f"Successfully retrieved last timestamp {last_ts} from {successful_queries} ROI table(s)")
            return last_ts
            
        except sqlite3.DatabaseError as db_err:
            logging.error(f"SQLite database error accessing {db_path}: {db_err}")
            return 0
        except sqlite3.Error as err:
            logging.error(f"SQLite error getting last timestamp from {db_path}: {err}")
            return 0
        except Exception as e:
            logging.error(f"Unexpected error getting last timestamp from SQLite {db_path}: {e}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            return 0

    def _create_async_writer(self, db_credentials, erase_old_db, **kwargs):
        """Create SQLite-specific async writer."""
        # SQLite uses the db path directly from db_credentials["name"]
        return self._async_writing_class(db_credentials["name"], self._queue, erase_old_db)
    
    def __getstate__(self):
        """Extend base pickle state with SQLite-specific parameters."""
        state = super(SQLiteResultWriter, self).__getstate__()
        # SQLite doesn't need extra kwargs, but we set empty dict for consistency
        state['_pickle_extra_kwargs'] = {}
        return state
    

    def _write_async_command(self, command, args=None):
        """
        Send SQL command to async writer process with SQLite placeholder conversion and resilience.
        
        Args:
            command (str): SQL command to execute (may contain MySQL placeholders)
            args (tuple): Optional arguments for parameterized query
            
        Returns:
            bool: True if command was sent successfully, False if buffered
        """
        # Convert MySQL placeholders (%s) to SQLite placeholders (?)
        if '%s' in command:
            sqlite_command = command.replace('%s', '?')
            logging.debug(f"Converting MySQL command to SQLite: {command} -> {sqlite_command}")
        else:
            sqlite_command = command
        
        # Convert Null() objects to None for SQLite compatibility
        if args is not None:
            sqlite_args = []
            for arg in args:
                if isinstance(arg, Null):
                    sqlite_args.append(None)  # SQLite expects None for NULL
                else:
                    sqlite_args.append(arg)
            sqlite_args = tuple(sqlite_args)
        else:
            sqlite_args = None
        
        # Use the resilient write method from parent class
        return self._write_async_command_resilient(sqlite_command, sqlite_args)

    def _create_table(self, name, fields, engine=None):
        """
        Create SQLite table (ignores engine parameter).
        
        Args:
            name (str): Table name
            fields (str): Field definitions
            engine: Ignored for SQLite
        """
        # Don't modify fields for SQLite - they should already be SQLite-compatible
        command = "CREATE TABLE IF NOT EXISTS %s (%s)" % (name, fields)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)
    
    def _initialise_roi_table(self, roi, data_row):
        """Initialize ROI-specific database table with SQLite-compatible syntax."""
        # SQLite-specific field definitions
        fields = ["id INTEGER PRIMARY KEY AUTOINCREMENT", "t INTEGER"]
        for dt in list(data_row.values()):
            # Convert MySQL types to SQLite equivalents
            sql_type = dt.sql_data_type.upper()
            if "INT" in sql_type:
                sqlite_type = "INTEGER"
            elif "FLOAT" in sql_type or "DOUBLE" in sql_type:
                sqlite_type = "REAL"
            elif "TEXT" in sql_type or "CHAR" in sql_type or "VARCHAR" in sql_type:
                sqlite_type = "TEXT"
            else:
                sqlite_type = "TEXT"  # Default fallback
            fields.append("%s %s" % (dt.header_name, sqlite_type))
        fields = ", ".join(fields)
        table_name = "ROI_%i" % roi.idx
        self._create_table(table_name, fields, engine=None)
        
    def _add(self, t, roi, data_rows):
        """
        Add data with SQLite-specific NULL handling.
        
        Uses None instead of Null() object and converts to string properly for SQLite.
        """
        t = int(round(t))
        roi_id = roi.idx
        for dr in data_rows:
            # Convert Null() to None, then build tuple for string representation
            values = [None if isinstance(self._null, Null) else self._null, t] + list(dr.values())
            # Convert None to NULL string for SQL, others to their string representation
            sql_values = []
            for val in values:
                if val is None:
                    sql_values.append("NULL")
                elif isinstance(val, str):
                    sql_values.append(f"'{val}'")  # Quote strings
                else:
                    sql_values.append(str(val))
            
            value_str = "(" + ", ".join(sql_values) + ")"
            
            if roi_id not in self._insert_dict or self._insert_dict[roi_id] == "":
                command = f'INSERT INTO ROI_{roi_id} VALUES {value_str}'
                self._insert_dict[roi_id] = command
            else:
                self._insert_dict[roi_id] += f",{value_str}"
        
        # now this is irrelevant when tracking multiple animals
        if self._dam_file_helper is not None:
            for dr in data_rows:
                self._dam_file_helper.input_roi_data(t, roi, dr)

    def _create_all_tables(self):
        """
        Create all necessary SQLite database tables for the experiment.
        
        Creates SQLite-compatible tables for:
        - ROI_MAP: ROI definitions and positions
        - VAR_MAP: Variable type mappings
        - IMG_SNAPSHOTS: Image snapshot storage (if enabled)
        - CSV_DAM_ACTIVITY: DAM-compatible activity data (if enabled)
        - METADATA: Experimental metadata
        - START_EVENTS: Experiment start/stop events
        
        Note: SENSORS table is not created as SQLite doesn't support sensors yet
        """
        if self._erase_old_db:
            logging.info("Creating master table 'ROI_MAP'")
            self._create_table("ROI_MAP", "roi_idx INTEGER, roi_value INTEGER, x INTEGER, y INTEGER, w INTEGER, h INTEGER")
            for r in self._rois:
                fd = r.get_feature_dict()
                command = "INSERT INTO ROI_MAP VALUES (?, ?, ?, ?, ?, ?)"
                self._write_async_command(command, (fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))

            logging.info("Creating variable map table 'VAR_MAP'")
            self._create_table("VAR_MAP", "var_name TEXT, sql_type TEXT, functional_type TEXT")
            
            if self._shot_saver is not None:
                logging.info("Creating table for IMG_SNAPSHOTS")
                # SQLite-compatible version of image snapshots table
                self._create_table("IMG_SNAPSHOTS", "id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER, img BLOB")

            if self._sensor_saver is not None:
                logging.info("Creating table for SENSORS data")
                # SensorDataHelper handles SQLite-compatible field generation
                self._create_table(self._sensor_saver.table_name, self._sensor_saver.create_command)

            if self._dam_file_helper is not None:
                logging.info("Creating 'CSV_DAM_ACTIVITY' table")
                # Convert DAM table fields to SQLite-compatible format
                mysql_fields = self._dam_file_helper.make_dam_file_sql_fields()
                # Convert MySQL field definitions to SQLite equivalents
                sqlite_fields = mysql_fields.replace("INT  NOT NULL AUTO_INCREMENT PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                sqlite_fields = sqlite_fields.replace("CHAR(100)", "TEXT")
                sqlite_fields = sqlite_fields.replace("SMALLINT", "INTEGER")
                self._create_table("CSV_DAM_ACTIVITY", sqlite_fields)

            logging.info("Creating 'METADATA' table")
            self._create_table("METADATA", "field TEXT, value TEXT")
            
            logging.info("Creating 'START_EVENTS' table")
            self._create_table("START_EVENTS", "id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER, event TEXT")
            event = "graceful_start"
            command = "INSERT INTO START_EVENTS VALUES (?, ?, ?)"
            self._write_async_command(command, (None, int(time.time()), event))

            # Insert experimental metadata using SQLite-specific method
            self._insert_metadata()
            
            self._wait_for_queue_empty()

        elif not self._erase_old_db and getattr(self, 'database_to_append', None):

            event = "appending"
            command = "INSERT INTO START_EVENTS VALUES (?, ?, ?)"
            self._write_async_command(command, (None, int(time.time()), event))
            self._wait_for_queue_empty()

    def _insert_metadata(self):
        """Insert experimental metadata into METADATA table with SQLite duplicate prevention."""
        import json
        from .base import METADATA_MAX_VALUE_LENGTH
        
        for k, v in list(self.metadata.items()):
            # Properly serialize complex metadata values to avoid SQL injection and formatting issues
            v_serialized = json.dumps(str(v)) if not isinstance(v, (str, int, float, bool, type(None))) else v
            
            # Truncate extremely large values as a safety measure
            max_value_length = METADATA_MAX_VALUE_LENGTH
            if isinstance(v_serialized, str) and len(v_serialized) > max_value_length:
                v_serialized = v_serialized[:max_value_length] + "... [TRUNCATED]"
                logging.warning(f"Metadata value for key '{k}' was truncated due to size limit")
            
            # Use SQLite INSERT OR IGNORE to prevent duplicate key errors
            command = "INSERT OR IGNORE INTO METADATA VALUES (?, ?)"
            self._write_async_command(command, (k, v_serialized))