"""
Unit tests for io/base.py.

Tests BaseResultWriter, BaseAsyncSQLWriter, dbAppender,
and resilience features (retry, buffer, restart).
"""

import os
import sqlite3
import tempfile
import time
import unittest
from collections import deque
from multiprocessing import Queue
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import numpy as np

from ethoscope.core.roi import ROI
from ethoscope.io.base import (
    ASYNC_WRITER_TIMEOUT,
    MAX_BUFFERED_COMMANDS,
    MAX_DB_RETRIES,
    METADATA_MAX_VALUE_LENGTH,
    BaseAsyncSQLWriter,
    BaseResultWriter,
    dbAppender,
)
from ethoscope.io.helpers import (
    DAMFileHelper,
    ImgSnapshotHelper,
    NpyAppendableFile,
    Null,
    SensorDataHelper,
)

# ===========================================================================
# Helper classes / Null
# ===========================================================================


class TestNull(unittest.TestCase):
    """Test Null helper class."""

    def test_repr(self):
        self.assertEqual(repr(Null()), "NULL")

    def test_str(self):
        self.assertEqual(str(Null()), "NULL")


# ===========================================================================
# NpyAppendableFile
# ===========================================================================


class TestNpyAppendableFile(unittest.TestCase):
    """Test NpyAppendableFile for incremental numpy writes."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_path = os.path.join(self.temp_dir, "test_data.npy")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_extension_changed_to_anpy(self):
        """Test file extension is changed to .anpy."""
        naf = NpyAppendableFile(self.base_path)
        self.assertTrue(naf.fname.endswith(".anpy"))

    def test_write_and_load(self):
        """Test write data then load it back."""
        naf = NpyAppendableFile(self.base_path, newfile=True)
        data = np.array([[1, 2, 3], [4, 5, 6]])
        naf.write(data)
        loaded = naf.load(axis=0)
        np.testing.assert_array_equal(loaded, data)

    def test_append_multiple_writes(self):
        """Test multiple writes append correctly."""
        naf = NpyAppendableFile(self.base_path, newfile=True)
        data1 = np.array([[1, 2], [3, 4]])
        data2 = np.array([[5, 6], [7, 8]])
        naf.write(data1)
        naf.write(data2)
        loaded = naf.load(axis=0)
        expected = np.concatenate([data1, data2], axis=0)
        np.testing.assert_array_equal(loaded, expected)

    def test_convert_to_npy(self):
        """Test conversion to standard .npy format."""
        naf = NpyAppendableFile(self.base_path, newfile=True)
        data = np.array([[1, 2, 3]])
        naf.write(data)
        npy_path = os.path.join(self.temp_dir, "output.npy")
        naf.convert(npy_path)
        self.assertTrue(os.path.exists(npy_path))
        loaded = np.load(npy_path)
        np.testing.assert_array_equal(loaded, data)

    def test_header(self):
        """Test header returns version and dict."""
        naf = NpyAppendableFile(self.base_path, newfile=True)
        data = np.array([1.0, 2.0, 3.0])
        naf.write(data)
        version, header_dict = naf.header
        self.assertIn("descr", header_dict)
        self.assertIn("shape", header_dict)


# ===========================================================================
# SensorDataHelper
# ===========================================================================


class TestSensorDataHelper(unittest.TestCase):
    """Test SensorDataHelper."""

    def _make_sensor(self):
        sensor = Mock()
        sensor.read_all.return_value = (22.5, 55.0)
        sensor.sensor_types = {"temperature": "FLOAT", "humidity": "FLOAT"}
        return sensor

    def test_init_mysql(self):
        """Test MySQL database type initialization."""
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor, database_type="MySQL")
        self.assertEqual(helper._table_name, "SENSORS")
        self.assertIn("id", helper._table_headers)

    def test_init_sqlite(self):
        """Test SQLite database type initialization."""
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor, database_type="SQLite3")
        self.assertIn("INTEGER PRIMARY KEY AUTOINCREMENT", helper._table_headers["id"])

    def test_flush_not_time_yet(self):
        """Test flush returns None when period hasn't elapsed."""
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor, period=120.0)
        result = helper.flush(0)
        self.assertIsNone(result)

    def test_flush_returns_command(self):
        """Test flush returns SQL command when period elapsed."""
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor, period=120.0, database_type="MySQL")
        # First flush at t=0
        helper.flush(0)
        # Second flush at t > period
        result = helper.flush(200000)  # 200s > 120s
        self.assertIsNotNone(result)
        cmd, args = result
        self.assertIn("INSERT into SENSORS", cmd)

    def test_flush_sqlite_format(self):
        """Test SQLite flush format doesn't include id."""
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor, period=120.0, database_type="SQLite3")
        helper.flush(0)
        result = helper.flush(200000)
        self.assertIsNotNone(result)
        cmd, args = result
        self.assertIn("INSERT into SENSORS", cmd)
        # SQLite version should specify columns (skipping id)
        self.assertIn("(", cmd)

    def test_create_command(self):
        """Test create_command generates proper SQL."""
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor, database_type="MySQL")
        cmd = helper.create_command
        self.assertIn("id", cmd)
        self.assertIn("t", cmd)

    def test_table_name(self):
        sensor = self._make_sensor()
        helper = SensorDataHelper(sensor)
        self.assertEqual(helper.table_name, "SENSORS")

    def test_sensor_type_conversion_sqlite(self):
        """Test MySQL types are converted to SQLite equivalents."""
        sensor = Mock()
        sensor.sensor_types = {
            "temp": "FLOAT",
            "count": "INT",
            "name": "VARCHAR(100)",
        }
        helper = SensorDataHelper(sensor, database_type="SQLite3")
        headers = helper._table_headers
        self.assertEqual(headers["temp"], "REAL")
        self.assertEqual(headers["count"], "INTEGER")
        self.assertEqual(headers["name"], "TEXT")


