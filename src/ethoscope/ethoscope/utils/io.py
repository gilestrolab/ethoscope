"""
Database Writers for Ethoscope Experiment Data Storage

This module provides various classes for storing experimental tracking data from the Ethoscope
behavioral monitoring system. The classes support multiple database backends (MySQL/MariaDB, SQLite)
and different output formats (database tables, numpy arrays).

Class Hierarchy and Relationships:
==================================

1. Database Writers (Main Interface):
   MySQLResultWriter (base class for MySQL database storage)
   ├── SQLiteResultWriter (extends BaseResultWriter for SQLite-specific behavior)
   └── RawDataWriter (independent class for numpy array storage)

2. Async Database Processes (Multiprocessing):
   multiprocessing.Process
   ├── AsyncMySQLWriter (handles MySQL/MariaDB writes in separate process)
   └── AsyncSQLiteWriter (handles SQLite writes in separate process)

3. Helper Classes (Data Formatting):
   SensorDataHelper (formats sensor data for database storage)
   ImgSnapshotHelper (handles image snapshot storage as BLOBs)
   DAMFileHelper (creates DAM-compatible activity summaries)

4. Utility Classes:
   Null (special NULL representation for SQLite)
   NpyAppendableFile (custom numpy array file format for incremental writes)

Interaction Flow:
================
1. MySQLResultWriter/SQLiteResultWriter creates an async writer process (AsyncMySQLWriter/AsyncSQLiteWriter)
2. MySQLResultWriter sends SQL commands through a multiprocessing queue to the async writer
3. MySQLResultWriter uses helper classes to format different data types:
   - DAMFileHelper for activity summaries
   - ImgSnapshotHelper for periodic screenshots
   - SensorDataHelper for environmental sensor data
4. RawDataWriter operates independently, saving raw data directly to numpy array files

Key Design Patterns:
===================
- Multiprocessing: Async writers run in separate processes to prevent I/O blocking
- Producer-Consumer: Main thread produces SQL commands, async writer consumes them
- Template Method: BaseResultWriter provides base implementation, MySQLResultWriter and SQLiteResultWriter override specific methods
- Helper Pattern: Separate classes handle formatting for different data types
- Context Manager: BaseResultWriter implements __enter__/__exit__ for proper cleanup
"""

import multiprocessing
import time, datetime
import traceback
import logging
from collections import OrderedDict, deque
import tempfile
import os
import numpy as np
import sqlite3
import mysql.connector
import json
from cv2 import imwrite, IMWRITE_JPEG_QUALITY

# Character encoding for MariaDB/MySQL connections
SQL_CHARSET = 'latin1'

# Constants
ASYNC_WRITER_TIMEOUT = 30  # Timeout in seconds for async writer initialization
SENSOR_DEFAULT_PERIOD = 120.0  # Default sensor sampling period in seconds
IMG_SNAPSHOT_DEFAULT_PERIOD = 300.0  # Default image snapshot period in seconds (5 minutes)

# Database resilience constants
MAX_DB_RETRIES = 3  # Maximum number of retry attempts for database operations
RETRY_BASE_DELAY = 1.0  # Base delay in seconds for exponential backoff
MAX_RETRY_DELAY = 30.0  # Maximum delay between retries
MAX_BUFFERED_COMMANDS = 10000  # Maximum commands to buffer in memory during failures
DAM_DEFAULT_PERIOD = 60.0  # Default DAM activity sampling period in seconds
METADATA_MAX_VALUE_LENGTH = 60000  # Maximum length for metadata values before truncation
QUEUE_CHECK_INTERVAL = 0.1  # Interval for checking queue status in seconds


# =============================================================================================================#
# DATA SPECIFIC HELPERS
#
# =============================================================================================================#

class SensorDataHelper(object):
    """
    Helper class for saving sensor data to database at regular intervals.
    
    This class manages the periodic sampling and storage of sensor readings
    (e.g., temperature, humidity) into the database.
    
    Attributes:
        _table_name (str): Name of the sensor data table
        _base_headers (dict): Base columns for the sensor table (id and timestamp)
    """
    _table_name = "SENSORS"
    
    def __init__(self, sensor, period=SENSOR_DEFAULT_PERIOD, database_type="MySQL"):
        """
        Initialize the sensor data helper.
        
        Args:
            sensor: Sensor object with read_all() method and sensor_types property
            period (float): Sampling period in seconds (default: 120s)
            database_type (str): Database type - "MySQL" or "SQLite3" (default: "MySQL")
        """
        self._period = period
        self._last_tick = 0
        self.sensor = sensor
        self._database_type = database_type
        
        # Set appropriate base headers based on database type
        if database_type == "SQLite3":
            self._base_headers = {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "t": "INTEGER"}
        else:  # MySQL
            self._base_headers = {"id": "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", "t": "INT"}
        
        # Build table headers with appropriate data types
        self._table_headers = {**self._base_headers, **self._get_sensor_types_for_database()}
        
    def flush(self, t):
        """
        Save sensor data if enough time has elapsed since last save.
        
        Args:
            t (int): Current time in milliseconds
            
        Returns:
            tuple: (SQL command, args) or None if not time to save
        """
        tick = int(round((t/1000.0)/self._period))
        if tick == self._last_tick:
            return
        try:
            if self._database_type == "SQLite3":
                # For SQLite, don't specify ID - let AUTOINCREMENT handle it
                values = [str(v) for v in ((int(t),) + self.sensor.read_all())]
                columns = list(self._table_headers.keys())[1:]  # Skip 'id' column
                cmd = (
                        "INSERT into "
                        + self._table_name
                        + " (" + ','.join(columns) + ")"
                        + " VALUES (" 
                        + ','.join(values) 
                        + ")"
                       )
            else:
                # For MySQL, explicit ID=0 is fine (will be auto-incremented)
                values = [str(v) for v in ((0, int(t)) + self.sensor.read_all())]
                cmd = (
                        "INSERT into "
                        + self._table_name
                        + " VALUES (" 
                        + ','.join(values) 
                        + ")"
                       )
            self._last_tick = tick
            return cmd, None
    
        except:
            logging.error("The sensor data are not available")
            self._last_tick = tick
            return
  
    @property
    def table_name (self):
        """Get the sensor table name."""
        return self._table_name
        
    def _get_sensor_types_for_database(self):
        """
        Convert sensor types to appropriate database format.
        
        Returns:
            dict: Sensor field names mapped to database-appropriate data types
        """
        if not hasattr(self.sensor, 'sensor_types'):
            return {}
        
        sensor_types = {}
        for field_name, mysql_type in self.sensor.sensor_types.items():
            if self._database_type == "SQLite3":
                # Convert MySQL types to SQLite equivalents
                if mysql_type.upper() in ['FLOAT', 'DOUBLE']:
                    sqlite_type = 'REAL'
                elif mysql_type.upper().startswith('INT'):
                    sqlite_type = 'INTEGER'
                elif mysql_type.upper().startswith(('CHAR', 'VARCHAR', 'TEXT')):
                    sqlite_type = 'TEXT'
                else:
                    sqlite_type = 'TEXT'  # Default fallback
                sensor_types[field_name] = sqlite_type
            else:
                # Use original MySQL types
                sensor_types[field_name] = mysql_type
        
        return sensor_types
    
    @property
    def create_command(self):
        """Generate SQL CREATE TABLE command for sensor data."""
        return ",".join([ "%s %s" % (key, self._table_headers[key]) for key in self._table_headers])

