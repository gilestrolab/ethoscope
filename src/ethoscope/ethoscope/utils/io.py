"""
Database Writers for Ethoscope Experiment Data Storage

This module provides various classes for storing experimental tracking data from the Ethoscope
behavioral monitoring system. The classes support multiple database backends (MySQL/MariaDB, SQLite)
and different output formats (database tables, numpy arrays).

Class Hierarchy and Relationships:
==================================

1. Database Writers (Main Interface):
   ResultWriter (base class for database storage)
   ├── SQLiteResultWriter (extends ResultWriter for SQLite-specific behavior)
   └── rawdatawriter (independent class for numpy array storage)

2. Async Database Processes (Multiprocessing):
   multiprocessing.Process
   ├── AsyncMySQLWriter (handles MySQL/MariaDB writes in separate process)
   └── AsyncSQLiteWriter (handles SQLite writes in separate process)

3. Helper Classes (Data Formatting):
   SensorDataToMySQLHelper (formats sensor data for database storage)
   ImgToMySQLHelper (handles image snapshot storage as BLOBs)
   DAMFileHelper (creates DAM-compatible activity summaries)

4. Utility Classes:
   Null (special NULL representation for SQLite)
   npyAppendableFile (custom numpy array file format for incremental writes)
   DatabaseMetadataCache (manages database metadata caching with automatic fallback)

Interaction Flow:
================
1. ResultWriter/SQLiteResultWriter creates an async writer process (AsyncMySQLWriter/AsyncSQLiteWriter)
2. ResultWriter sends SQL commands through a multiprocessing queue to the async writer
3. ResultWriter uses helper classes to format different data types:
   - DAMFileHelper for activity summaries
   - ImgToMySQLHelper for periodic screenshots
   - SensorDataToMySQLHelper for environmental sensor data
4. rawdatawriter operates independently, saving raw data directly to numpy array files

Key Design Patterns:
===================
- Multiprocessing: Async writers run in separate processes to prevent I/O blocking
- Producer-Consumer: Main thread produces SQL commands, async writer consumes them
- Template Method: ResultWriter provides base implementation, SQLiteResultWriter overrides specific methods
- Helper Pattern: Separate classes handle formatting for different data types
- Context Manager: ResultWriter implements __enter__/__exit__ for proper cleanup
"""

import multiprocessing
import time, datetime
import traceback
import logging
from collections import OrderedDict
import tempfile
import os, glob
import hashlib
import subprocess
import numpy as np
import sqlite3
import mysql.connector
                
import urllib.request, urllib.error, urllib.parse
import json
from cv2 import imwrite, IMWRITE_JPEG_QUALITY

# Character encoding for MariaDB/MySQL connections
SQL_CHARSET = 'latin1'

