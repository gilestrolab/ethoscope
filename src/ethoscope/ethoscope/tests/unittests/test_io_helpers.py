"""
Unit tests for I/O helper classes (io/helpers.py).

Tests helper classes for periodic data collection and storage:
- SensorDataHelper: Environmental sensor data collection
- ImgSnapshotHelper: Image snapshot storage
- DAMFileHelper: DAM-compatible activity monitoring
- Null: SQLite NULL representation
"""

import os
import unittest
from collections import OrderedDict
from unittest.mock import Mock

import numpy as np

from ethoscope.core.roi import ROI
from ethoscope.io.helpers import (
    DAMFileHelper,
    ImgSnapshotHelper,
    Null,
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
        helper = SensorDataHelper(
            self.mock_sensor, period=60, database_type="SQLite3"
        )

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
        helper = SensorDataHelper(
            self.mock_sensor, period=60, database_type="SQLite3"
        )

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
        roi = ROI(
            polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1
        )
        data = {"x": 50, "y": 50}

        distance = helper._compute_distance_for_roi(roi, data)

        self.assertEqual(distance, 0)
        self.assertIsNotNone(helper._last_positions[roi.idx])

    def test_compute_distance_calculates_normalized_movement(self):
        """Test _compute_distance_for_roi calculates correct normalized distance."""
        helper = DAMFileHelper()
        roi = ROI(
            polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1
        )

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
        roi = ROI(
            polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1
        )

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
        roi = ROI(
            polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1
        )

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
        roi = ROI(
            polygon=((0, 0), (100, 0), (100, 100), (0, 100)), idx=1, value=1
        )

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


if __name__ == "__main__":
    unittest.main()
