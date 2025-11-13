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

import json
import logging
import multiprocessing
import os
import time
import traceback
from collections import deque

# Import helper classes
from .helpers import DAMFileHelper, ImgSnapshotHelper, SensorDataHelper

# Character encoding for MariaDB/MySQL connections
SQL_CHARSET = "latin1"

# Constants
ASYNC_WRITER_TIMEOUT = 30  # Timeout in seconds for async writer initialization
SENSOR_DEFAULT_PERIOD = 120.0  # Default sensor sampling period in seconds
IMG_SNAPSHOT_DEFAULT_PERIOD = (
    300.0  # Default image snapshot period in seconds (5 minutes)
)

# Database resilience constants
MAX_DB_RETRIES = 3  # Maximum number of retry attempts for database operations
RETRY_BASE_DELAY = 1.0  # Base delay in seconds for exponential backoff
MAX_RETRY_DELAY = 30.0  # Maximum delay between retries
MAX_BUFFERED_COMMANDS = 10000  # Maximum commands to buffer in memory during failures
DAM_DEFAULT_PERIOD = 60.0  # Default DAM activity sampling period in seconds
METADATA_MAX_VALUE_LENGTH = (
    60000  # Maximum length for metadata values before truncation
)
QUEUE_CHECK_INTERVAL = 0.1  # Interval for checking queue status in seconds


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
        super().__init__()

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
            logging.info(
                f"{self._get_db_type_name()} database connection established successfully"
            )

            # Signal that the writer is ready to accept commands
            logging.info(
                f"{self._get_db_type_name()} async writer ready to accept commands"
            )
            self._ready_event.set()

            # Main command processing loop
            while do_run:
                try:
                    msg = self._queue.get()
                    if msg == "DONE":
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
                        logging.error(
                            f"Failed to run {self._get_db_type_name().lower()} command:\n%s"
                            % command
                        )
                        logging.error(f"Error details: {str(e)}")
                        logging.error(
                            f"Arguments: {str(args)}" if "args" in locals() else "None"
                        )
                        logging.error(f"Traceback: {traceback.format_exc()}")

                        # Allow subclasses to handle specific error types
                        self._handle_command_error(
                            e, command, args if "args" in locals() else None
                        )

                    except Exception as log_error:
                        logging.error(f"Failed to log error details: {str(log_error)}")
                        logging.error(
                            "Did not retrieve queue value or failed to log command"
                        )
                        do_run = False
                finally:
                    if self._queue.empty():
                        # Sleep if queue is empty to avoid excessive CPU usage
                        time.sleep(QUEUE_CHECK_INTERVAL)

        except KeyboardInterrupt as e:
            logging.warning(
                f"{self._get_db_type_name()} async process interrupted with KeyboardInterrupt"
            )
            # Ensure ready event is set even if interrupted
            self._ready_event.set()
            raise e
        except Exception as e:
            logging.error(
                f"{self._get_db_type_name()} async process stopped with an exception: %s",
                str(e),
            )
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