class ImgSnapshotHelper(object):
    """
    Helper class for saving image snapshots to database at regular intervals.
    
    This class handles periodic capture and storage of JPEG-compressed images
    from the experiment video feed into the database as BLOBs.
    
    Attributes:
        _table_name (str): Name of the image snapshots table
        _table_headers (dict): Column definitions for the snapshots table
    """
    _table_name = "IMG_SNAPSHOTS"
    
    def __init__(self, period=IMG_SNAPSHOT_DEFAULT_PERIOD, database_type="MySQL"):
        """
        Initialize the image snapshot helper.
        
        Args:
            period (float): Snapshot interval in seconds (default: 300s/5min)
            database_type (str): Database type - "MySQL" or "SQLite3" (default: "MySQL")
        """
        self._period = period
        self._last_tick = 0
        self._database_type = database_type
        self._tmp_file = tempfile.mktemp(prefix="ethoscope_", suffix=".jpg")
        
        # Set appropriate table headers based on database type
        if database_type == "SQLite3":
            self._table_headers = {"id": "INTEGER PRIMARY KEY AUTOINCREMENT", "t": "INTEGER", "img": "BLOB"}
        else:  # MySQL
            self._table_headers = {"id": "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", "t": "INT", "img": "LONGBLOB"}
                      
    @property
    def table_name (self):
        """Get the image snapshots table name."""
        return self._table_name
        
    @property
    def create_command(self):
        """Generate SQL CREATE TABLE command for image snapshots."""
        return ",".join([ "%s %s" % (key, self._table_headers[key]) for key in self._table_headers])
        
    def __del__(self):
        """Cleanup temporary file on object destruction."""
        try:
            os.remove(self._tmp_file)
        except:
            logging.error("Could not remove temp file: %s" % self._tmp_file)

    def flush(self, t, img):
        """
        Save image snapshot if enough time has elapsed.
        
        Args:
            t (int): Current time in milliseconds
            img (np.ndarray): Image array to save
            
        Returns:
            tuple: (SQL command, args) or None if not time to save
        """
        tick = int(round((t/1000.0)/self._period))
        if tick == self._last_tick:
            return
        imwrite(self._tmp_file, img, [int(IMWRITE_JPEG_QUALITY), 50])
        with open(self._tmp_file, "rb") as f:
                bstring = f.read()
        
        if self._database_type == "SQLite3":
            # For SQLite, don't specify ID - let AUTOINCREMENT handle it
            cmd = 'INSERT INTO ' + self._table_name + '(t,img) VALUES (?,?)'
            args = (int(t), bstring)
        else:
            # For MySQL, explicit ID=0 is fine (will be auto-incremented)
            cmd = 'INSERT INTO ' + self._table_name + '(id,t,img) VALUES (%s,%s,%s)'
            args = (0, int(t), bstring)
            
        self._last_tick = tick
        return cmd, args
        
class DAMFileHelper(object):
    """
    Helper class for generating DAM (Drosophila Activity Monitor) compatible data.
    
    This class tracks movement activity for each ROI and formats it in a way
    compatible with the DAM file format, allowing integration with existing
    Drosophila activity analysis tools.
    """
    
    def __init__(self, period=DAM_DEFAULT_PERIOD, n_rois=32):
        """
        Initialize the DAM file helper.
        
        Args:
            period (float): Activity sampling period in seconds (default: 60s)
            n_rois (int): Number of regions of interest (default: 32)
        """
        self._period = period
        self._activity_accum = OrderedDict()
        self._n_rois = n_rois
        self._distance_map ={}
        self._last_positions ={}
        self._scale = 100 # multiply by this factor before converting to int activity
        for i in range(1, self._n_rois +1):
            self._distance_map[i] = 0
            self._last_positions[i] = None
            
    def make_dam_file_sql_fields(self):
        """
        Generate SQL field definitions for DAM-compatible activity table.
        
        Returns:
            str: Comma-separated field definitions for CREATE TABLE
        """
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY",
          "date CHAR(100)",
          "time CHAR(100)"]
        for r in range(1,self._n_rois +1):
            fields.append("ROI_%d SMALLINT" % r)
        fields = ",".join(fields)
        return fields
        
    def _compute_distance_for_roi(self, roi, data):
        """
        Calculate normalized movement distance for a single ROI.
        
        Args:
            roi: ROI object with idx and longest_axis properties
            data (dict): Position data with 'x' and 'y' coordinates
            
        Returns:
            float: Normalized distance moved since last position
        """
        last_pos = self._last_positions[roi.idx]
        current_pos = data["x"] + 1j*data["y"]
        if last_pos is None:
            self._last_positions[roi.idx] = current_pos
            return 0
        dist = abs(current_pos - last_pos)
        dist /= roi.longest_axis
        self._last_positions[roi.idx] = current_pos
        return dist
        
    def input_roi_data(self, t, roi, data):
        """
        Record activity data for a specific ROI at given time.
        
        Args:
            t (int): Time in milliseconds
            roi: ROI object
            data (dict): Position data for the ROI
        """
        tick = int(round((t/1000.0)/self._period))
        act  = self._compute_distance_for_roi(roi,data)
        if tick not in self._activity_accum:
            self._activity_accum[tick] = OrderedDict()
            for r in range(1, self._n_rois + 1):
                self._activity_accum[tick][r] = 0
        self._activity_accum[tick][roi.idx] += act
        
    def _make_sql_command(self, vals):
        """
        Create SQL INSERT command for activity data.
        
        Args:
            vals (dict): Activity values for each ROI
            
        Returns:
            str: SQL INSERT command
        """
        dt = datetime.datetime.fromtimestamp(int(time.time()))
        date_time_fields = dt.strftime("%d %b %Y,%H:%M:%S").split(",")
        values = date_time_fields
        for i in range(1, self._n_rois +1):
            values.append(int(round(self._scale * vals[i])))
        command = '''INSERT INTO CSV_DAM_ACTIVITY (date, time, ''' + ', '.join([f'ROI_{i}' for i in range(1, self._n_rois + 1)]) + ''') VALUES %s''' % str(tuple(values))
        return command

    def flush(self, t):
        """
        Generate SQL commands for all accumulated activity data.
        
        Args:
            t (int): Current time in milliseconds
            
        Returns:
            list: SQL INSERT commands for accumulated data
        """
        out =  OrderedDict()
        tick = int(round((t/1000.0)/self._period))
        if len(self._activity_accum) < 1:
            self._activity_accum[tick] = OrderedDict()
            for r in range(1, self._n_rois +1):
                self._activity_accum[tick][r] = 0
            return []

        m  = min(self._activity_accum.keys())
        todel = []
        for i in range(m, tick ):
            if i not in list(self._activity_accum.keys()):
                self._activity_accum[i] = OrderedDict()
                for r in range(1, self._n_rois +1):
                    self._activity_accum[i][r] = 0
            out[i] =  self._activity_accum[i].copy()
            todel.append(i)
            for r in range(1, self._n_rois + 1):
                out[i][r] = round(out[i][r],5)

        for i in todel:
            del self._activity_accum[i]

        if tick - m > 1:
            logging.warning("DAM file writer skipping a tick. No data for more than one period!")
        out = [self._make_sql_command(v) for v in list(out.values())]
        return out



class Null(object):
    """
    Special NULL representation for SQLite compatibility.
    
    SQLite requires NULL for auto-increment fields instead of 0.
    """
    def __repr__(self):
        return "NULL"
    def __str__(self):
        return "NULL"


# =============================================================================================================#
# ASYNC CLASSES
# BaseAsyncSQLWriter (multiprocessing.Process)
#     AsyncMySQLWriter (BaseAsyncSQLWriter)
#     ASyncSQLiteWriter (BaseAsyncSQLWriter)
#
# =============================================================================================================#

