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
   DatabaseMetadataCache (manages database metadata caching with automatic fallback)

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
from collections import OrderedDict
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
        values = [0] + date_time_fields
        for i in range(1, self._n_rois +1):
            values.append(int(round(self._scale * vals[i])))
        command = '''INSERT INTO CSV_DAM_ACTIVITY VALUES %s''' % str(tuple(values))
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
        self._last_t, self._last_flush_t, self._last_dam_t = [0] * 3
        self._metadata = metadata
        self._rois = rois
        self._db_credentials = db_credentials
        self._make_dam_like_table = make_dam_like_table
        self._take_frame_shots = take_frame_shots
        
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
        if (self._database_type == "MySQL" and erase_old_db) or self._database_type == "SQLite3":
            logging.warning("Waiting for async writer to initialize database...")
            # Wait for async writer to complete database initialization
            if not self._async_writer._ready_event.wait(timeout=ASYNC_WRITER_TIMEOUT):
                if self._async_writer.is_alive():
                    raise Exception(f"Async database writer failed to initialize within {ASYNC_WRITER_TIMEOUT} seconds - check database connection")
                else:
                    raise Exception("Async database writer process died during initialization - check database configuration and logs")
            
            logging.warning("Creating database tables...")
            self._create_all_tables()

        elif self._database_type == "MySQL" and not erase_old_db:
            event = "crash_recovery"
            command = "INSERT INTO START_EVENTS VALUES (%s, %s, %s)"
            self._write_async_command(command, (self._null, int(time.time()), event))

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
            self._async_writer.join()
            logging.info("Joined OK")
            
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
            self._dam_file_helper.input_roi_data(t, roi, data_rows)
    
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
        Send SQL command to async writer process.
        
        Args:
            command (str): SQL command to execute
            args (tuple): Optional arguments for parameterized query
            
        Raises:
            Exception: If async writer has died
        """
        # Check if async writer is still alive (already waited for ready during init)
        if not self._async_writer.is_alive():
            raise Exception("Async database writer has stopped unexpectedly")
        
        # Send command to queue with error handling
        try:
            self._queue.put((command, args))
        except Exception as e:
            raise Exception(f"Failed to send command to async writer: {e}")

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
                 take_frame_shots=False, db_host="localhost", sensor=None, *args, **kwargs):
        """
        Initialize SQLite result writer.
        
        Note: DAM-like tables are disabled by default for SQLite.
        Args:
            db_host: Ignored for SQLite (file-based), kept for compatibility
            sensor: Optional sensor object for environmental data collection
        """
        # SQLite-specific parameter overrides
        # Remove any conflicting arguments from kwargs to avoid duplicate argument errors
        kwargs.pop('erase_old_db', None)
        
        # SQLite databases are unique per experiment, don't erase them
        erase_old_db = False
        
        # Call parent initialization with all common logic
        super(SQLiteResultWriter, self).__init__(db_credentials, rois, metadata, make_dam_like_table, 
                                                 take_frame_shots, erase_old_db, sensor, **kwargs)
    
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
        Send SQL command to async writer process with SQLite placeholder conversion.
        
        Args:
            command (str): SQL command to execute (may contain MySQL placeholders)
            args (tuple): Optional arguments for parameterized query
            
        Raises:
            Exception: If async writer is not ready or has died
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
            
        # Wait for the async writer to be ready before sending commands
        if not self._async_writer._ready_event.wait(timeout=ASYNC_WRITER_TIMEOUT):
            if self._async_writer.is_alive():
                raise Exception(f"Async database writer failed to initialize within {ASYNC_WRITER_TIMEOUT} seconds - check SQLite connection")
            else:
                raise Exception("Async database writer process died during initialization - check SQLite configuration and logs")
        
        if not self._async_writer.is_alive():
            raise Exception("Async database writer has stopped unexpectedly")
        self._queue.put((sqlite_command, sqlite_args))

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
            self._dam_file_helper.input_roi_data(t, roi, data_rows)

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
        with sqlite3.connect(db_path, timeout=30.0) as conn:
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