class BaseResultWriter:
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

    def __init__(
        self,
        db_credentials,
        rois,
        metadata=None,
        make_dam_like_table=True,
        take_frame_shots=False,
        erase_old_db=True,
        sensor=None,
        **kwargs,
    ):
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
        self._async_writer = self._create_async_writer(
            db_credentials, erase_old_db, **kwargs
        )
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
            self._sensor_saver = SensorDataHelper(
                sensor, database_type=self._database_type
            )
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
                raise Exception(
                    f"Async database writer failed to initialize within {ASYNC_WRITER_TIMEOUT} seconds - check database connection"
                )
            else:
                raise Exception(
                    "Async database writer process died during initialization - check database configuration and logs"
                )

        logging.warning("Creating database tables...")

        # This will check if tables need to be created or not based on erase_old_db
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

    def get_backup_filename(self):
        """
        Get the backup filename for this result writer.

        Base implementation returns the backup filename from metadata if available.
        Subclasses can override this method to provide writer-specific logic.

        Returns:
            str or None: Backup filename if available, None otherwise
        """
        if hasattr(self, "_metadata") and self._metadata:
            return self._metadata.get("backup_filename")
        return None

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
            # Check if v is a string (command) or a list (data)
            if isinstance(v, str):
                # Original behavior for string commands
                self._write_async_command(v)
                self._insert_dict[k] = ""
            elif isinstance(v, list):
                # For list-based data (e.g., SQLiteResultWriter), do nothing here
                # The subclass should handle flushing lists appropriately
                pass
        try:
            command = "INSERT INTO METADATA VALUES (%s, %s)"
            self._write_async_command(
                command, ("stop_date_time", str(int(time.time())))
            )
            while not self._queue.empty():
                logging.info("waiting for queue to be processed")
                time.sleep(QUEUE_CHECK_INTERVAL)
        except Exception:
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
        state["_pickle_init_args"] = {
            "db_credentials": self._db_credentials,
            "rois": self._rois,
            "metadata": self._metadata,
            "make_dam_like_table": self._make_dam_like_table,
            "take_frame_shots": self._take_frame_shots,
        }

        # Remove non-serializable multiprocessing objects
        state.pop("_queue", None)
        state.pop("_async_writer", None)

        return state

    def __setstate__(self, state):
        """
        Restore object from pickled state by recreating multiprocessing objects.

        This recreates the queue and async writer that were excluded during pickling.
        """
        self.__dict__.update(state)

        # Recreate multiprocessing objects using stored parameters
        init_args = state.get("_pickle_init_args", {})

        # Recreate queue and async writer
        self._queue = multiprocessing.JoinableQueue()
        self._async_writer = self._create_async_writer(
            init_args.get("db_credentials", self._db_credentials),
            False,  # Don't erase database when restoring from pickle
            **getattr(self, "_pickle_extra_kwargs", {}),
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
        if not hasattr(self, "_initialized_rois"):
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
                # Check if v is a string (command) or a list (data)
                if isinstance(v, str):
                    # Original behavior for string commands
                    self._write_async_command(v)
                    self._insert_dict[k] = ""
                elif isinstance(v, list):
                    # For list-based data (e.g., SQLiteResultWriter), do nothing here
                    # The subclass should handle flushing lists appropriately
                    pass
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
                command = f"INSERT INTO ROI_{roi_id} VALUES {str(tp)}"
                self._insert_dict[roi_id] = command
            else:
                self._insert_dict[roi_id] += "," + str(tp)

        # now this is irrelevant when tracking multiple animals
        if self._dam_file_helper is not None:
            for dr in data_rows:
                self._dam_file_helper.input_roi_data(t, roi, dr)

    def _initialise_var_map(self, data_row):
        """Initialize variable mapping table with data types."""
        self._write_async_command("DELETE FROM VAR_MAP")
        for dt in list(data_row.values()):
            command = "INSERT INTO VAR_MAP VALUES (%s, %s, %s)"
            self._write_async_command(
                command, (dt.header_name, dt.sql_data_type, dt.functional_type)
            )

    def _initialise_roi_table(self, roi, data_row):
        """Initialize ROI-specific database table (MySQL version)."""
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY", "t INT"]
        for dt in list(data_row.values()):
            fields.append(f"{dt.header_name} {dt.sql_data_type}")
        fields = ", ".join(fields)
        table_name = f"ROI_{roi.idx}"
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
                        self.log_io_diagnostics(
                            f"Writer died during attempt {attempt + 1}/{MAX_DB_RETRIES}"
                        )
                        logging.warning(
                            f"Async writer died, attempting restart (attempt {attempt + 1}/{MAX_DB_RETRIES})"
                        )
                        if self._restart_async_writer():
                            # Writer restarted successfully, retry buffered commands first
                            self._retry_buffered_commands()
                        continue
                    else:
                        # Final attempt failed, buffer the command
                        self.log_io_diagnostics(
                            "Writer permanently failed, entering degraded mode"
                        )
                        logging.error(
                            "Async writer permanently failed, buffering command"
                        )
                        return self._buffer_command(command, args)

                # Send command to queue
                self._queue.put((command, args))
                return True

            except Exception as e:
                if attempt < MAX_DB_RETRIES:
                    delay = min(RETRY_BASE_DELAY * (2**attempt), MAX_RETRY_DELAY)
                    logging.warning(
                        f"Database write failed (attempt {attempt + 1}/{MAX_DB_RETRIES}): {e}. Retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)
                else:
                    logging.error(
                        f"All database write attempts failed: {e}. Buffering command."
                    )
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
            if hasattr(self, "_async_writer") and self._async_writer is not None:
                try:
                    if self._async_writer.is_alive():
                        self._async_writer.terminate()
                        self._async_writer.join(timeout=5)
                except Exception as e:
                    logging.warning(f"Error cleaning up old async writer: {e}")

            # Clean up old queue
            if hasattr(self, "_queue") and self._queue is not None:
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
            logging.info(
                f"Successfully restarted async writer (restart #{self._writer_restart_count})"
            )
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
                logging.warning(
                    f"Command buffer full ({MAX_BUFFERED_COMMANDS} commands), oldest commands will be dropped"
                )
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
                    logging.error(
                        "Async writer died again while retrying buffered commands"
                    )
                    break

            except Exception as e:
                failed_retries += 1
                logging.warning(f"Failed to retry buffered command: {e}")
                if failed_retries > 10:  # Stop if too many consecutive failures
                    logging.error(
                        "Too many failures retrying buffered commands, stopping retry"
                    )
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
            "writer_alive": (
                self._async_writer.is_alive()
                if hasattr(self, "_async_writer")
                else False
            ),
            "buffered_commands": len(self._failed_commands_buffer),
            "restart_count": self._writer_restart_count,
            "last_restart_time": self._last_restart_time,
            "time_since_last_restart": (
                time.time() - self._last_restart_time
                if self._last_restart_time > 0
                else None
            ),
        }

    def log_io_diagnostics(self, error_context=""):
        """
        Log comprehensive I/O diagnostics to help identify SD card issues.

        Args:
            error_context (str): Additional context about when the error occurred
        """
        try:
            status = self.get_resilience_status()
            db_path = getattr(self, "_db_credentials", {}).get("name", "unknown")

            logging.error(f"Database I/O Issue - {error_context}")
            logging.error(f"  Database path: {db_path}")
            logging.error(f"  Writer alive: {status['writer_alive']}")
            logging.error(f"  Buffered commands: {status['buffered_commands']}")
            logging.error(f"  Writer restarts: {status['restart_count']}")
            logging.error(
                f"  Time since last restart: {status['time_since_last_restart']:.1f}s"
                if status["time_since_last_restart"]
                else "Never restarted"
            )

            # Check disk space and I/O stats if possible
            if (
                hasattr(os, "statvfs")
                and db_path != "unknown"
                and os.path.exists(os.path.dirname(db_path))
            ):
                try:
                    statvfs = os.statvfs(os.path.dirname(db_path))
                    # Handle different statvfs implementations
                    if hasattr(statvfs, "f_available"):
                        free_space = statvfs.f_frsize * statvfs.f_available
                        total_space = statvfs.f_frsize * statvfs.f_blocks
                    else:
                        free_space = statvfs.f_frsize * statvfs.f_bavail
                        total_space = statvfs.f_frsize * statvfs.f_blocks
                    free_percent = (free_space / total_space) * 100
                    logging.error(
                        f"  Disk space: {free_space / (1024**3):.2f}GB free ({free_percent:.1f}% of {total_space / (1024**3):.2f}GB)"
                    )
                except Exception as e:
                    logging.error(f"  Could not check disk space: {e}")

            # Log recent queue status
            if hasattr(self, "_queue"):
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
            command = f"CREATE TABLE IF NOT EXISTS {name} ({fields}) ENGINE={engine}"
        else:
            command = f"CREATE TABLE IF NOT EXISTS {name} ({fields})"
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)

    def _insert_metadata(self):
        """Insert experimental metadata into METADATA table."""
        for k, v in list(self.metadata.items()):
            # Properly serialize complex metadata values to avoid SQL injection and formatting issues
            v_serialized = (
                json.dumps(str(v))
                if not isinstance(v, (str, int, float, bool, type(None)))
                else v
            )

            # Truncate extremely large values as a safety measure
            max_value_length = METADATA_MAX_VALUE_LENGTH
            if isinstance(v_serialized, str) and len(v_serialized) > max_value_length:
                v_serialized = v_serialized[:max_value_length] + "... [TRUNCATED]"
                logging.warning(
                    f"Metadata value for key '{k}' was truncated due to size limit"
                )

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