# ===========================================================================
# ImgSnapshotHelper
# ===========================================================================


class TestImgSnapshotHelper(unittest.TestCase):
    """Test ImgSnapshotHelper."""

    def test_init_mysql(self):
        helper = ImgSnapshotHelper(database_type="MySQL")
        self.assertEqual(helper._table_headers["img"], "LONGBLOB")

    def test_init_sqlite(self):
        helper = ImgSnapshotHelper(database_type="SQLite3")
        self.assertEqual(helper._table_headers["img"], "BLOB")

    def test_table_name(self):
        helper = ImgSnapshotHelper()
        self.assertEqual(helper.table_name, "IMG_SNAPSHOTS")

    def test_create_command(self):
        helper = ImgSnapshotHelper(database_type="MySQL")
        cmd = helper.create_command
        self.assertIn("img", cmd)
        self.assertIn("LONGBLOB", cmd)

    def test_flush_not_time_yet(self):
        """Test flush returns None when period hasn't elapsed."""
        helper = ImgSnapshotHelper(period=300.0)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        result = helper.flush(0, img)
        self.assertIsNone(result)

    def test_flush_returns_command_sqlite(self):
        """Test flush returns SQL command for SQLite."""
        helper = ImgSnapshotHelper(period=300.0, database_type="SQLite3")
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        helper.flush(0, img)
        result = helper.flush(500000, img)  # 500s > 300s
        self.assertIsNotNone(result)
        cmd, args = result
        self.assertIn("INSERT INTO IMG_SNAPSHOTS", cmd)
        self.assertIn("?", cmd)  # SQLite placeholder


# ===========================================================================
# DAMFileHelper
# ===========================================================================


class TestDAMFileHelper(unittest.TestCase):
    """Test DAMFileHelper."""

    def test_init(self):
        helper = DAMFileHelper(n_rois=10)
        self.assertEqual(helper._n_rois, 10)
        self.assertEqual(len(helper._distance_map), 10)

    def test_make_dam_file_sql_fields(self):
        """Test SQL field generation."""
        helper = DAMFileHelper(n_rois=3)
        fields = helper.make_dam_file_sql_fields()
        self.assertIn("ROI_1", fields)
        self.assertIn("ROI_2", fields)
        self.assertIn("ROI_3", fields)
        self.assertIn("date", fields)
        self.assertIn("time", fields)

    def test_input_roi_data_and_flush(self):
        """Test data input and flush cycle."""
        helper = DAMFileHelper(period=60.0, n_rois=2)
        roi = Mock()
        roi.idx = 1
        roi.longest_axis = 100.0
        data = {"x": 50, "y": 25}

        # Input data for first tick
        helper.input_roi_data(0, roi, data)
        # Input data for second tick
        helper.input_roi_data(61000, roi, data)  # >60s later

        result = helper.flush(120000)  # Flush at 120s
        self.assertIsInstance(result, list)

    def test_flush_empty(self):
        """Test flush with no accumulated data."""
        helper = DAMFileHelper(n_rois=2)
        result = helper.flush(0)
        self.assertEqual(result, [])