class BaseAsyncSQLWriter(multiprocessing.Process):
    """
    Abstract base class for asynchronous SQL database writers.
    
    This class provides a template method pattern for SQL database writers that run
    in separate processes. It handles the common functionality of queue processing,
    event signaling, error handling, and cleanup while allowing subclasses to 
    implement database-specific connection and initialization logic.
    
    Attributes:
        _queue (multiprocessing.Queue): Queue for receiving SQL commands
        _erase_old_db (bool): Whether to erase existing database on startup
        _ready_event (multiprocessing.Event): Signals when writer is ready
    """
    
    def __init__(self, queue, erase_old_db=True):
        """
        Initialize the base async SQL writer.
        
        Args:
            queue (multiprocessing.Queue): Queue for receiving SQL commands
            erase_old_db (bool): Whether to erase existing database on startup
        """
        self._queue = queue
        self._erase_old_db = erase_old_db
        self._ready_event = multiprocessing.Event()
        super(BaseAsyncSQLWriter, self).__init__()
    
    def run(self):
        """
        Template method for the main process loop.
        
        This method implements the common pattern for all async SQL writers:
        1. Initialize database-specific setup
        2. Signal ready state
        3. Process commands from queue until 'DONE'
        4. Handle errors appropriately
        5. Clean up resources
        """
        db = None
        do_run = True
        
        try:
            logging.info(f"{self._get_db_type_name()} async writer starting up...")
            
            # Database-specific initialization (implemented by subclasses)
            self._initialize_database()
            
            # Get database connection (implemented by subclasses)
            db = self._get_connection()
            logging.info(f"{self._get_db_type_name()} database connection established successfully")
            
            # Signal that the writer is ready to accept commands
            logging.info(f"{self._get_db_type_name()} async writer ready to accept commands")
            self._ready_event.set()
        
            # Main command processing loop
            while do_run:
                try:
                    msg = self._queue.get()
                    if (msg == 'DONE'):
                        do_run = False
                        continue
                    command, args = msg
                    
                    c = db.cursor()
                    if args is None:
                        c.execute(command)
                    else:
                        c.execute(command, args)
                    db.commit()
                    
                except Exception as e:
                    # Determine if this error should stop the writer
                    if not self._should_retry_on_error(e):
                        do_run = False
                        
                    try:
                        logging.error(f"Failed to run {self._get_db_type_name().lower()} command:\n%s" % command)
                        logging.error("Error details: %s" % str(e))
                        logging.error("Arguments: %s" % str(args) if 'args' in locals() else "None")
                        logging.error("Traceback: %s" % traceback.format_exc())
                        
                        # Allow subclasses to handle specific error types
                        self._handle_command_error(e, command, args if 'args' in locals() else None)
                        
                    except Exception as log_error:
                        logging.error("Failed to log error details: %s" % str(log_error))
                        logging.error("Did not retrieve queue value or failed to log command")
                        do_run = False
                finally:
                    if self._queue.empty():
                        # Sleep if queue is empty to avoid excessive CPU usage
                        time.sleep(QUEUE_CHECK_INTERVAL)
                        
        except KeyboardInterrupt as e:
            logging.warning(f"{self._get_db_type_name()} async process interrupted with KeyboardInterrupt")
            # Ensure ready event is set even if interrupted
            self._ready_event.set()
            raise e
        except Exception as e:
            logging.error(f"{self._get_db_type_name()} async process stopped with an exception: %s", str(e))
            logging.error("Exception traceback: %s", traceback.format_exc())
            # Ensure ready event is set even if there's an error during startup
            self._ready_event.set()
            raise e
        finally:
            logging.info(f"Closing async {self._get_db_type_name().lower()} writer")
            while not self._queue.empty():
                self._queue.get()
            self._queue.close()
            if db is not None:
                db.close()
    
    # Abstract methods that subclasses must implement
    def _initialize_database(self):
        """Initialize database-specific setup (create, delete, configure)."""
        raise NotImplementedError("Subclasses must implement _initialize_database()")
    
    def _get_connection(self):
        """Create and return a database connection object."""
        raise NotImplementedError("Subclasses must implement _get_connection()")
    
    def _get_db_type_name(self):
        """Return the database type name for logging (e.g., 'MySQL', 'SQLite')."""
        raise NotImplementedError("Subclasses must implement _get_db_type_name()")
    
    def _should_retry_on_error(self, error):
        """
        Determine whether the writer should continue after an error.
        
        Args:
            error (Exception): The exception that occurred
            
        Returns:
            bool: True if the writer should continue, False if it should stop
        """
        raise NotImplementedError("Subclasses must implement _should_retry_on_error()")
    
    def _handle_command_error(self, error, command, args):
        """
        Handle database-specific error processing.
        
        Args:
            error (Exception): The exception that occurred
            command (str): The SQL command that failed
            args (tuple): The command arguments, if any
        """
        # Default implementation does nothing; subclasses can override
        pass

class AsyncMySQLWriter(BaseAsyncSQLWriter):
    """
    Asynchronous MySQL/MariaDB database writer that runs in a separate process.
    
    This class handles all database write operations in a separate process to prevent
    blocking the main data collection thread. It uses a queue to receive SQL commands
    from the main process and executes them sequentially.
    
    Attributes:
        _db_host (str): Database host address
        _db_name (str): Database name
        _db_user_name (str): Database username
        _db_user_pass (str): Database password
    """
    
    _database_type = "MySQL"

    def __init__(self, db_credentials, queue, erase_old_db=True, db_host="localhost"):
        """
        Initialize the async MySQL writer process.
        
        Args:
            db_credentials (dict): Database credentials containing:
                - name: Database name
                - user: Database username
                - password: Database password
            queue (multiprocessing.Queue): Queue for receiving SQL commands
            erase_old_db (bool): Whether to drop and recreate database
            db_host (str): Database server hostname or IP address
        """
        super(AsyncMySQLWriter, self).__init__(queue, erase_old_db)
        self._db_name = db_credentials["name"]
        self._db_user_name = db_credentials["user"]
        self._db_user_pass = db_credentials["password"]
        self._db_host = db_host


    def _delete_my_sql_db(self):
        """
        Delete the existing MySQL database if it exists.
        
        This method connects to MySQL, truncates all tables for performance,
        resets binary logs if enabled, and then drops the entire database.
        """
        try:
            logging.info(f"Attempting to connect to mysql db {self._db_name} on host {self._db_host} as {self._db_user_name}")
            db = mysql.connector.connect(host=self._db_host,
                                         user=self._db_user_name,
                                         passwd=self._db_user_pass,
                                         db=self._db_name,
                                         buffered=True,
                                         charset=SQL_CHARSET,
                                         use_unicode=True)
                                         
        except mysql.connector.errors.OperationalError:
            logging.warning("Database %s does not exist. Cannot delete it" % self._db_name)
            return
            
        except Exception as e:
            logging.error(traceback.format_exc())
            return
        c = db.cursor()
        
        # Reset binary logs if enabled to save space
        # However, this will throw an error if binary logging is set to off
        # Which is what we should be doing because it reduces disk access and we do not need it anyway
        try:
            c.execute("SHOW VARIABLES LIKE 'log_bin';")
            log_bin_status = c.fetchone()
            if log_bin_status and log_bin_status[1] == 'ON':
                logging.info("The binary logs are set to true. Resetting them to save space.")
                c.execute("RESET MASTER")
        except Exception as e:
            logging.warning(f"Could not reset binary logs: {e}")

        # Drop the entire database directly (no need to truncate tables first)
        logging.info("Dropping entire database")
        command = "DROP DATABASE IF EXISTS %s" % self._db_name
        c.execute(command)
        db.commit()
        db.close()

    def _create_mysql_db(self):
        """
        Create a new MySQL database and configure database settings.
        
        This method creates the database, sets up a read-only 'node' user for
        remote access, and configures InnoDB settings for optimal performance.
        """
        logging.info(f"Connecting to MySQL host {self._db_host} as user {self._db_user_name}")
        try:
            db = mysql.connector.connect(host=self._db_host,
                                         user=self._db_user_name,
                                         passwd=self._db_user_pass,
                                         buffered=True,
                                         charset=SQL_CHARSET,
                                         use_unicode=True)
            logging.info("Successfully connected to MySQL for database creation")
        except Exception as e:
            logging.error(f"Failed to connect to MySQL: {str(e)}")
            raise
        c = db.cursor()
        cmd = "CREATE DATABASE %s" % self._db_name
        c.execute(cmd)
        logging.info("Database created")
        
        #create a read-only node user that the node will use to get data from
        #it's better to have a second user for remote operation for reasons of debug and have better control
        cmd = "GRANT SELECT ON %s.* to 'node' identified by 'node'" % self._db_name
        c.execute(cmd)
        logging.info("Node user created")
        
        #set some innodb specific values that cannot be set on the config file
        cmd = "SET GLOBAL innodb_file_per_table=1"
        c.execute(cmd)
        #"Variable 'innodb_file_format' is a read only variable"
        #cmd = "SET GLOBAL innodb_file_format=Barracuda"
        #c.execute(cmd)
        cmd = "SET GLOBAL autocommit=0"
        c.execute(cmd)
        db.close()
        
    def _get_connection(self):
        """
        Establish a connection to the MySQL database.
        
        Returns:
            mysql.connector.connection: Database connection object
        """
        db = mysql.connector.connect(host=self._db_host,
                                     user=self._db_user_name,
                                     passwd=self._db_user_pass,
                                     db=self._db_name,
                                     buffered=True,
                                     charset=SQL_CHARSET,
                                     use_unicode=True)
        return db
    
    # Implementation of abstract methods from BaseAsyncSQLWriter
    def _initialize_database(self):
        """Initialize MySQL database setup - create/delete database if needed."""
        if self._erase_old_db:
            logging.info("Deleting old database...")
            self._delete_my_sql_db()
            logging.info("Creating new database...")
            self._create_mysql_db()
    
    def _get_db_type_name(self):
        """Return database type name for logging."""
        return "MySQL"
    
    def _should_retry_on_error(self, error):
        """
        Determine if MySQL writer should continue after an error.
        
        MySQL writer uses sophisticated error recovery - continues on non-critical errors.
        """
        error_str = str(error).lower()
        critical_errors = ['access denied', 'connection', 'server has gone away', 'lost connection']
        is_critical = any(critical_error in error_str for critical_error in critical_errors)
        
        if is_critical:
            logging.error("Critical database error detected, stopping async writer")
            return False
        else:
            logging.warning("Non-critical database error, continuing operations")
            return True


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


