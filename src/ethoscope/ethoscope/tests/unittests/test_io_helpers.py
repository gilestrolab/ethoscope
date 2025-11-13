"""
Unit tests for I/O helper classes (io/helpers.py).

Tests helper classes for periodic data collection and storage:
- SensorDataHelper: Environmental sensor data collection
- ImgSnapshotHelper: Image snapshot storage
- DAMFileHelper: DAM-compatible activity monitoring
- NpyAppendableFile: Appendable numpy file format
- RawDataWriter: Raw tracking data writer
- Null: SQLite NULL representation
"""

import os
import tempfile
import unittest
from collections import OrderedDict
from unittest.mock import Mock

import numpy as np

from ethoscope.core.roi import ROI
from ethoscope.io.helpers import (
    DAMFileHelper,
    ImgSnapshotHelper,
    NpyAppendableFile,
    Null,
    RawDataWriter,
    SensorDataHelper,
)


class TestNull(unittest.TestCase):
    """Test suite for Null class."""

    def test_null_repr(self):
        """Test __repr__ returns 'NULL'."""
        null = Null()
        self.assertEqual(repr(null), "NULL")

    def test_null_str(self):
        """Test __str__ returns 'NULL'."""
        null = Null()
        self.assertEqual(str(null), "NULL")


class TestSensorDataHelper(unittest.TestCase):
    """Test suite for SensorDataHelper."""

    def setUp(self):
        """Create mock sensor for testing."""
        self.mock_sensor = Mock()
        self.mock_sensor.sensor_types = {
            "temperature": "FLOAT",
            "humidity": "FLOAT",
            "pressure": "INT",
        }
        self.mock_sensor.read_all.return_value = (25.5, 60.0, 1013)

    def test_init_with_mysql(self):
        """Test initialization with MySQL database type."""
        helper = SensorDataHelper(self.mock_sensor, period=120, database_type="MySQL")

        self.assertEqual(helper._period, 120)
        self.assertEqual(helper._database_type, "MySQL")
        self.assertEqual(helper.sensor, self.mock_sensor)
        self.assertIn("id", helper._base_headers)
        self.assertIn("AUTO_INCREMENT", helper._base_headers["id"])

    def test_init_with_sqlite(self):
        """Test initialization with SQLite database type."""
        helper = SensorDataHelper(self.mock_sensor, period=60, database_type="SQLite3")

        self.assertEqual(helper._period, 60)
        self.assertEqual(helper._database_type, "SQLite3")
        self.assertIn("id", helper._base_headers)
        self.assertIn("AUTOINCREMENT", helper._base_headers["id"])

    def test_table_name_property(self):
        """Test table_name property returns correct value."""
        helper = SensorDataHelper(self.mock_sensor)
        self.assertEqual(helper.table_name, "SENSORS")

    def test_get_sensor_types_converts_mysql_to_sqlite(self):
        """Test _get_sensor_types_for_database converts types for SQLite."""
        helper = SensorDataHelper(self.mock_sensor, database_type="SQLite3")

        sensor_types = helper._get_sensor_types_for_database()

        self.assertEqual(sensor_types["temperature"], "REAL")
        self.assertEqual(sensor_types["humidity"], "REAL")
        self.assertEqual(sensor_types["pressure"], "INTEGER")

    def test_get_sensor_types_preserves_mysql_types(self):
        """Test _get_sensor_types_for_database preserves MySQL types."""
        helper = SensorDataHelper(self.mock_sensor, database_type="MySQL")

        sensor_types = helper._get_sensor_types_for_database()

        self.assertEqual(sensor_types["temperature"], "FLOAT")
        self.assertEqual(sensor_types["humidity"], "FLOAT")
        self.assertEqual(sensor_types["pressure"], "INT")

    def test_get_sensor_types_handles_missing_sensor_types(self):
        """Test _get_sensor_types_for_database handles sensors without sensor_types."""
        sensor_no_types = Mock(spec=[])  # No sensor_types attribute
        helper = SensorDataHelper(sensor_no_types)

        sensor_types = helper._get_sensor_types_for_database()

        self.assertEqual(sensor_types, {})

    def test_get_sensor_types_converts_varchar_to_text(self):
        """Test _get_sensor_types_for_database converts VARCHAR to TEXT for SQLite."""
        mock_sensor = Mock()
        mock_sensor.sensor_types = {
            "device_id": "VARCHAR(50)",
            "status": "VARCHAR(100)",
        }
        helper = SensorDataHelper(mock_sensor, database_type="SQLite3")

        sensor_types = helper._get_sensor_types_for_database()

        self.assertEqual(sensor_types["device_id"], "TEXT")
        self.assertEqual(sensor_types["status"], "TEXT")

    def test_get_sensor_types_converts_char_to_text(self):
        """Test _get_sensor_types_for_database converts CHAR to TEXT for SQLite."""
        mock_sensor = Mock()
        mock_sensor.sensor_types = {"code": "CHAR(10)", "flag": "CHAR"}
        helper = SensorDataHelper(mock_sensor, database_type="SQLite3")

        sensor_types = helper._get_sensor_types_for_database()

        self.assertEqual(sensor_types["code"], "TEXT")
        self.assertEqual(sensor_types["flag"], "TEXT")

    def test_get_sensor_types_converts_text_to_text(self):
        """Test _get_sensor_types_for_database handles TEXT type for SQLite."""
        mock_sensor = Mock()
        mock_sensor.sensor_types = {"description": "TEXT", "notes": "LONGTEXT"}
        helper = SensorDataHelper(mock_sensor, database_type="SQLite3")

        sensor_types = helper._get_sensor_types_for_database()

        self.assertEqual(sensor_types["description"], "TEXT")
        self.assertEqual(sensor_types["notes"], "TEXT")

    def test_get_sensor_types_fallback_to_text(self):
        """Test _get_sensor_types_for_database falls back to TEXT for unknown types."""
        mock_sensor = Mock()
        mock_sensor.sensor_types = {"data": "BLOB", "other": "UNKNOWN_TYPE"}
        helper = SensorDataHelper(mock_sensor, database_type="SQLite3")

        sensor_types = helper._get_sensor_types_for_database()

        # Unknown types should default to TEXT
        self.assertEqual(sensor_types["data"], "TEXT")
        self.assertEqual(sensor_types["other"], "TEXT")

    def test_create_command_generates_sql(self):
        """Test create_command property generates valid SQL."""
        helper = SensorDataHelper(self.mock_sensor, database_type="MySQL")

        command = helper.create_command

        self.assertIn("id", command)
        self.assertIn("t", command)
        self.assertIn("temperature", command)
        self.assertIn("humidity", command)
        self.assertIn("pressure", command)

    def test_flush_returns_none_if_same_tick(self):
        """Test flush returns None if called within same period."""
        helper = SensorDataHelper(self.mock_sensor, period=60)

        # First call at t=120000ms (120s = tick 2)
        result1 = helper.flush(120000)
        # Second call at t=150000ms (150s = still tick 2 for 60s period)
        result2 = helper.flush(150000)

        self.assertIsNotNone(result1)
        self.assertIsNone(result2)

    def test_flush_mysql_generates_correct_command(self):
        """Test flush generates correct MySQL INSERT command."""
        helper = SensorDataHelper(self.mock_sensor, period=60, database_type="MySQL")

        # t=120000ms = 120s = 2 periods
        result = helper.flush(120000)

        self.assertIsNotNone(result)
        command, args = result
        self.assertIn("INSERT into SENSORS", command)
        self.assertIn("0", command)  # MySQL uses explicit ID=0
        self.assertIn("120000", command)
        self.assertIn("25.5", command)
        self.assertIn("60.0", command)
        self.assertIn("1013", command)

    def test_flush_sqlite_generates_correct_command(self):
        """Test flush generates correct SQLite INSERT command."""
        helper = SensorDataHelper(self.mock_sensor, period=60, database_type="SQLite3")

        result = helper.flush(120000)

        self.assertIsNotNone(result)
        command, args = result
        self.assertIn("INSERT into SENSORS", command)
        # SQLite skips ID column (AUTOINCREMENT handles it)
        self.assertNotIn(",id", command.lower())
        self.assertIn("120000", command)

    def test_flush_handles_sensor_error(self):
        """Test flush handles sensor read errors gracefully."""
        self.mock_sensor.read_all.side_effect = Exception("Sensor offline")
        helper = SensorDataHelper(self.mock_sensor, period=60)

        result = helper.flush(120000)

        self.assertIsNone(result)

    def test_flush_advances_tick_on_error(self):
        """Test flush advances tick even when sensor fails."""
        self.mock_sensor.read_all.side_effect = Exception("Sensor offline")
        helper = SensorDataHelper(self.mock_sensor, period=60)

        # First call fails
        result1 = helper.flush(120000)
        # Fix sensor
        self.mock_sensor.read_all.side_effect = None
        self.mock_sensor.read_all.return_value = (25.5, 60.0, 1013)
        # Second call at same tick should return None (already advanced)
        result2 = helper.flush(120500)

        self.assertIsNone(result1)
        self.assertIsNone(result2)