class AsyncMySQLWriter(multiprocessing.Process):
    """
    Asynchronous MySQL/MariaDB database writer that runs in a separate process.
    
    This class handles all database write operations in a separate process to prevent
    blocking the main data collection thread. It uses a queue to receive SQL commands
    from the main process and executes them sequentially.
    
    Attributes:
        _db_host (str): Database host address (default: "localhost")
    """
    
    _db_host = "localhost"
    #_db_host = "node" #uncomment this to save data on the node
    
    def __init__(self, db_credentials, queue, erase_old_db=True):
        """
        Initialize the async MySQL writer process.
        
        Args:
            db_credentials (dict): Database credentials containing:
                - name: Database name
                - user: Database username
                - password: Database password
            queue (multiprocessing.Queue): Queue for receiving SQL commands
            erase_old_db (bool): Whether to drop and recreate the database on startup
        """
        self._db_name = db_credentials["name"]
        self._db_user_name = db_credentials["user"]
        self._db_user_pass = db_credentials["password"]
        self._erase_old_db = erase_old_db
        self._queue = queue
        self._ready_event = multiprocessing.Event()
        super(AsyncMySQLWriter,self).__init__()


    def _delete_my_sql_db(self):
        """
        Delete the existing MySQL database if it exists.
        
        This method connects to MySQL, truncates all tables for performance,
        resets binary logs if enabled, and then drops the entire database.
        """
        try:
            logging.info(f"Attempting to connect to mysql db {self._db_name} on host {self._db_host} as {self._db_user_name}:{self._db_user_name}")
            db = mysql.connector.connect(host=self._db_host,
                                         user=self._db_user_name,
                                         passwd=self._db_user_name,
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
        #Truncate all tables before dropping db for performance
        command = "SHOW TABLES"
        c.execute(command)
        tables = c.fetchall()
        # In case we use binary logging, we remove bin logs to save space.
        # However, this will throw an error if binary logging is set to off
        # Which is what we should be doing because it reduces disk access and we do not need it anyway
        c.execute("SHOW VARIABLES LIKE 'log_bin';")
        log_bin_status = c.fetchone()
        if log_bin_status and log_bin_status[1] == 'ON':
            logging.info("The binary logs are set to true. Resetting them to save space.")
            c.execute("RESET MASTER")
        to_execute  = []
        for t in tables:
            t = t[0]
            command = "TRUNCATE TABLE %s" % t
            to_execute.append(command)

        logging.info("Truncating all database tables")

        for te in to_execute:
            c.execute(te)
        db.commit()
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
        
    def run(self):
        """
        Main process loop for the async writer.
        
        Continuously processes SQL commands from the queue until a 'DONE' message
        is received. Handles connection errors and attempts to maintain database
        connectivity throughout the experiment.
        """
        db = None
        do_run = True
        
        try:
            logging.info("AsyncMySQLWriter starting up...")
            if self._erase_old_db:
                logging.info("Deleting old database...")
                self._delete_my_sql_db()
                logging.info("Creating new database...")
                self._create_mysql_db()
            logging.info("Getting database connection...")
            db = self._get_connection()
            logging.info("Database connection established successfully")
            
            # Signal that the writer is ready to accept commands
            logging.info("AsyncMySQLWriter ready to accept commands")
            self._ready_event.set()
        
            while do_run:
                try:
                    msg = self._queue.get()
                    if (msg == 'DONE'):
                        do_run=False
                        continue
                    command, args = msg
                    c = db.cursor()
                    if args is None:
                        c.execute(command)
                    else:
                        c.execute(command, args)
                    db.commit()
                except Exception as e:
                    try:
                        logging.error("Failed to run mysql command:\n%s" % command)
                        logging.error("Error details: %s" % str(e))
                        logging.error("Traceback: %s" % traceback.format_exc())
                        
                        # Check if this is a critical error that should stop the writer
                        error_str = str(e).lower()
                        critical_errors = ['access denied', 'connection', 'server has gone away', 'lost connection']
                        is_critical = any(critical_error in error_str for critical_error in critical_errors)
                        
                        if is_critical:
                            logging.error("Critical database error detected, stopping async writer")
                            do_run = False
                        else:
                            logging.warning("Non-critical database error, continuing operations")
                            
                    except:
                        logging.error("Did not retrieve queue value or failed to process error")
                        do_run = False
                finally:
                    if self._queue.empty():
                        #we sleep if we have an empty queue. this way, we don't over use a cpu
                        time.sleep(.1)
        except KeyboardInterrupt as e:
            logging.warning("DB async process interrupted with KeyboardInterrupt")
            # Ensure ready event is set even if interrupted
            # This prevents the main thread from hanging indefinitely
            self._ready_event.set()
            raise e
        except Exception as e:
            logging.error("DB async process stopped with an exception: %s", str(e))
            logging.error("Exception traceback: %s", traceback.format_exc())
            # Ensure ready event is set even if there's an error during startup
            # This prevents the main thread from hanging indefinitely
            self._ready_event.set()
            raise e
        finally:
            logging.info("Closing async mysql writer")
            while not self._queue.empty():
                self._queue.get()
            self._queue.close()
            if db is not None:
                db.close()
                
class SensorDataToMySQLHelper(object):
    """
    Helper class for saving sensor data to MySQL at regular intervals.
    
    This class manages the periodic sampling and storage of sensor readings
    (e.g., temperature, humidity) into the database.
    
    Attributes:
        _table_name (str): Name of the sensor data table
        _base_headers (dict): Base columns for the sensor table (id and timestamp)
    """
    _table_name = "SENSORS"
    _base_headers = {"id" : "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", 
                     "t"  : "INT" }
                          
    def __init__(self, sensor, period=120.0):
        """
        Initialize the sensor data helper.
        
        Args:
            sensor: Sensor object with read_all() method and sensor_types property
            period (float): Sampling period in seconds (default: 120s)
        """
        self._period = period
        self._last_tick = 0
        self.sensor = sensor
        self._table_headers = {**self._base_headers, **self.sensor.sensor_types}
        
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
        
    @property
    def create_command(self):
        """Generate SQL CREATE TABLE command for sensor data."""
        return ",".join([ "%s %s" % (key, self._table_headers[key]) for key in self._table_headers])

class ImgToMySQLHelper(object):
    """
    Helper class for saving image snapshots to MySQL at regular intervals.
    
    This class handles periodic capture and storage of JPEG-compressed images
    from the experiment video feed into the database as BLOBs.
    
    Attributes:
        _table_name (str): Name of the image snapshots table
        _table_headers (dict): Column definitions for the snapshots table
    """
    _table_name = "IMG_SNAPSHOTS"
    _table_headers = {"id" : "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", 
                      "t"  : "INT",
                      "img" : "LONGBLOB"}
                      
    @property
    def table_name (self):
        """Get the image snapshots table name."""
        return self._table_name
        
    @property
    def create_command(self):
        """Generate SQL CREATE TABLE command for image snapshots."""
        return ",".join([ "%s %s" % (key, self._table_headers[key]) for key in self._table_headers])
    
    def __init__(self, period=300.0):
        """
        Initialize the image snapshot helper.
        
        Args:
            period (float): Snapshot interval in seconds (default: 300s/5min)
        """
        self._period = period
        self._last_tick = 0
        self._tmp_file = tempfile.mktemp(prefix="ethoscope_", suffix=".jpg")
        
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
    
    def __init__(self, period=60.0, n_rois=32):
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
        
class ResultWriter(object):
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
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _async_writing_class = AsyncMySQLWriter
    _null = 0
    
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=True, 
                 take_frame_shots=False, erase_old_db=True, sensor=None, *args, **kwargs):
        """
        Initialize the result writer with various data collection options.
        
        Args:
            db_credentials (dict): Database connection credentials
            rois (list): List of ROI objects to track
            metadata (dict): Experimental metadata to store
            make_dam_like_table (bool): Whether to create DAM-compatible activity table
            take_frame_shots (bool): Whether to periodically save image snapshots
            erase_old_db (bool): Whether to drop and recreate database
            sensor: Optional sensor object for environmental data collection
        """
        self._queue = multiprocessing.JoinableQueue()
        self._async_writer = self._async_writing_class(db_credentials, self._queue, erase_old_db)
        self._async_writer.start()
        self._last_t, self._last_flush_t, self._last_dam_t = [0] * 3
        self._metadata = metadata
        self._rois = rois
        self._db_credentials = db_credentials
        self._make_dam_like_table = make_dam_like_table
        self._take_frame_shots = take_frame_shots
        if make_dam_like_table:
            self._dam_file_helper = DAMFileHelper(n_rois=len(rois))
        else:
            self._dam_file_helper = None
        if take_frame_shots:
            self._shot_saver = ImgToMySQLHelper()
        else:
            self._shot_saver = None
        self._insert_dict = {}
        if self._metadata is None:
            self._metadata  = {}
        if sensor is not None:
            self._sensor_saver = SensorDataToMySQLHelper(sensor)
            logging.info("Creating connection to a sensor to store its data in the db")
        else:
            self._sensor_saver = None
        
        self._var_map_initialised = False
        
        if erase_old_db:
            logging.warning("Erasing the old database and recreating the tables")
            self._create_all_tables()
            
        else:
            event = "crash_recovery"
            command = "INSERT INTO START_EVENTS VALUES (%s, %s, %s)"
            self._write_async_command(command, (self._null, int(time.time()), event))
        logging.info("Result writer initialised")
        
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

        for k,v in list(self.metadata.items()):
            # Properly serialize complex metadata values to avoid SQL injection and formatting issues
            v_serialized = json.dumps(str(v)) if not isinstance(v, (str, int, float, bool, type(None))) else v
            
            # Truncate extremely large values as a safety measure (TEXT supports up to 65KB)
            max_value_length = 60000
            if isinstance(v_serialized, str) and len(v_serialized) > max_value_length:
                v_serialized = v_serialized[:max_value_length] + "... [TRUNCATED]"
                logging.warning(f"Metadata value for key '{k}' was truncated due to size limit")
            
            command = "INSERT INTO METADATA VALUES (%s, %s)"
            self._write_async_command(command, (k, v_serialized))
        
        while not self._queue.empty():
            logging.info("waiting for queue to be processed")
            time.sleep(.1)
            
    @property
    def metadata(self):
        """Get experimental metadata dictionary."""
        return self._metadata
        
    def write(self, t, roi, data_rows):
        """
        Write tracking data for a specific ROI at given time.
        
        Args:
            t (int): Time in milliseconds
            roi: ROI object being tracked
            data_rows (list): List of data points for tracked objects in ROI
        """
        #fixme
        dr = data_rows[0]
        if not self._var_map_initialised:
            for r in self._rois:
                self._initialise(r, dr)
            self._initialise_var_map(dr)
        self._add(t, roi, data_rows)
        self._last_t = t
        # now this is irrelevant when tracking multiple animals
        if self._dam_file_helper is not None:
            self._dam_file_helper.input_roi_data(t, roi, dr)
            
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
        t = int(round(t))
        roi_id = roi.idx
        for dr in data_rows:
            tp = (0, t) + tuple(dr.values())
            if roi_id not in self._insert_dict  or self._insert_dict[roi_id] == "":
                command = 'INSERT INTO ROI_%i VALUES %s' % (roi_id, str(tp))
                self._insert_dict[roi_id] = command
            else:
                self._insert_dict[roi_id] += ("," + str(tp))
                
    def _initialise_var_map(self,  data_row):
        """
        Initialize the variable mapping table with data types.
        
        Args:
            data_row: Sample data row to extract variable information
        """
        logging.info("Filling 'VAR_MAP' with values")
        # we recreate var map so we do not have duplicate entries
        self._write_async_command("DELETE FROM VAR_MAP")
        for dt in list(data_row.values()):
            command = "INSERT INTO VAR_MAP VALUES %s"% str((dt.header_name, dt.sql_data_type, dt.functional_type))
            self._write_async_command(command)
        self._var_map_initialised = True

    def _initialise(self, roi, data_row):
        """
        Initialize a ROI-specific data table.
        
        Args:
            roi: ROI object
            data_row: Sample data row to determine column structure
        """
        # We make a new dir to store results
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY" ,"t INT"]
        for dt in list(data_row.values()):
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))
        fields = ", ".join(fields)
        table_name = "ROI_%i" % roi.idx
        self._create_table(table_name, fields)

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
                time.sleep(.1)
        except Exception as e:
            logging.error("Error writing metadata stop time:")
            logging.error(traceback.format_exc())
        finally:
            logging.info("Closing mysql async queue")
            self._queue.put("DONE")
            logging.info("Freeing queue")
            self._queue.cancel_join_thread()
            logging.info("Joining thread")
            self._async_writer.join()
            logging.info("Joined OK")
            
    def close(self):
        """Placeholder close method."""
        pass
        
    def _write_async_command(self, command, args=None):
        """
        Send SQL command to async writer process.
        
        Args:
            command (str): SQL command to execute
            args (tuple): Optional arguments for parameterized query
            
        Raises:
            Exception: If async writer is not ready or has died
        """
        # Wait for the async writer to be ready before sending commands
        if not self._async_writer._ready_event.wait(timeout=30):
            if self._async_writer.is_alive():
                raise Exception("Async database writer failed to initialize within 30 seconds - check MariaDB connection")
            else:
                raise Exception("Async database writer process died during initialization - check MariaDB configuration and logs")
        
        if not self._async_writer.is_alive():
            raise Exception("Async database writer has stopped unexpectedly")
        self._queue.put((command, args))
        
    def _create_table(self, name, fields, engine="InnoDB"):
        """
        Create a database table with specified fields.
        
        Args:
            name (str): Table name
            fields (str): Field definitions for CREATE TABLE
            engine (str): Storage engine (default: InnoDB)
        """
        command = "CREATE TABLE IF NOT EXISTS %s (%s) ENGINE %s KEY_BLOCK_SIZE=16;" % (name, fields, engine)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)
        
    def __getstate__(self):
        """Prepare object for pickling."""
        return {"args": {"db_credentials": self._db_credentials,
                         "rois": self._rois,
                         "metadata": self._metadata,
                         "make_dam_like_table": self._make_dam_like_table,
                         "take_frame_shots": self._take_frame_shots,
                         "erase_old_db": False}}
                         
    def __setstate__(self, state):
        """Restore object from pickled state."""
        self.__init__(**state["args"])