# ===========================================================================
# BaseAsyncSQLWriter
# ===========================================================================


class ConcreteAsyncWriter(BaseAsyncSQLWriter):
    """Concrete implementation for testing."""

    def __init__(self, queue, erase_old_db=True):
        super().__init__(queue, erase_old_db)
        self._initialized = False

    def _initialize_database(self):
        self._initialized = True

    def _get_connection(self):
        return Mock()

    def _get_db_type_name(self):
        return "Test"

    def _should_retry_on_error(self, error):
        return False

    def _handle_command_error(self, error, command, args):
        pass


class TestBaseAsyncSQLWriter(unittest.TestCase):
    """Test BaseAsyncSQLWriter base class."""

    def test_init(self):
        """Test initialization stores queue and flags."""
        queue = Mock(spec=Queue)
        writer = ConcreteAsyncWriter(queue, erase_old_db=True)
        self.assertEqual(writer._queue, queue)
        self.assertTrue(writer._erase_old_db)

    def test_abstract_methods_raise(self):
        """Test abstract methods raise NotImplementedError."""
        queue = Mock(spec=Queue)
        writer = BaseAsyncSQLWriter(queue)
        with self.assertRaises(NotImplementedError):
            writer._initialize_database()
        with self.assertRaises(NotImplementedError):
            writer._get_connection()
        with self.assertRaises(NotImplementedError):
            writer._get_db_type_name()
        with self.assertRaises(NotImplementedError):
            writer._should_retry_on_error(Exception())


# ===========================================================================
# BaseResultWriter - resilience features
# ===========================================================================


class TestBaseResultWriterResilience(unittest.TestCase):
    """Test BaseResultWriter resilience features without full init."""

    def _make_writer_shell(self):
        """Create a BaseResultWriter-like object with resilience attributes set manually."""
        writer = object.__new__(BaseResultWriter)
        writer._failed_commands_buffer = deque(maxlen=MAX_BUFFERED_COMMANDS)
        writer._writer_restart_count = 0
        writer._last_restart_time = 0
        writer._async_writer = Mock()
        writer._async_writer.is_alive.return_value = True
        writer._queue = Mock()
        writer._db_credentials = {"name": "/tmp/test.db"}
        return writer

    def test_buffer_command(self):
        """Test _buffer_command adds to buffer."""
        writer = self._make_writer_shell()
        result = writer._buffer_command("INSERT INTO test VALUES (1)", None)
        self.assertFalse(result)
        self.assertEqual(len(writer._failed_commands_buffer), 1)

    def test_buffer_command_full_warning(self):
        """Test buffer full triggers warning."""
        writer = self._make_writer_shell()
        for i in range(MAX_BUFFERED_COMMANDS):
            writer._buffer_command(f"CMD {i}", None)
        self.assertEqual(len(writer._failed_commands_buffer), MAX_BUFFERED_COMMANDS)

    def test_retry_buffered_commands_empty(self):
        """Test retry does nothing with empty buffer."""
        writer = self._make_writer_shell()
        writer._retry_buffered_commands()  # Should not raise

    def test_retry_buffered_commands_sends_to_queue(self):
        """Test retry sends buffered commands to queue."""
        writer = self._make_writer_shell()
        writer._failed_commands_buffer.append(("CMD1", None, time.time()))
        writer._failed_commands_buffer.append(("CMD2", (1,), time.time()))

        writer._retry_buffered_commands()
        self.assertEqual(writer._queue.put.call_count, 2)
        self.assertEqual(len(writer._failed_commands_buffer), 0)

    def test_retry_buffered_commands_skips_old(self):
        """Test retry skips commands older than 5 minutes."""
        writer = self._make_writer_shell()
        old_time = time.time() - 400  # 400s ago > 300s threshold
        writer._failed_commands_buffer.append(("OLD_CMD", None, old_time))
        writer._failed_commands_buffer.append(("NEW_CMD", None, time.time()))

        writer._retry_buffered_commands()
        # Only NEW_CMD should be sent
        self.assertEqual(writer._queue.put.call_count, 1)

    def test_retry_buffered_commands_stops_if_writer_dies(self):
        """Test retry stops if writer dies during retry."""
        writer = self._make_writer_shell()
        writer._async_writer.is_alive.return_value = False
        writer._failed_commands_buffer.append(("CMD1", None, time.time()))

        writer._retry_buffered_commands()
        # Command should be put back in buffer
        self.assertEqual(len(writer._failed_commands_buffer), 1)

    def test_get_resilience_status(self):
        """Test resilience status dict structure."""
        writer = self._make_writer_shell()
        status = writer.get_resilience_status()
        self.assertIn("writer_alive", status)
        self.assertIn("buffered_commands", status)
        self.assertIn("restart_count", status)
        self.assertIn("last_restart_time", status)
        self.assertTrue(status["writer_alive"])
        self.assertEqual(status["buffered_commands"], 0)

    def test_write_async_command_resilient_success(self):
        """Test successful command write."""
        writer = self._make_writer_shell()
        result = writer._write_async_command_resilient("CREATE TABLE t (id INT)")
        self.assertTrue(result)
        writer._queue.put.assert_called_once()

    def test_write_async_command_resilient_dead_writer(self):
        """Test command buffered when writer is dead and restart fails."""
        writer = self._make_writer_shell()
        writer._async_writer.is_alive.return_value = False
        writer._create_async_writer = Mock(return_value=Mock())

        with patch.object(writer, "_restart_async_writer", return_value=False):
            result = writer._write_async_command_resilient("INSERT INTO t VALUES (1)")

        self.assertFalse(result)
        self.assertEqual(len(writer._failed_commands_buffer), 1)

    def test_log_io_diagnostics(self):
        """Test log_io_diagnostics doesn't crash."""
        writer = self._make_writer_shell()
        # Should not raise
        writer.log_io_diagnostics("test error")

    def test_restart_async_writer_throttle(self):
        """Test restart is throttled (min 30s between attempts)."""
        writer = self._make_writer_shell()
        writer._last_restart_time = time.time()  # Just restarted
        result = writer._restart_async_writer()
        self.assertFalse(result)