# =============================================================================================================#
# SYNC CLASSES
# BaseResultWriter (Object)
#     ResultWriter (BaseResultWriter)
#     SQLResultWriter (BaseResultWriter)
#
# =============================================================================================================#

class BaseResultWriter(object):
    """
    Abstract base class for all result writers with common functionality.
    
    This class contains all the shared logic for initializing and managing result writers,
    including helper classes, metadata handling, and database table creation. Subclasses
    implement database-specific async writer creation and any specialized behavior.
    
    Attributes:
        _max_insert_string_len (int): Maximum length for batched INSERT commands
        _async_writing_class: Class to use for async database writes (set by subclasses)
        _null: Value to use for NULL in database (set by subclasses)
    """
    
    # Subclasses must define these class attributes
    _async_writing_class = None
    _null = None
    _max_insert_string_len = 1000
    
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=True, 
                 take_frame_shots=False, erase_old_db=True, sensor=None, **kwargs):
        """
        Initialize the base result writer with common functionality.
        
        Args:
            db_credentials (dict): Database connection credentials
            rois (list): List of ROI objects to track
            metadata (dict): Experimental metadata to store
            make_dam_like_table (bool): Whether to create DAM-compatible activity table
            take_frame_shots (bool): Whether to periodically save image snapshots
            erase_old_db (bool): Whether to drop and recreate database
            sensor: Optional sensor object for environmental data collection
            **kwargs: Additional arguments passed to subclasses
        """
        # Create async writer using subclass-specific method
        self._queue = multiprocessing.JoinableQueue()
        self._async_writer = self._create_async_writer(db_credentials, erase_old_db, **kwargs)
        self._async_writer.start()
        
        # Initialize common attributes
        self._erase_old_db = erase_old_db
        self._last_t, self._last_flush_t, self._last_dam_t = [0] * 3
        self._metadata = metadata
        self._rois = rois
        self._db_credentials = db_credentials
        self._make_dam_like_table = make_dam_like_table
        self._take_frame_shots = take_frame_shots
        
        # Initialize resilience features
        self._failed_commands_buffer = deque(maxlen=MAX_BUFFERED_COMMANDS)
        self._writer_restart_count = 0
        self._last_restart_time = 0
        
        # Initialize helper classes
        if make_dam_like_table:
            self._dam_file_helper = DAMFileHelper(n_rois=len(rois))
        else:
            self._dam_file_helper = None
        if take_frame_shots:
            self._shot_saver = ImgSnapshotHelper(database_type=self._database_type)
        else:
            self._shot_saver = None
        self._insert_dict = {}
        if self._metadata is None:
            self._metadata = {}
        if sensor is not None:
            self._sensor_saver = SensorDataHelper(sensor, database_type=self._database_type)
            logging.info("Creating connection to a sensor to store its data in the db")
        else:
            self._sensor_saver = None
        
        self._var_map_initialised = False
        
        # Database initialization - wait for async writer to be ready first
#        if (self._database_type == "MySQL" and erase_old_db) or self._database_type == "SQLite3":
        logging.warning("Waiting for async writer to initialize database...")
        # Wait for async writer to complete database initialization
        if not self._async_writer._ready_event.wait(timeout=ASYNC_WRITER_TIMEOUT):
            if self._async_writer.is_alive():
                raise Exception(f"Async database writer failed to initialize within {ASYNC_WRITER_TIMEOUT} seconds - check database connection")
            else:
                raise Exception("Async database writer process died during initialization - check database configuration and logs")
        
        logging.warning("Creating database tables...")
    
        #This will check if tables need to be created or not based on erase_old_db
        self._create_all_tables()