class AsyncSQLiteWriter(multiprocessing.Process):
    """
    Asynchronous SQLite database writer running in a separate process.
    
    Similar to AsyncMySQLWriter but for SQLite databases. Uses specific
    PRAGMA settings for optimal performance with single-writer pattern.
    
    Attributes:
        _pragmas (dict): SQLite PRAGMA settings for performance optimization
    """
    _pragmas = {"temp_store": "MEMORY",
                "journal_mode": "OFF",
                "locking_mode":  "EXCLUSIVE"}
                
    def __init__(self, db_name, queue, erase_old_db=True):
        """
        Initialize the async SQLite writer.
        
        Args:
            db_name (str): Path to SQLite database file
            queue (multiprocessing.Queue): Queue for receiving SQL commands
            erase_old_db (bool): Whether to delete existing database
        """
        self._db_name = db_name
        self._queue = queue
        self._erase_old_db =  erase_old_db
        super(AsyncSQLiteWriter,self).__init__()
        
        if erase_old_db:
            try:
                os.remove(self._db_name)
            except:
                pass
            conn = self._get_connection()
            c = conn.cursor()
            logging.info("Setting DB parameters'")
            for k,v in list(self._pragmas.items()):
                command = "PRAGMA %s = %s" %(str(k), str(v))
                c.execute(command)
        
    def _get_connection(self):
        """
        Create SQLite database connection.
        
        Returns:
            sqlite3.Connection: Database connection object
        """
        db =   sqlite3.connect(self._db_name)
        return db

    def run(self):
        """
        Main process loop for SQLite async writer.
        
        Processes SQL commands from queue until 'DONE' message received.
        """
        db = None
        do_run = True
        try:
            db = self._get_connection()
            while do_run:
                try:
                    msg = self._queue.get()
                    if (msg == 'DONE'):
                        do_run=False
                        continue
                    command, args = msg

                    c = db.cursor()
                    if args is None:
                        c.execute(command)
                    else:
                        c.execute(command, args)
                    db.commit()
                except:
                    do_run=False
                    try:
                        logging.error("Failed to run mysql command:\n%s" % command)
                    except:
                        logging.error("Did not retrieve queue value")
                finally:
                    if self._queue.empty():
                        #we sleep if we have an empty queue. this way, we don't over use a cpu
                        time.sleep(.1)
        except KeyboardInterrupt as e:
            logging.warning("DB async process interrupted with KeyboardInterrupt")
            # Ensure ready event is set even if interrupted
            # This prevents the main thread from hanging indefinitely
            self._ready_event.set()
            raise e
        except Exception as e:
            logging.error("DB async process stopped with an exception: %s", str(e))
            logging.error("Exception traceback: %s", traceback.format_exc())
            # Ensure ready event is set even if there's an error during startup
            # This prevents the main thread from hanging indefinitely
            self._ready_event.set()
            raise e
        finally:
            logging.info("Closing async mysql writer")
            while not self._queue.empty():
                self._queue.get()
            self._queue.close()
            if db is not None:
                db.close()
                