class TestImgSnapshotHelper(unittest.TestCase):
    """Test suite for ImgSnapshotHelper."""

    def tearDown(self):
        """Clean up temporary files."""
        # Find and remove any temporary ethoscope_*.jpg files
        import glob

        for f in glob.glob("/tmp/ethoscope_*.jpg"):
            try:
                os.remove(f)
            except Exception:
                pass

    def test_init_with_mysql(self):
        """Test initialization with MySQL database type."""
        helper = ImgSnapshotHelper(period=300, database_type="MySQL")

        self.assertEqual(helper._period, 300)
        self.assertEqual(helper._database_type, "MySQL")
        self.assertIn("LONGBLOB", helper._table_headers["img"])

    def test_init_with_sqlite(self):
        """Test initialization with SQLite database type."""
        helper = ImgSnapshotHelper(period=60, database_type="SQLite3")

        self.assertEqual(helper._period, 60)
        self.assertEqual(helper._database_type, "SQLite3")
        self.assertIn("BLOB", helper._table_headers["img"])

    def test_table_name_property(self):
        """Test table_name property returns correct value."""
        helper = ImgSnapshotHelper()
        self.assertEqual(helper.table_name, "IMG_SNAPSHOTS")

    def test_create_command_generates_sql(self):
        """Test create_command property generates valid SQL."""
        helper = ImgSnapshotHelper(database_type="MySQL")

        command = helper.create_command

        self.assertIn("id", command)
        self.assertIn("t", command)
        self.assertIn("img", command)

    def test_flush_returns_none_if_same_tick(self):
        """Test flush returns None if called within same period."""
        helper = ImgSnapshotHelper(period=60)
        img = np.zeros((100, 100), dtype=np.uint8)

        # First call at t=120000ms (120s = tick 2)
        result1 = helper.flush(120000, img)
        # Second call at t=150000ms (150s = still tick 2 for 60s period)
        result2 = helper.flush(150000, img)

        self.assertIsNotNone(result1)
        self.assertIsNone(result2)

    def test_flush_mysql_generates_correct_command(self):
        """Test flush generates correct MySQL INSERT command."""
        helper = ImgSnapshotHelper(period=60, database_type="MySQL")
        img = np.zeros((100, 100), dtype=np.uint8)

        result = helper.flush(120000, img)

        self.assertIsNotNone(result)
        command, args = result
        self.assertIn("INSERT INTO IMG_SNAPSHOTS", command)
        self.assertEqual(len(args), 3)  # MySQL: (id, t, img)
        self.assertEqual(args[0], 0)  # ID
        self.assertEqual(args[1], 120000)  # timestamp
        self.assertIsInstance(args[2], bytes)  # JPEG bytes

    def test_flush_sqlite_generates_correct_command(self):
        """Test flush generates correct SQLite INSERT command."""
        helper = ImgSnapshotHelper(period=60, database_type="SQLite3")
        img = np.zeros((100, 100), dtype=np.uint8)

        result = helper.flush(120000, img)

        self.assertIsNotNone(result)
        command, args = result
        self.assertIn("INSERT INTO IMG_SNAPSHOTS", command)
        self.assertEqual(len(args), 2)  # SQLite: (t, img) - no ID
        self.assertEqual(args[0], 120000)  # timestamp
        self.assertIsInstance(args[1], bytes)  # JPEG bytes