#        elif self._database_type == "MySQL" and not erase_old_db:
#            event = "crash_recovery"
#            command = "INSERT INTO START_EVENTS VALUES (%s, %s, %s)"
#            self._write_async_command(command, (self._null, int(time.time()), event))

        logging.info("Result writer initialised")
    
    def _create_async_writer(self, db_credentials, erase_old_db, **kwargs):
        """
        Create database-specific async writer.
        
        This abstract method must be implemented by subclasses to create
        the appropriate async writer for their database type.
        
        Args:
            db_credentials (dict): Database connection credentials
            erase_old_db (bool): Whether to erase existing database
            **kwargs: Additional database-specific arguments
            
        Returns:
            BaseAsyncSQLWriter: The appropriate async writer instance
        """
        raise NotImplementedError("Subclasses must implement _create_async_writer()")
    
    def __enter__(self):
        """Context manager entry."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit - ensures proper cleanup.
        
        Flushes remaining data, writes stop timestamp, and properly
        shuts down the async writer process.
        """
        logging.info("Closing result writer...")
        for k, v in list(self._insert_dict.items()):
            self._write_async_command(v)
            self._insert_dict[k] = ""
        try:
            command = "INSERT INTO METADATA VALUES (%s, %s)"
            self._write_async_command(command, ("stop_date_time", str(int(time.time()))))
            while not self._queue.empty():
                logging.info("waiting for queue to be processed")
                time.sleep(QUEUE_CHECK_INTERVAL)
        except Exception as e:
            logging.error("Error writing metadata stop time:")
            logging.error(traceback.format_exc())
        finally:
            logging.info("Closing async queue")
            self._queue.put("DONE")
            logging.info("Freeing queue")
            self._queue.cancel_join_thread()
            logging.info("Joining thread")
            if self._async_writer.is_alive():
                self._async_writer.join()
                logging.info("Joined OK")
            else:
                logging.info("Process was not started, skipping join")

    def append(self):
        """
        Gets the last timestamp from the database to allow appending.
        Returns:
            int: The last timestamp in milliseconds, or 0 if not found.
        """
        return self.get_last_timestamp()
            
    def close(self):
        """Placeholder close method."""
        pass
        
    def __getstate__(self):
        """
        Prepare object for pickling by excluding non-serializable multiprocessing objects.
        
        JoinableQueue and Process objects cannot be pickled, so we store the initialization
        parameters needed to recreate them after unpickling.
        """
        state = self.__dict__.copy()
        
        # Store initialization parameters for reconstruction
        state['_pickle_init_args'] = {
            'db_credentials': self._db_credentials,
            'rois': self._rois,
            'metadata': self._metadata,
            'make_dam_like_table': self._make_dam_like_table,
            'take_frame_shots': self._take_frame_shots,
        }
        
        # Remove non-serializable multiprocessing objects
        state.pop('_queue', None)
        state.pop('_async_writer', None)
        
        return state
        
    def __setstate__(self, state):
        """
        Restore object from pickled state by recreating multiprocessing objects.
        
        This recreates the queue and async writer that were excluded during pickling.
        """
        self.__dict__.update(state)
        
        # Recreate multiprocessing objects using stored parameters
        init_args = state.get('_pickle_init_args', {})
        
        # Recreate queue and async writer
        self._queue = multiprocessing.JoinableQueue()
        self._async_writer = self._create_async_writer(
            init_args.get('db_credentials', self._db_credentials),
            False,  # Don't erase database when restoring from pickle
            **getattr(self, '_pickle_extra_kwargs', {})
        )
        # Note: async writer is not started automatically - the calling code should handle this
    
    @property
    def metadata(self):
        """Get experimental metadata."""
        return self._metadata

    def write(self, t, roi, data_rows):
        """
        Write tracking data for a ROI.
        
        Args:
            t (int): Time in milliseconds
            roi: ROI object
            data_rows (list): List of tracking data points
        """
        self._last_t = t
        if not self._var_map_initialised:
            self._var_map_initialised = True
            self._initialise_var_map(data_rows[0])
        
        # Check if this ROI's table exists, create if needed
        roi_id = roi.idx
        table_name = f"ROI_{roi_id}"
        if not hasattr(self, '_initialized_rois'):
            self._initialized_rois = set()
        
        if roi_id not in self._initialized_rois:
            self._initialise_roi_table(roi, data_rows[0])
            self._initialized_rois.add(roi_id)
            
        self._add(t, roi, data_rows)
        
    def flush(self, t, img=None):
        """
        Flush accumulated data to database.
        
        This method is called periodically to write batched SQL commands,
        save snapshots, and collect sensor data.
        
        Args:
            t (int): Current time in milliseconds
            img (np.ndarray): Optional image for snapshot
            
        Returns:
            bool: Always returns False
        """
        if self._dam_file_helper is not None:
            out = self._dam_file_helper.flush(t)
            for c in out:
                self._write_async_command(c)
        if self._shot_saver is not None and img is not None:
            c_args = self._shot_saver.flush(t, img)
            if c_args is not None:
                self._write_async_command(*c_args)
        if self._sensor_saver is not None:
            c_args = self._sensor_saver.flush(t)
            if c_args is not None:
                self._write_async_command(*c_args)
        for k, v in list(self._insert_dict.items()):
            if len(v) > self._max_insert_string_len:
                self._write_async_command(v)
                self._insert_dict[k] = ""
        return False

    def _add(self, t, roi, data_rows):
        """
        Add tracking data to the batch insert buffer.
        
        Args:
            t (int): Time in milliseconds
            roi: ROI object
            data_rows (list): Tracking data points
        """
        roi_id = roi.idx
        for dr in data_rows:
            tp = (self._null, t) + tuple(dr.values())
            if roi_id not in self._insert_dict or self._insert_dict[roi_id] == "":
                command = 'INSERT INTO ROI_%i VALUES %s' % (roi_id, str(tp))
                self._insert_dict[roi_id] = command
            else:
                self._insert_dict[roi_id] += ("," + str(tp))
        
        # now this is irrelevant when tracking multiple animals
        if self._dam_file_helper is not None:
            for dr in data_rows:
                self._dam_file_helper.input_roi_data(t, roi, dr)
    
    def _initialise_var_map(self, data_row):
        """Initialize variable mapping table with data types."""
        self._write_async_command("DELETE FROM VAR_MAP")
        for dt in list(data_row.values()):
            command = "INSERT INTO VAR_MAP VALUES (%s, %s, %s)"
            self._write_async_command(command, (dt.header_name, dt.sql_data_type, dt.functional_type))

    def _initialise_roi_table(self, roi, data_row):
        """Initialize ROI-specific database table (MySQL version)."""
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY", "t INT"]
        for dt in list(data_row.values()):
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))
        fields = ", ".join(fields)
        table_name = "ROI_%i" % roi.idx
        self._create_table(table_name, fields)
    
    def _write_async_command(self, command, args=None):
        """
        Send SQL command to async writer process with resilience features.
        
        Args:
            command (str): SQL command to execute
            args (tuple): Optional arguments for parameterized query
            
        Raises:
            Exception: If all retry attempts fail and fallback strategies are exhausted
        """
        return self._write_async_command_resilient(command, args)
    
    def _write_async_command_resilient(self, command, args=None):
        """
        Send SQL command with retry logic and writer recovery.
        
        Args:
            command (str): SQL command to execute
            args (tuple): Optional arguments for parameterized query
            
        Returns:
            bool: True if command was sent successfully, False if buffered
        """
        for attempt in range(MAX_DB_RETRIES + 1):
            try:
                # Check if async writer is alive
                if not self._async_writer.is_alive():
                    if attempt < MAX_DB_RETRIES:
                        self.log_io_diagnostics(f"Writer died during attempt {attempt + 1}/{MAX_DB_RETRIES}")
                        logging.warning(f"Async writer died, attempting restart (attempt {attempt + 1}/{MAX_DB_RETRIES})")
                        if self._restart_async_writer():
                            # Writer restarted successfully, retry buffered commands first
                            self._retry_buffered_commands()
                        continue
                    else:
                        # Final attempt failed, buffer the command
                        self.log_io_diagnostics("Writer permanently failed, entering degraded mode")
                        logging.error("Async writer permanently failed, buffering command")
                        return self._buffer_command(command, args)
                
                # Send command to queue
                self._queue.put((command, args))
                return True
                
            except Exception as e:
                if attempt < MAX_DB_RETRIES:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                    logging.warning(f"Database write failed (attempt {attempt + 1}/{MAX_DB_RETRIES}): {e}. Retrying in {delay:.1f}s")
                    time.sleep(delay)
                else:
                    logging.error(f"All database write attempts failed: {e}. Buffering command.")
                    return self._buffer_command(command, args)
        
        return False
    
    def _restart_async_writer(self):
        """
        Attempt to restart the async database writer process.
        
        Returns:
            bool: True if restart was successful, False otherwise
        """
        try:
            current_time = time.time()
            
            # Prevent too frequent restarts (minimum 30 seconds between attempts)
            if current_time - self._last_restart_time < 30:
                logging.warning("Async writer restart attempted too recently, skipping")
                return False
            
            # Clean up old writer
            if hasattr(self, '_async_writer') and self._async_writer is not None:
                try:
                    if self._async_writer.is_alive():
                        self._async_writer.terminate()
                        self._async_writer.join(timeout=5)
                except Exception as e:
                    logging.warning(f"Error cleaning up old async writer: {e}")
            
            # Clean up old queue
            if hasattr(self, '_queue') and self._queue is not None:
                try:
                    self._queue.close()
                except Exception as e:
                    logging.warning(f"Error closing old queue: {e}")
            
            # Create new queue and writer
            self._queue = multiprocessing.JoinableQueue()
            self._async_writer = self._create_async_writer(self._db_credentials, False)
            self._async_writer.start()
            
            # Wait for initialization
            if not self._async_writer._ready_event.wait(timeout=ASYNC_WRITER_TIMEOUT):
                logging.error("Restarted async writer failed to initialize")
                return False
            
            self._writer_restart_count += 1
            self._last_restart_time = current_time
            logging.info(f"Successfully restarted async writer (restart #{self._writer_restart_count})")
            return True
            
        except Exception as e:
            logging.error(f"Failed to restart async writer: {e}")
            return False
    
    def _buffer_command(self, command, args=None):
        """
        Buffer a failed database command for later retry.
        
        Args:
            command (str): SQL command to buffer
            args (tuple): Optional command arguments
            
        Returns:
            bool: False (indicates command was buffered, not executed)
        """
        try:
            self._failed_commands_buffer.append((command, args, time.time()))
            if len(self._failed_commands_buffer) >= MAX_BUFFERED_COMMANDS:
                logging.warning(f"Command buffer full ({MAX_BUFFERED_COMMANDS} commands), oldest commands will be dropped")
            return False
        except Exception as e:
            logging.error(f"Failed to buffer command: {e}")
            return False
    
    def _retry_buffered_commands(self):
        """
        Attempt to execute all buffered commands after writer recovery.
        """
        if not self._failed_commands_buffer:
            return
        
        retry_count = len(self._failed_commands_buffer)
        logging.info(f"Retrying {retry_count} buffered database commands")
        
        # Process buffered commands in FIFO order
        failed_retries = 0
        while self._failed_commands_buffer:
            try:
                command, args, timestamp = self._failed_commands_buffer.popleft()
                age = time.time() - timestamp
                
                # Skip very old commands (older than 5 minutes)
                if age > 300:
                    logging.warning(f"Skipping old buffered command (age: {age:.1f}s)")
                    continue
                
                # Try to execute the command directly (no retry logic here to avoid recursion)
                if self._async_writer.is_alive():
                    self._queue.put((command, args))
                else:
                    # Writer died again, put command back and stop
                    self._failed_commands_buffer.appendleft((command, args, timestamp))
                    logging.error("Async writer died again while retrying buffered commands")
                    break
                    
            except Exception as e:
                failed_retries += 1
                logging.warning(f"Failed to retry buffered command: {e}")
                if failed_retries > 10:  # Stop if too many consecutive failures
                    logging.error("Too many failures retrying buffered commands, stopping retry")
                    break
        
        remaining = len(self._failed_commands_buffer)
        if remaining > 0:
            logging.warning(f"{remaining} commands remain buffered after retry attempt")
        else:
            logging.info("All buffered commands successfully retried")
    
    def get_resilience_status(self):
        """
        Get current status of database resilience features.
        
        Returns:
            dict: Status information including buffer size, restart count, etc.
        """
        return {
            'writer_alive': self._async_writer.is_alive() if hasattr(self, '_async_writer') else False,
            'buffered_commands': len(self._failed_commands_buffer),
            'restart_count': self._writer_restart_count,
            'last_restart_time': self._last_restart_time,
            'time_since_last_restart': time.time() - self._last_restart_time if self._last_restart_time > 0 else None
        }
    
    def log_io_diagnostics(self, error_context=""):
        """
        Log comprehensive I/O diagnostics to help identify SD card issues.
        
        Args:
            error_context (str): Additional context about when the error occurred
        """
        try:
            status = self.get_resilience_status()
            db_path = getattr(self, '_db_credentials', {}).get('name', 'unknown')
            
            logging.error(f"Database I/O Issue - {error_context}")
            logging.error(f"  Database path: {db_path}")
            logging.error(f"  Writer alive: {status['writer_alive']}")
            logging.error(f"  Buffered commands: {status['buffered_commands']}")
            logging.error(f"  Writer restarts: {status['restart_count']}")
            logging.error(f"  Time since last restart: {status['time_since_last_restart']:.1f}s" if status['time_since_last_restart'] else "Never restarted")
            
            # Check disk space and I/O stats if possible
            if hasattr(os, 'statvfs') and db_path != 'unknown' and os.path.exists(os.path.dirname(db_path)):
                try:
                    statvfs = os.statvfs(os.path.dirname(db_path))
                    # Handle different statvfs implementations
                    if hasattr(statvfs, 'f_available'):
                        free_space = statvfs.f_frsize * statvfs.f_available
                        total_space = statvfs.f_frsize * statvfs.f_blocks
                    else:
                        free_space = statvfs.f_frsize * statvfs.f_bavail
                        total_space = statvfs.f_frsize * statvfs.f_blocks
                    free_percent = (free_space / total_space) * 100
                    logging.error(f"  Disk space: {free_space / (1024**3):.2f}GB free ({free_percent:.1f}% of {total_space / (1024**3):.2f}GB)")
                except Exception as e:
                    logging.error(f"  Could not check disk space: {e}")
            
            # Log recent queue status
            if hasattr(self, '_queue'):
                try:
                    queue_size = self._queue.qsize()
                    logging.error(f"  Queue size: {queue_size}")
                except Exception as e:
                    logging.error(f"  Could not check queue size: {e}")
            
        except Exception as e:
            logging.error(f"Failed to log I/O diagnostics: {e}")

    def _create_table(self, name, fields, engine="InnoDB"):
        """
        Create a database table with specified fields.
        
        Args:
            name (str): Table name
            fields (str): Field definitions for CREATE TABLE
            engine (str): Storage engine (default: InnoDB)
        """
        if engine:
            command = "CREATE TABLE IF NOT EXISTS %s (%s) ENGINE=%s" % (name, fields, engine)
        else:
            command = "CREATE TABLE IF NOT EXISTS %s (%s)" % (name, fields)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)

    def _insert_metadata(self):
        """Insert experimental metadata into METADATA table."""
        for k, v in list(self.metadata.items()):
            # Properly serialize complex metadata values to avoid SQL injection and formatting issues
            v_serialized = json.dumps(str(v)) if not isinstance(v, (str, int, float, bool, type(None))) else v
            
            # Truncate extremely large values as a safety measure
            max_value_length = METADATA_MAX_VALUE_LENGTH
            if isinstance(v_serialized, str) and len(v_serialized) > max_value_length:
                v_serialized = v_serialized[:max_value_length] + "... [TRUNCATED]"
                logging.warning(f"Metadata value for key '{k}' was truncated due to size limit")
            
            # Use database-specific placeholder syntax
            if self._database_type == "SQLite3":
                command = "INSERT INTO METADATA VALUES (?, ?)"
            else:  # MySQL
                command = "INSERT INTO METADATA VALUES (%s, %s)"
            self._write_async_command(command, (k, v_serialized))

    def _wait_for_queue_empty(self):
        """Wait for queue to be processed."""
        while not self._queue.empty():
            logging.info("waiting for queue to be processed")
            time.sleep(QUEUE_CHECK_INTERVAL)