class Null(object):
    """
    Special NULL representation for SQLite compatibility.
    
    SQLite requires NULL for auto-increment fields instead of 0.
    """
    def __repr__(self):
        return "NULL"
    def __str__(self):
        return "NULL"
        
class SQLiteResultWriter(ResultWriter):
    """
    SQLite-specific result writer.
    
    Extends ResultWriter with SQLite-specific modifications including:
    - Use of AsyncSQLiteWriter instead of AsyncMySQLWriter
    - NULL instead of 0 for auto-increment fields
    - Removal of MySQL-specific table options
    """
    _async_writing_class = AsyncSQLiteWriter
    _null= Null()
    
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=False, 
                 take_frame_shots=False, *args, **kwargs):
        """
        Initialize SQLite result writer.
        
        Note: DAM-like tables are disabled by default for SQLite.
        """
        super(SQLiteResultWriter, self).__init__(db_credentials, rois, metadata,
                                                make_dam_like_table, take_frame_shots, *args, **kwargs)

    def _create_table(self, name, fields, engine=None):
        """
        Create SQLite table (ignores engine parameter).
        
        Args:
            name (str): Table name
            fields (str): Field definitions
            engine: Ignored for SQLite
        """
        fields = fields.replace("NOT NULL", "")
        command = "CREATE TABLE IF NOT EXISTS %s (%s)" % (name,fields)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)
        
    def _add(self, t, roi, data_rows):
        """
        Add data with SQLite-specific NULL handling.
        
        Uses NULL object instead of 0 for auto-increment primary keys.
        """
        t = int(round(t))
        roi_id = roi.idx
        for dr in data_rows:
            # here we use NULL because SQLite does not support '0' for auto index
            tp = (self._null, t) + tuple(dr.values())
            if roi_id not in self._insert_dict  or self._insert_dict[roi_id] == "":
                command = 'INSERT INTO ROI_%i VALUES %s' % (roi_id, str(tp))
                self._insert_dict[roi_id] = command
            else:
                self._insert_dict[roi_id] += ("," + str(tp))
                