# ===========================================================================
# BaseResultWriter - metadata and table creation
# ===========================================================================


class TestBaseResultWriterMetadata(unittest.TestCase):
    """Test BaseResultWriter metadata handling."""

    def _make_writer_shell(self):
        writer = object.__new__(BaseResultWriter)
        writer._queue = Mock()
        writer._async_writer = Mock()
        writer._async_writer.is_alive.return_value = True
        writer._failed_commands_buffer = deque(maxlen=MAX_BUFFERED_COMMANDS)
        writer._writer_restart_count = 0
        writer._last_restart_time = 0
        writer._db_credentials = {"name": "/tmp/test.db"}
        return writer

    def test_insert_metadata_sqlite(self):
        """Test metadata insertion with SQLite placeholders."""
        writer = self._make_writer_shell()
        writer._metadata = {"machine_name": "test", "version": "1.0"}
        writer._database_type = "SQLite3"

        writer._insert_metadata()
        self.assertEqual(writer._queue.put.call_count, 2)

    def test_insert_metadata_mysql(self):
        """Test metadata insertion with MySQL placeholders."""
        writer = self._make_writer_shell()
        writer._metadata = {"key": "value"}
        writer._database_type = "MySQL"

        writer._insert_metadata()
        call_args = writer._queue.put.call_args[0][0]
        self.assertIn("%s", call_args[0])

    def test_insert_metadata_truncates_long_values(self):
        """Test metadata values exceeding max length are truncated."""
        writer = self._make_writer_shell()
        long_value = "x" * (METADATA_MAX_VALUE_LENGTH + 100)
        writer._metadata = {"big_key": long_value}
        writer._database_type = "MySQL"

        writer._insert_metadata()
        call_args = writer._queue.put.call_args[0][0]
        serialized_value = call_args[1][1]
        self.assertIn("[TRUNCATED]", serialized_value)

    def test_insert_metadata_serializes_complex_types(self):
        """Test complex metadata values are JSON serialized."""
        writer = self._make_writer_shell()
        writer._metadata = {"config": {"nested": True}}
        writer._database_type = "MySQL"

        writer._insert_metadata()
        # Should not crash on dict value

    def test_create_table(self):
        """Test _create_table sends CREATE TABLE command."""
        writer = self._make_writer_shell()
        writer._create_table("test_table", "id INT, name TEXT", engine="InnoDB")
        call_args = writer._queue.put.call_args[0][0]
        self.assertIn("CREATE TABLE IF NOT EXISTS test_table", call_args[0])

    def test_create_table_no_engine(self):
        """Test _create_table without engine."""
        writer = self._make_writer_shell()
        writer._create_table("test_table", "id INT", engine=None)
        call_args = writer._queue.put.call_args[0][0]
        cmd = call_args[0]
        self.assertNotIn("ENGINE", cmd)