class MySQLResultWriter(BaseResultWriter):
    """
    Main class for writing experimental results to a MySQL database.
    
    This class coordinates multiple helper classes to save different types of data:
    - ROI tracking data
    - DAM-compatible activity summaries
    - Image snapshots
    - Sensor readings
    - Experimental metadata
    
    Attributes:
        _max_insert_string_len (int): Maximum length for batched INSERT commands
        _async_writing_class: Class to use for async database writes
        _null: Value to use for NULL in database
    """
    _description = {
        "overview": "MySQL/MariaDB result writer - stores tracking data to a mySQL/mariadb database server.",
        "arguments": [
            {"name": "db_host", "description": "Database server hostname or IP address", "type": "str", "default": "localhost", "options": ["localhost", "node"]},
            {"name": "take_frame_shots", "description": "Save periodic frame snapshots", "type": "boolean", "default": True},
            {"name": "make_dam_like_table", "description": "Create DAM-compatible activity summary table", "type": "boolean", "default": False}
        ]
    }
    
    _database_type = "MySQL"
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _async_writing_class = AsyncMySQLWriter
    _null = 0
    
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=True, 
                 take_frame_shots=False, erase_old_db=True, sensor=None, db_host="localhost", *args, **kwargs):
        """
        Initialize the MySQL result writer.
        
        Args:
            db_credentials (dict): Database connection credentials
            rois (list): List of ROI objects to track
            metadata (dict): Experimental metadata to store
            make_dam_like_table (bool): Whether to create DAM-compatible activity table
            take_frame_shots (bool): Whether to periodically save image snapshots
            erase_old_db (bool): Whether to drop and recreate database
            sensor: Optional sensor object for environmental data collection
            db_host (str): Database server hostname or IP address
        """
        # Store MySQL-specific parameters for async writer creation
        self._db_host = db_host
        # Call parent initialization with all common logic
        super(MySQLResultWriter, self).__init__(db_credentials, rois, metadata, make_dam_like_table, 
                                         take_frame_shots, erase_old_db, sensor, **kwargs)
    
    def get_last_timestamp(self):
        """
        Connects to the database and retrieves the last timestamp
        from all ROI tables.
        Returns:
            int: The last timestamp in milliseconds, or 0 if not found.
        """
        try:
            db = mysql.connector.connect(
                host=self._db_host,
                user=self._db_credentials["user"],
                passwd=self._db_credentials["password"],
                db=self._db_credentials["name"],
            )
            cursor = db.cursor()
            last_ts = 0
            for roi in self._rois:
                table_name = f"ROI_{roi.idx}"
                cursor.execute(f"SELECT MAX(t) FROM {table_name}")
                result = cursor.fetchone()
                if result and result[0] is not None:
                    last_ts = max(last_ts, result[0])
            cursor.close()
            db.close()
            return last_ts
        except mysql.connector.Error as err:
            logging.error(f"Error getting last timestamp from MySQL: {err}")
            return 0

    def _create_async_writer(self, db_credentials, erase_old_db, **kwargs):
        """Create MySQL-specific async writer."""
        return self._async_writing_class(db_credentials, self._queue, erase_old_db, self._db_host)
    
    def __getstate__(self):
        """Extend base pickle state with MySQL-specific parameters."""
        state = super(MySQLResultWriter, self).__getstate__()
        # Store MySQL-specific parameters
        state['_pickle_extra_kwargs'] = {'db_host': getattr(self, '_db_host', 'localhost')}
        return state

    def _create_all_tables(self):
        """
        Create all necessary database tables for the experiment.
        
        Creates tables for:
        - ROI_MAP: ROI definitions and positions
        - VAR_MAP: Variable type mappings
        - IMG_SNAPSHOTS: Image snapshot storage (if enabled)
        - SENSORS: Sensor data (if sensor provided)
        - CSV_DAM_ACTIVITY: DAM-compatible activity data (if enabled)
        - METADATA: Experimental metadata
        - START_EVENTS: Experiment start/stop events
        """
        if self._erase_old_db:
            logging.info("Creating master table 'ROI_MAP'")
            self._create_table("ROI_MAP", "roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT")
            for r in self._rois:
                fd = r.get_feature_dict()
                command = "INSERT INTO ROI_MAP VALUES %s" % str((fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))
                self._write_async_command(command)

            logging.info("Creating variable map table 'VAR_MAP'")
            self._create_table("VAR_MAP", "var_name CHAR(100), sql_type CHAR(100), functional_type CHAR(100)")
            if self._shot_saver is not None:
                logging.info("Creating table for IMG_screenshots")
                self._create_table(self._shot_saver.table_name, self._shot_saver.create_command)
            if self._sensor_saver is not None:
                logging.info("Creating table for SENSORS data")
                self._create_table(self._sensor_saver.table_name, self._sensor_saver.create_command)

            if self._dam_file_helper is not None:
                logging.info("Creating 'CSV_DAM_ACTIVITY' table")
                fields = self._dam_file_helper.make_dam_file_sql_fields()
                self._create_table("CSV_DAM_ACTIVITY", fields)

            logging.info("Creating 'METADATA' table")
            self._create_table("METADATA", "field CHAR(100), value TEXT")
            logging.info("Creating 'START_EVENTS' table")
            self._create_table("START_EVENTS", "id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY, t INT, event CHAR(100)")
        
            event = "graceful_start"
            command = "INSERT INTO START_EVENTS VALUES (%s, %s, %s)"
            self._write_async_command(command, (self._null, int(time.time()), event))

            # Insert experimental metadata using shared method
            self._insert_metadata()
            
            self._wait_for_queue_empty()
        
        elif not self._erase_old_db and getattr(self, 'database_to_append', None):
            event = "appending"
            command = "INSERT INTO START_EVENTS VALUES (%s, %s, %s)"
            self._write_async_command(command, (self._null, int(time.time()), event))
            self._wait_for_queue_empty()


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

            # Insert experimental metadata using shared method
            self._insert_metadata()
            
            self._wait_for_queue_empty()

        elif not self._erase_old_db and getattr(self, 'database_to_append', None):

            event = "appending"
            command = "INSERT INTO START_EVENTS VALUES (?, ?, ?)"
            self._write_async_command(command, (None, int(time.time()), event))
            self._wait_for_queue_empty()

