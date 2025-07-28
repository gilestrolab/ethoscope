import time
import logging
import traceback
import mysql.connector
from .base import BaseAsyncSQLWriter, BaseResultWriter

# Character encoding for MariaDB/MySQL connections
SQL_CHARSET = 'latin1'

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
        "overview": "MySQL/MariaDB result writer - stores tracking data to a mySQL/mariadb database server. Legacy.",
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

            # Insert experimental metadata using MySQL-specific method
            self._insert_metadata()
            
            self._wait_for_queue_empty()
        
        elif not self._erase_old_db and getattr(self, 'database_to_append', None):
            event = "appending"
            command = "INSERT INTO START_EVENTS VALUES (%s, %s, %s)"
            self._write_async_command(command, (self._null, int(time.time()), event))
            self._wait_for_queue_empty()

    def _insert_metadata(self):
        """Insert experimental metadata into METADATA table with MySQL duplicate prevention."""
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
            
            # Use MySQL INSERT IGNORE to prevent duplicate key errors
            command = "INSERT IGNORE INTO METADATA VALUES (%s, %s)"
            self._write_async_command(command, (k, v_serialized))