# ===========================================================================
# BaseResultWriter - write/flush/add
# ===========================================================================


class TestBaseResultWriterWriteFlush(unittest.TestCase):
    """Test BaseResultWriter write and flush pipeline."""

    def _make_writer_shell(self):
        writer = object.__new__(BaseResultWriter)
        writer._queue = Mock()
        writer._async_writer = Mock()
        writer._async_writer.is_alive.return_value = True
        writer._failed_commands_buffer = deque(maxlen=MAX_BUFFERED_COMMANDS)
        writer._writer_restart_count = 0
        writer._last_restart_time = 0
        writer._db_credentials = {"name": "/tmp/test.db"}
        writer._null = Null()
        writer._insert_dict = {}
        writer._dam_file_helper = None
        writer._shot_saver = None
        writer._sensor_saver = None
        writer._var_map_initialised = False
        writer._max_insert_string_len = 1000
        writer._last_t = 0
        writer._rois = []
        return writer

    def test_write_initialises_var_map_on_first_call(self):
        """Test write initialises variable map on first call."""
        writer = self._make_writer_shell()
        roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)

        mock_var = Mock()
        mock_var.header_name = "x"
        mock_var.sql_data_type = "SMALLINT"
        mock_var.functional_type = "distance"
        mock_var.values.return_value = [mock_var]
        data_row = Mock()
        data_row.values.return_value = [mock_var]
        data_row.items.return_value = [("x", mock_var)]

        with (
            patch.object(writer, "_initialise_var_map") as mock_init_vm,
            patch.object(writer, "_initialise_roi_table"),
            patch.object(writer, "_add"),
        ):
            writer.write(1000, roi, [data_row])
            mock_init_vm.assert_called_once()

    def test_write_does_not_reinitialise_var_map(self):
        """Test write doesn't reinitialise var map on subsequent calls."""
        writer = self._make_writer_shell()
        writer._var_map_initialised = True
        writer._initialized_rois = {1}

        roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)
        data_row = Mock()
        data_row.values.return_value = []

        with (
            patch.object(writer, "_initialise_var_map") as mock_init_vm,
            patch.object(writer, "_add"),
        ):
            writer.write(2000, roi, [data_row])
            mock_init_vm.assert_not_called()

    def test_flush_returns_false(self):
        """Test flush always returns False."""
        writer = self._make_writer_shell()
        result = writer.flush(1000)
        self.assertFalse(result)

    def test_flush_triggers_dam_helper(self):
        """Test flush calls DAM helper."""
        writer = self._make_writer_shell()
        mock_dam = Mock()
        mock_dam.flush.return_value = ["INSERT cmd1", "INSERT cmd2"]
        writer._dam_file_helper = mock_dam

        writer.flush(1000)
        mock_dam.flush.assert_called_once_with(1000)

    def test_flush_triggers_sensor_helper(self):
        """Test flush calls sensor helper."""
        writer = self._make_writer_shell()
        mock_sensor = Mock()
        mock_sensor.flush.return_value = ("INSERT INTO SENSORS ...", None)
        writer._sensor_saver = mock_sensor

        writer.flush(1000)
        mock_sensor.flush.assert_called_once_with(1000)

    def test_add_creates_insert_command(self):
        """Test _add builds INSERT command string."""
        writer = self._make_writer_shell()
        roi = ROI(polygon=((0, 0), (100, 0), (100, 50), (0, 50)), idx=1)

        mock_var = Mock()
        mock_var.__int__ = Mock(return_value=42)
        data_row = Mock()
        data_row.values.return_value = [mock_var]

        writer._add(1000, roi, [data_row])
        self.assertIn(1, writer._insert_dict)
        self.assertIn("INSERT INTO ROI_1 VALUES", writer._insert_dict[1])


# ===========================================================================
# BaseResultWriter - context manager and pickle
# ===========================================================================