class TestDAMFileHelper(unittest.TestCase):
    """Test suite for DAMFileHelper."""

    def test_init_creates_distance_map(self):
        """Test initialization creates distance map for all ROIs."""
        helper = DAMFileHelper(period=60, n_rois=5)

        self.assertEqual(helper._period, 60)
        self.assertEqual(helper._n_rois, 5)
        self.assertEqual(len(helper._distance_map), 5)
        self.assertEqual(len(helper._last_positions), 5)
        for i in range(1, 6):
            self.assertEqual(helper._distance_map[i], 0)
            self.assertIsNone(helper._last_positions[i])

    def test_make_dam_file_sql_fields(self):
        """Test make_dam_file_sql_fields generates correct SQL."""
        helper = DAMFileHelper(n_rois=3)

        fields = helper.make_dam_file_sql_fields()

        self.assertIn("id INT", fields)
        self.assertIn("date CHAR", fields)
        self.assertIn("time CHAR", fields)
        self.assertIn("ROI_1 SMALLINT", fields)
        self.assertIn("ROI_2 SMALLINT", fields)
        self.assertIn("ROI_3 SMALLINT", fields)

    def test_compute_distance_returns_zero_on_first_call(self):
        """Test _compute_distance_for_roi returns 0 for first position."""
        helper = DAMFileHelper()
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)
        data = {"x": 50, "y": 50}

        distance = helper._compute_distance_for_roi(roi, data)

        self.assertEqual(distance, 0)
        self.assertIsNotNone(helper._last_positions[roi.idx])

    def test_compute_distance_calculates_normalized_movement(self):
        """Test _compute_distance_for_roi calculates correct normalized distance."""
        helper = DAMFileHelper()
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)

        # First position
        data1 = {"x": 0, "y": 0}
        helper._compute_distance_for_roi(roi, data1)

        # Second position - moved 100 pixels horizontally
        data2 = {"x": 100, "y": 0}
        distance = helper._compute_distance_for_roi(roi, data2)

        # Distance should be normalized by longest_axis
        self.assertGreater(distance, 0)
        self.assertLess(distance, 2)  # Should be around 1.0

    def test_input_roi_data_accumulates_activity(self):
        """Test input_roi_data accumulates activity data."""
        helper = DAMFileHelper(period=60)
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)

        # Input data at t=120000ms (tick=2)
        data = {"x": 50, "y": 50}
        helper.input_roi_data(120000, roi, data)

        # Verify activity was recorded
        self.assertIn(2, helper._activity_accum)
        self.assertIsInstance(helper._activity_accum[2], OrderedDict)

    def test_flush_returns_empty_list_when_no_data(self):
        """Test flush returns empty list when no activity accumulated."""
        helper = DAMFileHelper(period=60)

        result = helper.flush(120000)

        self.assertEqual(result, [])

    def test_flush_generates_sql_commands(self):
        """Test flush generates SQL INSERT commands for accumulated data."""
        helper = DAMFileHelper(period=60, n_rois=2)
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)

        # Add activity data
        data1 = {"x": 0, "y": 0}
        helper.input_roi_data(60000, roi, data1)  # tick=1
        data2 = {"x": 10, "y": 0}
        helper.input_roi_data(60500, roi, data2)  # tick=1

        # Flush at tick=3 (should output tick=1,2)
        result = helper.flush(180000)

        # Should have 2 SQL commands (tick 1 and tick 2)
        self.assertGreater(len(result), 0)
        for cmd in result:
            self.assertIn("INSERT INTO CSV_DAM_ACTIVITY", cmd)
            self.assertIn("date", cmd)
            self.assertIn("time", cmd)
            self.assertIn("ROI_1", cmd)

    def test_flush_clears_accumulated_data(self):
        """Test flush clears accumulated activity data."""
        helper = DAMFileHelper(period=60)
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)

        # Add and flush
        helper.input_roi_data(60000, roi, {"x": 0, "y": 0})
        helper.flush(180000)

        # Activity for past ticks should be cleared
        self.assertNotIn(1, helper._activity_accum)

    def test_make_sql_command_formats_correctly(self):
        """Test _make_sql_command generates well-formatted SQL."""
        helper = DAMFileHelper(n_rois=2)

        vals = OrderedDict({1: 0.5, 2: 1.2})
        command = helper._make_sql_command(vals)

        self.assertIn("INSERT INTO CSV_DAM_ACTIVITY", command)
        self.assertIn("date", command)
        self.assertIn("time", command)
        self.assertIn("ROI_1", command)
        self.assertIn("ROI_2", command)
        # Check scaled integer values
        self.assertIn("50", command)  # 0.5 * 100
        self.assertIn("120", command)  # 1.2 * 100