class npyAppendableFile():
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
                         
class rawdatawriter():
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
        self.files = [ npyAppendableFile (os.path.join("%s_%03d" % (self._basename, n_rois) + ".anpy"), newfile = True ) for r in range(n_rois) ]
        
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


class DatabaseMetadataCache:
    """
    Manages database metadata caching for ethoscope experiments.
    
    This class provides a clean interface for:
    - Querying database metadata with accurate size calculation
    - Creating and managing cache files based on experiment timestamps
    - Reading cached metadata when database is unavailable
    - Finalizing cache files when experiments end
    """
    
    def __init__(self, db_credentials, device_name="", cache_dir="/ethoscope_data/cache"):
        self.db_credentials = db_credentials
        self.device_name = device_name
        self.cache_dir = cache_dir
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
    
    def _get_cache_file_path(self, tracking_start_time):
        """Determine cache file path based on experiment timing."""
        if not self.device_name:
            return None
            
        if tracking_start_time:
            # Use provided timestamp
            ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(tracking_start_time))
            cache_filename = f"db_metadata_{ts_str}_{self.device_name}_db.json"
            return os.path.join(self.cache_dir, cache_filename)
        
        # Try to get timestamp from metadata table
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
                cursor.execute("SELECT value FROM METADATA WHERE field = 'date_time'")
                result = cursor.fetchone()
                if result:
                    metadata_start_time = float(result[0])
                    ts_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(metadata_start_time))
                    cache_filename = f"db_metadata_{ts_str}_{self.device_name}_db.json"
                    return os.path.join(self.cache_dir, cache_filename)
        except Exception as e:
            logging.warning(f"Could not retrieve experiment start time from metadata: {e}")
        
        return None
    
    def _query_database(self):
        """Query database for metadata including size and table counts."""
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
            
            # Get table counts
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            
            table_counts = {}
            for table in tables:
                try:
                    if table in ["ROI_MAP", "VAR_MAP", "METADATA"]:
                        cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                    else:
                        cursor.execute(f"SELECT COALESCE(MAX(id), 0) FROM `{table}`")
                    
                    result = cursor.fetchone()
                    table_counts[table] = result[0] if result and result[0] is not None else 0
                except mysql.connector.Error:
                    table_counts[table] = 0
            
            return {
                "db_size_bytes": int(db_size),
                "table_counts": table_counts,
                "last_db_update": time.time()
            }
    
    def _write_cache(self, cache_file_path, db_info=None, tracking_start_time=None, finalise=False):
        """Write or update cache file."""
        try:
            # Read existing cache file or create new one
            if os.path.exists(cache_file_path):
                with open(cache_file_path, 'r') as f:
                    cache_data = json.load(f)
            else:
                if finalise:
                    logging.warning(f"Cannot finalize non-existent cache file: {cache_file_path}")
                    return
                # Create new cache file
                cache_data = {
                    "db_name": self.db_credentials["name"],
                    "device_name": self.device_name,
                    "tracking_start_time": time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(tracking_start_time)),
                    "creation_timestamp": tracking_start_time,
                    "db_status": "tracking"
                }
            
            if finalise:
                # Mark cache file as finalized
                cache_data["db_status"] = "finalised"
                cache_data["finalized_timestamp"] = time.time()
            else:
                # Update with current database info
                cache_data.update({
                    "last_updated": time.time(),
                    "db_size_bytes": db_info["db_size_bytes"],
                    "table_counts": db_info["table_counts"],
                    "last_db_update": db_info["last_db_update"]
                })
            
            # Write cache file
            with open(cache_file_path, 'w') as f:
                json.dump(cache_data, f, indent=2)
                
        except Exception as e:
            action = "finalize" if finalise else "update"
            logging.warning(f"Failed to {action} cache file {cache_file_path}: {e}")
    
    def _read_cache(self, cache_file_path):
        """Read cache file, or find latest if path is None."""
        if cache_file_path and os.path.exists(cache_file_path):
            # Read specific cache file
            try:
                with open(cache_file_path, 'r') as f:
                    cache_data = json.load(f)
                
                return {
                    "db_size_bytes": cache_data.get("db_size_bytes", 0),
                    "table_counts": cache_data.get("table_counts", {}),
                    "last_db_update": cache_data.get("last_db_update", 0),
                    "cache_file": cache_file_path,
                    "db_status": cache_data.get("db_status", "unknown")
                }
            except Exception as e:
                logging.warning(f"Failed to read cache file {cache_file_path}: {e}")
        
        # Find and read latest cache file for this device
        try:
            cache_files = []
            for filename in os.listdir(self.cache_dir):
                if filename.endswith(f"_{self.device_name}_db.json") and filename.startswith("db_metadata_"):
                    cache_files.append(os.path.join(self.cache_dir, filename))
            
            if cache_files:
                # Sort by modification time and get the most recent
                cache_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                latest_cache = cache_files[0]
                
                with open(latest_cache, 'r') as f:
                    cache_data = json.load(f)
                
                return {
                    "db_size_bytes": cache_data.get("db_size_bytes", 0),
                    "table_counts": cache_data.get("table_counts", {}),
                    "last_db_update": cache_data.get("last_db_update", 0),
                    "cache_file": latest_cache,
                    "db_status": cache_data.get("db_status", "unknown")
                }
                
        except Exception as e:
            logging.warning(f"Failed to find latest cache file for {self.device_name}: {e}")
        
        # Return empty data if no cache available
        return {"db_size_bytes": 0, "table_counts": {}, "last_db_update": 0}