class TestBaseResultWriterContextManager(unittest.TestCase):
    """Test BaseResultWriter context manager and pickle support."""

    def test_enter_returns_self(self):
        """Test __enter__ returns the writer instance."""
        writer = object.__new__(BaseResultWriter)
        result = writer.__enter__()
        self.assertIs(result, writer)

    def test_getstate_excludes_queue_and_writer(self):
        """Test __getstate__ removes non-serializable objects."""
        writer = object.__new__(BaseResultWriter)
        writer._queue = Mock()
        writer._async_writer = Mock()
        writer._db_credentials = {"name": "test"}
        writer._rois = []
        writer._metadata = {}
        writer._make_dam_like_table = True
        writer._take_frame_shots = False

        state = writer.__getstate__()
        self.assertNotIn("_queue", state)
        self.assertNotIn("_async_writer", state)
        self.assertIn("_pickle_init_args", state)

    def test_metadata_property(self):
        """Test metadata property."""
        writer = object.__new__(BaseResultWriter)
        writer._metadata = {"key": "val"}
        self.assertEqual(writer.metadata, {"key": "val"})

    def test_get_backup_filename(self):
        """Test get_backup_filename from metadata."""
        writer = object.__new__(BaseResultWriter)
        writer._metadata = {"backup_filename": "backup_2025.db"}
        self.assertEqual(writer.get_backup_filename(), "backup_2025.db")

    def test_get_backup_filename_missing(self):
        """Test get_backup_filename returns None when not in metadata."""
        writer = object.__new__(BaseResultWriter)
        writer._metadata = {}
        self.assertIsNone(writer.get_backup_filename())


# ===========================================================================
# dbAppender
# ===========================================================================


class TestDbAppender(unittest.TestCase):
    """Test dbAppender database type detection."""

    def test_detect_sqlite_by_extension_db(self):
        """Test SQLite detection by .db extension."""
        appender = object.__new__(dbAppender)
        appender.db_credentials = {"name": "test"}
        result = appender._detect_database_type("experiment.db")
        self.assertEqual(result, "SQLite")

    def test_detect_sqlite_by_extension_sqlite(self):
        """Test SQLite detection by .sqlite extension."""
        appender = object.__new__(dbAppender)
        appender.db_credentials = {"name": "test"}
        result = appender._detect_database_type("data.sqlite")
        self.assertEqual(result, "SQLite")

    def test_detect_sqlite_by_extension_sqlite3(self):
        """Test SQLite detection by .sqlite3 extension."""
        appender = object.__new__(dbAppender)
        appender.db_credentials = {"name": "test"}
        result = appender._detect_database_type("data.sqlite3")
        self.assertEqual(result, "SQLite")

    def test_detect_mysql_by_name_pattern(self):
        """Test MySQL detection for simple database names."""
        appender = object.__new__(dbAppender)
        appender.db_credentials = {"name": "test"}
        result = appender._detect_database_type("ethoscope_001_db")
        self.assertEqual(result, "MySQL")

    def test_detect_sqlite_by_existing_file(self):
        """Test SQLite detection when file exists."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_path = f.name
        try:
            appender = object.__new__(dbAppender)
            appender.db_credentials = {"name": "test"}
            result = appender._detect_database_type(temp_path)
            self.assertEqual(result, "SQLite")
        finally:
            os.unlink(temp_path)

    def test_find_sqlite_database_path_direct(self):
        """Test finding database by direct path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_path = f.name
        try:
            appender = object.__new__(dbAppender)
            result = appender._find_sqlite_database_path(temp_path)
            self.assertEqual(result, temp_path)
        finally:
            os.unlink(temp_path)

    def test_find_sqlite_database_path_not_found(self):
        """Test returns None when database not found."""
        appender = object.__new__(dbAppender)
        result = appender._find_sqlite_database_path("/nonexistent/db.db")
        self.assertIsNone(result)

    def test_init_requires_database_to_append(self):
        """Test ValueError when database_to_append is empty."""
        with self.assertRaises(ValueError):
            dbAppender(
                db_credentials={"name": "test"},
                rois=[],
                database_to_append="",
            )

    def test_description(self):
        """Test _description structure."""
        desc = dbAppender._description
        self.assertIn("overview", desc)
        self.assertIn("arguments", desc)

    def test_context_manager_delegation(self):
        """Test context manager delegates to wrapped writer."""
        appender = object.__new__(dbAppender)
        mock_writer = MagicMock()  # MagicMock supports __enter__/__exit__
        appender._writer = mock_writer

        appender.__enter__()
        mock_writer.__enter__.assert_called_once()

        appender.__exit__(None, None, None)
        mock_writer.__exit__.assert_called_once()

    def test_getattr_delegation(self):
        """Test attribute access delegates to wrapped writer."""
        appender = object.__new__(dbAppender)
        mock_writer = Mock()
        mock_writer.some_method = Mock(return_value="delegated")
        appender._writer = mock_writer

        result = appender.some_method()
        self.assertEqual(result, "delegated")


if __name__ == "__main__":
    unittest.main()