class dbAppender:
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
            {
                "name": "database_to_append",
                "description": "Database to append to",
                "type": "str",
                "default": "",
                "asknode": "database_list",
            },
            {
                "name": "take_frame_shots",
                "description": "Save periodic frame snapshots",
                "type": "boolean",
                "default": True,
            },
            {
                "name": "make_dam_like_table",
                "description": "Create DAM-compatible activity summary table",
                "type": "boolean",
                "default": False,
            },
        ],
    }

    def __init__(
        self,
        db_credentials,
        rois,
        metadata=None,
        database_to_append="",
        make_dam_like_table=False,
        take_frame_shots=False,
        sensor=None,
        db_host="localhost",
        *args,
        **kwargs,
    ):
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
            raise ValueError(
                f"Could not detect database type for: {self.database_to_append}"
            )

    def _detect_database_type(self, database_name):
        """
        Detect whether the selected database is SQLite or MySQL.

        Args:
            database_name (str): Name/path of the database

        Returns:
            str: "SQLite" or "MySQL" or None if cannot detect
        """
        # Method 1: Check if it's a file path with SQLite extension
        if (
            database_name.endswith(".db")
            or database_name.endswith(".sqlite")
            or database_name.endswith(".sqlite3")
        ):
            return "SQLite"

        # Method 2: Check if file exists in common SQLite locations
        sqlite_paths = [
            f"/ethoscope_data/results/{database_name}",
            f"/ethoscope_data/results/{database_name}.db",
            database_name,  # If full path is provided
        ]

        for path in sqlite_paths:
            if os.path.exists(path):
                return "SQLite"

        # Method 3: Check cache for database information
        try:
            from .cache import get_all_databases_info

            device_name = self.db_credentials.get("name", "ETHOSCOPE_DEFAULT")
            if isinstance(device_name, str) and not device_name.startswith(
                "ETHOSCOPE_"
            ):
                # If device_name is a path (SQLite), extract device ID for cache lookup
                import re

                device_match = re.search(r"([a-f0-9]{32})", device_name)
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
        if (
            "/" not in database_name
            and "\\" not in database_name
            and "." not in database_name
        ):
            return "MySQL"

        return None

    def _create_sqlite_writer(self):
        """Create SQLite writer with append functionality."""
        # Lazy import to avoid circular dependency
        from .sqlite import SQLiteResultWriter

        # Update db_credentials to point to the existing database
        sqlite_db_credentials = self.db_credentials.copy()

        # Find the actual path to the SQLite database
        sqlite_path = self._find_sqlite_database_path(self.database_to_append)
        if not sqlite_path:
            raise FileNotFoundError(
                f"SQLite database not found: {self.database_to_append}"
            )

        sqlite_db_credentials["name"] = sqlite_path

        # Create SQlite writer with erase_old_db=False for append functionality
        self.kwargs.update({"erase_old_db": False})
        self._writer = SQLiteResultWriter(
            sqlite_db_credentials,
            self.rois,
            *self.args,
            metadata=self.metadata,
            make_dam_like_table=self.make_dam_like_table,
            take_frame_shots=self.take_frame_shots,
            sensor=self.sensor,
            **self.kwargs,
        )

    def _create_mysql_writer(self):
        """Create MySQL writer with append functionality."""
        # Lazy import to avoid circular dependency
        from .mysql import MySQLResultWriter

        # Update db_credentials to point to the existing database
        mysql_db_credentials = self.db_credentials.copy()
        mysql_db_credentials["name"] = self.database_to_append

        # Create MySQL writer with erase_old_db=False for append functionality
        self.kwargs.update({"erase_old_db": False})
        self._writer = MySQLResultWriter(
            mysql_db_credentials,
            self.rois,
            *self.args,
            metadata=self.metadata,
            make_dam_like_table=self.make_dam_like_table,
            take_frame_shots=self.take_frame_shots,
            sensor=self.sensor,
            db_host=self.db_host,
            **self.kwargs,
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
        if not db_basename.endswith(".db"):
            db_basename += ".db"

        # Walk the filesystem starting from common ethoscope data locations
        search_roots = ["/ethoscope_data/results", "/data"]

        for search_root in search_roots:
            if not os.path.exists(search_root):
                continue

            try:
                for root, _dirs, files in os.walk(search_root):
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
                if isinstance(device_name, str) and not device_name.startswith(
                    "ETHOSCOPE_"
                ):
                    # Extract device ID from path for cache lookup
                    import re

                    device_match = re.search(r"([a-f0-9]{32})", device_name)
                    if device_match:
                        device_name = f"ETHOSCOPE_{device_match.group(1)[:8].upper()}"

            databases_info = get_all_databases_info(device_name)

            # Add SQLite databases
            sqlite_dbs = databases_info.get("SQLite", {})
            for db_name, db_info in sqlite_dbs.items():
                if (
                    db_info.get("file_exists", False)
                    and db_info.get("filesize", 0) > 32768
                ):  # > 32KB
                    databases_list.append(
                        {
                            "name": db_name,
                            "type": "SQLite",
                            "active": True,
                            "size": db_info.get("filesize", 0),
                            "status": db_info.get("db_status", "unknown"),
                            "path": db_info.get("path", ""),
                        }
                    )

            # Add MySQL databases
            mysql_dbs = databases_info.get("MariaDB", {})
            for db_name, db_info in mysql_dbs.items():
                databases_list.append(
                    {
                        "name": db_name,
                        "type": "MySQL",
                        "active": True,
                        "size": db_info.get("db_size_bytes", 0),
                        "status": db_info.get("db_status", "unknown"),
                    }
                )

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