# =============================================================================================================#
# VARIOUS OTHER CLASSES
#
# =============================================================================================================#


class NpyAppendableFile():
    """
    Custom file format for efficiently appending numpy arrays.
    
    Creates .anpy files that can be incrementally written to without loading
    the entire file into memory. Can be converted to standard .npy format.
    """
    
    def __init__(self, fname, newfile = True):
        """
        Initialize appendable numpy file.
        
        Args:
            fname (str): Base filename (extension will be changed to .anpy)
            newfile (bool): Whether to create new file or append to existing
        """
        filepath, extension = os.path.splitext(fname)
        self.fname = filepath + ".anpy"
        
        self._newfile = newfile
        self._first_write = True
        
    def write(self, data):
        """
        Append array to file.
        
        Args:
            data (np.ndarray): Array to append
            
        Returns:
            bool: True if write successful
        """
        if self._newfile and self._first_write:
            with open(self.fname, "wb") as fh:
                np.save(fh, data)
            self._first_write = False
            return True
        
        else:
        
            with open(self.fname, "ab") as fh:
                np.save(fh, data)
            
            return True
        
        return False
            
    def load(self, axis=2):
        """
        Load entire file contents.
        
        Args:
            axis (int): Axis along which to concatenate arrays
            
        Returns:
            np.ndarray: Concatenated array data
        """
        with open(self.fname, "rb") as fh:
            fsz = os.fstat(fh.fileno()).st_size
            out = np.load(fh)
            while fh.tell() < fsz:
                out = np.concatenate((out, np.load(fh)), axis=axis)
            
        return out
    
    def convert(self, filename=None):
        """
        Convert .anpy file to standard .npy format.
        
        Args:
            filename (str): Output filename (default: same name with .npy)
        """
        content = self.load()
        
        if filename == None:
            filepath, _ = os.path.splitext(self.fname)
            filename = filepath + ".npy"
        
        with open(filename, "wb") as fh:
            np.save(fh, content)
            
        print ("New .npy compatible file saved with name %s. Use numpy.load to load data from it. The array has a shape of %s" % (filename, content.shape))
        
    @property
    def _dtype(self):
        """Get data type of stored arrays."""
        return self.load().dtype
        
    @property
    def _actual_shape(self):
        """Get shape of complete concatenated data."""
        return self.load().shape
    
    @property
    def header(self):
        """
        Read numpy file header information.
        
        Returns:
            tuple: (version, header_dict) with file format information
        """
        with open(self.fname, "rb") as fh:
            version = np.lib.format.read_magic(fh)
            shape, fortran, dtype = np.lib.format._read_array_header(fh, version)
        
        return version, {'descr': dtype,
                         'fortran_order' : fortran,
                         'shape' : shape}
                         
class RawDataWriter():
    """
    Writer for saving raw tracking data for offline analysis.
    
    Saves tracking data as appendable numpy arrays (.anpy files) that can be
    efficiently written during experiments and later converted to standard
    numpy format for analysis.
    """
    
    def __init__(self, basename, n_rois, entities=40):
        """
        Initialize raw data writer.
        
        Args:
            basename (str): Base filename for output files
            n_rois (int): Number of ROIs to track
            entities (int): Maximum number of entities per ROI (default: 40)
        """
        self._basename, _ = os.path.splitext (basename)
        
        self.entities = entities
        self.files = [ NpyAppendableFile (os.path.join("%s_%03d" % (self._basename, n_rois) + ".anpy"), newfile = True ) for r in range(n_rois) ]
        
        self.data = dict()
        
    def flush(self, t, frame):
        """
        Write accumulated data to files.
        
        Args:
            t (int): Current time (unused)
            frame: Current frame (unused)
        """
        for row, fh in zip(self.data, self.files):
            fh.write(self.data[row])
        
    def write(self, t, roi, data_rows):
        """
        Store tracking data for a ROI.
        
        Args:
            t (int): Time in milliseconds
            roi: ROI object with idx property
            data_rows (list): List of DataPoint objects with tracking info
                Each DataPoint contains: x, y, w, h, phi, is_inferred, has_interacted
        """
        #Convert data_rows to an array with shape (nf, 5) where nf is the number of flies in the ROI
        arr = np.asarray([[t, fly['x'], fly['y'], fly['w'], fly['h'], fly['phi']] for fly in data_rows])
        #The size of data_rows depends on how many contours were found. The array needs to have a fixed shape so we round it to self.entities as the max number of flies allowed
        arr.resize((self.entities, 6, 1), refcheck=False)
        self.data[roi.idx] = arr


# =============================================================================================================#
# DATABASE APPENDER META-CLASS
# =============================================================================================================#