class TestNpyAppendableFile(unittest.TestCase):
    """Test suite for NpyAppendableFile."""

    def setUp(self):
        """Create temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.temp_dir, "test_data.txt")

    def tearDown(self):
        """Clean up temporary files."""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_init_changes_extension_to_anpy(self):
        """Test initialization converts file extension to .anpy."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)

        expected_name = os.path.join(self.temp_dir, "test_data.anpy")
        self.assertEqual(npyfile.fname, expected_name)

    def test_init_preserves_anpy_extension(self):
        """Test initialization preserves .anpy extension if already present."""
        anpy_file = os.path.join(self.temp_dir, "test.anpy")
        npyfile = NpyAppendableFile(anpy_file, newfile=True)

        self.assertEqual(npyfile.fname, anpy_file)

    def test_write_creates_new_file(self):
        """Test write creates new file when newfile=True on first write."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        data = np.array([1, 2, 3])

        result = npyfile.write(data)

        self.assertTrue(result)
        self.assertTrue(os.path.exists(npyfile.fname))

    def test_write_appends_to_existing_file(self):
        """Test write appends to existing file on subsequent writes."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)

        # First write
        data1 = np.array([1, 2, 3])
        npyfile.write(data1)

        # Second write should append
        data2 = np.array([4, 5, 6])
        result = npyfile.write(data2)

        self.assertTrue(result)

    def test_write_appends_when_newfile_false(self):
        """Test write appends immediately when newfile=False."""
        # Create initial file
        npyfile1 = NpyAppendableFile(self.test_file, newfile=True)
        npyfile1.write(np.array([1, 2, 3]))

        # Open with newfile=False to append
        npyfile2 = NpyAppendableFile(self.test_file, newfile=False)
        result = npyfile2.write(np.array([4, 5, 6]))

        self.assertTrue(result)

    def test_load_reads_single_array(self):
        """Test load reads single array from file."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        data = np.array([[1, 2], [3, 4]])
        npyfile.write(data)

        loaded = npyfile.load(axis=0)

        np.testing.assert_array_equal(loaded, data)

    def test_load_concatenates_multiple_arrays(self):
        """Test load concatenates multiple appended arrays."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)

        # Write multiple arrays
        data1 = np.array([[1, 2]])
        data2 = np.array([[3, 4]])
        data3 = np.array([[5, 6]])

        npyfile.write(data1)
        npyfile.write(data2)
        npyfile.write(data3)

        loaded = npyfile.load(axis=0)

        expected = np.array([[1, 2], [3, 4], [5, 6]])
        np.testing.assert_array_equal(loaded, expected)

    def test_convert_creates_npy_file(self):
        """Test convert creates standard .npy file."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        data = np.array([[1, 2], [3, 4]])
        npyfile.write(data)

        # Convert to .npy
        npy_filename = os.path.join(self.temp_dir, "output.npy")
        npyfile.convert(filename=npy_filename)

        # Verify .npy file was created and can be loaded
        self.assertTrue(os.path.exists(npy_filename))
        loaded = np.load(npy_filename)
        np.testing.assert_array_equal(loaded, data)

    def test_convert_uses_default_filename(self):
        """Test convert uses default filename when none provided."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        data = np.array([1, 2, 3])
        npyfile.write(data)

        npyfile.convert()

        # Should create test_data.npy
        expected_name = os.path.join(self.temp_dir, "test_data.npy")
        self.assertTrue(os.path.exists(expected_name))

    def test_dtype_property(self):
        """Test _dtype property returns correct data type."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        data = np.array([1.5, 2.5, 3.5], dtype=np.float32)
        npyfile.write(data)

        dtype = npyfile._dtype

        self.assertEqual(dtype, np.float32)

    def test_actual_shape_property(self):
        """Test _actual_shape property returns correct shape."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        # Use 3D arrays to match default axis=2 in load()
        data1 = np.array([[[1], [2]]])  # shape (1, 2, 1)
        data2 = np.array([[[3], [4]]])  # shape (1, 2, 1)
        npyfile.write(data1)
        npyfile.write(data2)

        shape = npyfile._actual_shape

        self.assertEqual(shape, (1, 2, 2))  # Concatenated along axis 2

    def test_header_property_reads_numpy_header(self):
        """Test header property reads numpy file format information."""
        npyfile = NpyAppendableFile(self.test_file, newfile=True)
        data = np.array([[1, 2], [3, 4]], dtype=np.int32)
        npyfile.write(data)

        version, header = npyfile.header

        self.assertIsNotNone(version)
        self.assertIn("descr", header)
        self.assertIn("fortran_order", header)
        self.assertIn("shape", header)
        self.assertEqual(header["shape"], (2, 2))