class dbAppender(object):
    """
    Meta-class for appending to existing databases.
    
    This class provides a unified interface for appending to both SQLite and MySQL databases.
    It automatically detects the database type, presents available databases to the user,
    and wraps around the appropriate writer class with append functionality enabled.
    
    Features:
    - Auto-detects database type (SQLite vs MySQL) from selected database
    - Presents dropdown list of available databases from cache
    - Wraps around MySQLResultWriter or SQLiteResultWriter with erase_old_db=False
    - Maintains compatibility with existing frontend dropdown population
    """
    
    _description = {
        "overview": "Database appender - automatically detects database type and appends to existing databases. Supports both SQLite and MySQL/MariaDB databases with unified interface.",
        "arguments": [
            {"name": "database_to_append", "description": "Database to append to", "type": "str", "default": "", "asknode": "database_list"},
            {"name": "take_frame_shots", "description": "Save periodic frame snapshots", "type": "boolean", "default": True},
            {"name": "make_dam_like_table", "description": "Create DAM-compatible activity summary table", "type": "boolean", "default": False}
        ]
    }
    
    def __init__(self, db_credentials, rois, metadata=None, database_to_append="", 
                 make_dam_like_table=False, take_frame_shots=False, sensor=None, 
                 db_host="localhost", *args, **kwargs):
        """
        Initialize the database appender meta-class.
        
        Args:
            db_credentials (dict): Database connection credentials
            rois (list): List of ROI objects to track
            metadata (dict): Experimental metadata to store
            database_to_append (str): Name of database to append to
            make_dam_like_table (bool): Whether to create DAM-compatible activity table
            take_frame_shots (bool): Whether to periodically save image snapshots
            sensor: Optional sensor object for environmental data collection
            db_host (str): Database server hostname or IP address (for MySQL)
        """
        self.database_to_append = database_to_append
        self.erase_old_db = False
        self.db_credentials = db_credentials

        self.rois = rois
        self.metadata = metadata
        self.make_dam_like_table = make_dam_like_table
        self.take_frame_shots = take_frame_shots
        self.sensor = sensor
        self.db_host = db_host
        self.args = args
        self.kwargs = kwargs
        
        # Detect database type and create appropriate writer
        self._detect_database_type_and_create_writer()

        logging.info(f"We will be appending database: {database_to_append}")        
    
    def _detect_database_type_and_create_writer(self):
        """
        Auto-detect database type from the selected database and create appropriate writer.
        """
        if not self.database_to_append:
            raise ValueError("database_to_append parameter is required")
        
        # Detect database type based on file extension and existence
        db_type = self._detect_database_type(self.database_to_append)
        
        if db_type == "SQLite":
            logging.info(f"Detected SQLite database: {self.database_to_append}")
            self._create_sqlite_writer()
        elif db_type == "MySQL":
            logging.info(f"Detected MySQL database: {self.database_to_append}")
            self._create_mysql_writer()
        else:
            raise ValueError(f"Could not detect database type for: {self.database_to_append}")
    
    def _detect_database_type(self, database_name):
        """
        Detect whether the selected database is SQLite or MySQL.
        
        Args:
            database_name (str): Name/path of the database
            
        Returns:
            str: "SQLite" or "MySQL" or None if cannot detect
        """
        # Method 1: Check if it's a file path with SQLite extension
        if database_name.endswith('.db') or database_name.endswith('.sqlite') or database_name.endswith('.sqlite3'):
            return "SQLite"
        
        # Method 2: Check if file exists in common SQLite locations
        sqlite_paths = [
            f"/ethoscope_data/results/{database_name}",
            f"/ethoscope_data/results/{database_name}.db",
            database_name  # If full path is provided
        ]
        
        for path in sqlite_paths:
            if os.path.exists(path):
                return "SQLite"
        
        # Method 3: Check cache for database information
        try:
            from .cache import get_all_databases_info
            device_name = self.db_credentials.get("name", "ETHOSCOPE_DEFAULT")
            if isinstance(device_name, str) and not device_name.startswith("ETHOSCOPE_"):
                # If device_name is a path (SQLite), extract device ID for cache lookup
                import re
                device_match = re.search(r'([a-f0-9]{32})', device_name)
                if device_match:
                    device_name = f"ETHOSCOPE_{device_match.group(1)[:8].upper()}"
            
            databases_info = get_all_databases_info(device_name)
            
            # Check SQLite databases
            if databases_info.get("SQLite", {}).get(database_name):
                return "SQLite"
            
            # Check MySQL databases  
            if databases_info.get("MariaDB", {}).get(database_name):
                return "MySQL"
                
        except Exception as e:
            logging.warning(f"Could not check cache for database type detection: {e}")
        
        # Method 4: Default assumption based on database name patterns
        # If no file extension and not found as file, assume MySQL
        if '/' not in database_name and '\\' not in database_name and '.' not in database_name:
            return "MySQL"
        
        return None
    
    def _create_sqlite_writer(self):
        """Create SQLite writer with append functionality."""
        # Update db_credentials to point to the existing database
        sqlite_db_credentials = self.db_credentials.copy()
        
        # Find the actual path to the SQLite database
        sqlite_path = self._find_sqlite_database_path(self.database_to_append)
        if not sqlite_path:
            raise FileNotFoundError(f"SQLite database not found: {self.database_to_append}")
        
        sqlite_db_credentials["name"] = sqlite_path

        # Create SQlite writer with erase_old_db=False for append functionality
        self.kwargs.update({'erase_old_db': False})
        self._writer = SQLiteResultWriter(
            db_credentials=sqlite_db_credentials,
            rois=self.rois,
            metadata=self.metadata,
            make_dam_like_table=self.make_dam_like_table,
            take_frame_shots=self.take_frame_shots,
            sensor=self.sensor,
            *self.args,
            **self.kwargs
        )
    
    def _create_mysql_writer(self):
        """Create MySQL writer with append functionality."""
        # Update db_credentials to point to the existing database
        mysql_db_credentials = self.db_credentials.copy()
        mysql_db_credentials["name"] = self.database_to_append
        
        # Create MySQL writer with erase_old_db=False for append functionality
        self.kwargs.update({'erase_old_db': False})
        self._writer = MySQLResultWriter(
            db_credentials=mysql_db_credentials,
            rois=self.rois,
            metadata=self.metadata,
            make_dam_like_table=self.make_dam_like_table,
            take_frame_shots=self.take_frame_shots,
            sensor=self.sensor,
            db_host=self.db_host,
            *self.args,
            **self.kwargs
        )
    
    def _find_sqlite_database_path(self, database_name):
        """
        Find the actual file path for a SQLite database.
        
        Args:
            database_name (str): Name or partial path of database
            
        Returns:
            str: Full path to database file, or None if not found
        """
        # If full path is provided and exists, use it
        if os.path.exists(database_name):
            logging.info(f"Found SQLite database at: {database_name}")
            return database_name
        
        # Get the basename and ensure it has .db extension
        db_basename = os.path.basename(database_name)
        if not db_basename.endswith('.db'):
            db_basename += '.db'
        
        # Walk the filesystem starting from common ethoscope data locations
        search_roots = ["/ethoscope_data/results", "/data"]
        
        for search_root in search_roots:
            if not os.path.exists(search_root):
                continue
                
            try:
                for root, dirs, files in os.walk(search_root):
                    if db_basename in files:
                        full_path = os.path.join(root, db_basename)
                        logging.info(f"Found SQLite database at: {full_path}")
                        return full_path
            except Exception as e:
                logging.warning(f"Error walking directory {search_root}: {e}")
                continue
        
        logging.warning(f"Could not find SQLite database: {database_name}")
        return None
    
    @classmethod
    def get_available_databases(cls, db_credentials, device_name=""):
        """
        Get list of available databases for the dropdown interface.
        
        Args:
            db_credentials (dict): Database connection credentials
            device_name (str): Name of the device
            
        Returns:
            list: List of database dictionaries for frontend dropdown
        """
        databases_list = []
        
        try:
            from .cache import get_all_databases_info
            
            # Extract device name from credentials if not provided
            if not device_name and "name" in db_credentials:
                device_name = db_credentials["name"]
                if isinstance(device_name, str) and not device_name.startswith("ETHOSCOPE_"):
                    # Extract device ID from path for cache lookup
                    import re
                    device_match = re.search(r'([a-f0-9]{32})', device_name)
                    if device_match:
                        device_name = f"ETHOSCOPE_{device_match.group(1)[:8].upper()}"
            
            databases_info = get_all_databases_info(device_name)
            
            # Add SQLite databases
            sqlite_dbs = databases_info.get("SQLite", {})
            for db_name, db_info in sqlite_dbs.items():
                if db_info.get("file_exists", False) and db_info.get("filesize", 0) > 32768:  # > 32KB
                    databases_list.append({
                        "name": db_name,
                        "type": "SQLite",
                        "active": True,
                        "size": db_info.get("filesize", 0),
                        "status": db_info.get("db_status", "unknown"),
                        "path": db_info.get("path", "")
                    })
            
            # Add MySQL databases
            mysql_dbs = databases_info.get("MariaDB", {})
            for db_name, db_info in mysql_dbs.items():
                databases_list.append({
                    "name": db_name,
                    "type": "MySQL",
                    "active": True,
                    "size": db_info.get("db_size_bytes", 0),
                    "status": db_info.get("db_status", "unknown")
                })
                
        except Exception as e:
            logging.error(f"Error getting available databases: {e}")
        
        return databases_list
    
    # Delegate all other methods to the wrapped writer
    def __getattr__(self, name):
        """Delegate all method calls to the wrapped writer instance."""
        return getattr(self._writer, name)
    
    def __enter__(self):
        """Context manager entry - delegate to wrapped writer."""
        return self._writer.__enter__()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - delegate to wrapped writer."""
        return self._writer.__exit__(exc_type, exc_val, exc_tb)