class TestRawDataWriter(unittest.TestCase):
    """Test suite for RawDataWriter."""

    def setUp(self):
        """Create temporary directory for test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_basename = os.path.join(self.temp_dir, "raw_data.db")

    def tearDown(self):
        """Clean up temporary files."""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_init_creates_files_for_rois(self):
        """Test initialization creates NpyAppendableFile for each ROI."""
        writer = RawDataWriter(self.test_basename, n_rois=3)

        self.assertEqual(len(writer.files), 3)
        for npy_file in writer.files:
            self.assertIsInstance(npy_file, NpyAppendableFile)

    def test_init_strips_extension_from_basename(self):
        """Test initialization strips extension from basename."""
        writer = RawDataWriter(self.test_basename, n_rois=2)

        # Files should be named with _basename (no .db extension)
        expected_basename = os.path.join(self.temp_dir, "raw_data")
        for npy_file in writer.files:
            self.assertTrue(npy_file.fname.startswith(expected_basename))

    def test_init_sets_entities(self):
        """Test initialization sets maximum entities."""
        writer = RawDataWriter(self.test_basename, n_rois=2, entities=50)

        self.assertEqual(writer.entities, 50)

    def test_init_default_entities(self):
        """Test initialization uses default entities=40."""
        writer = RawDataWriter(self.test_basename, n_rois=2)

        self.assertEqual(writer.entities, 40)

    def test_write_stores_data_in_data_dict(self):
        """Test write stores tracking data in internal data dictionary."""
        writer = RawDataWriter(self.test_basename, n_rois=2)
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)

        data_rows = [
            {"x": 10, "y": 20, "w": 5, "h": 5, "phi": 0.5},
            {"x": 30, "y": 40, "w": 6, "h": 6, "phi": 1.2},
        ]

        writer.write(t=1000, roi=roi, data_rows=data_rows)

        self.assertIn(roi.idx, writer.data)
        self.assertIsInstance(writer.data[roi.idx], np.ndarray)

    def test_write_creates_fixed_shape_array(self):
        """Test write creates array with fixed shape based on entities."""
        writer = RawDataWriter(self.test_basename, n_rois=2, entities=10)
        roi = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1)

        data_rows = [{"x": 10, "y": 20, "w": 5, "h": 5, "phi": 0.5}]

        writer.write(t=1000, roi=roi, data_rows=data_rows)

        # Array should have shape (entities, 6, 1) where 6 is (t, x, y, w, h, phi)
        self.assertEqual(writer.data[roi.idx].shape, (10, 6, 1))

    def test_flush_writes_data_to_files(self):
        """Test flush writes accumulated data to NpyAppendableFile instances."""
        writer = RawDataWriter(self.test_basename, n_rois=2)
        roi1 = ROI(polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=0, value=1)
        roi2 = ROI(polygon=((100, 0), (200, 0), (200, 100), (100, 100)), idx=1, value=2)

        # Write data for both ROIs
        data_rows1 = [{"x": 10, "y": 20, "w": 5, "h": 5, "phi": 0.5}]
        data_rows2 = [{"x": 30, "y": 40, "w": 6, "h": 6, "phi": 1.2}]

        writer.write(t=1000, roi=roi1, data_rows=data_rows1)
        writer.write(t=1000, roi=roi2, data_rows=data_rows2)

        # Flush should write to files
        writer.flush(t=1000, frame=None)

        # Verify files were created
        for npy_file in writer.files:
            self.assertTrue(os.path.exists(npy_file.fname))


if __name__ == "__main__":
    unittest.main()
