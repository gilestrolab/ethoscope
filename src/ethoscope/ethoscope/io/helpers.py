import os
import time
import datetime
import logging
import tempfile
import numpy as np
from collections import OrderedDict
from cv2 import imwrite, IMWRITE_JPEG_QUALITY

# Constants from base.py
SENSOR_DEFAULT_PERIOD = 120.0  # Default sensor sampling period in seconds
IMG_SNAPSHOT_DEFAULT_PERIOD = (
    300.0  # Default image snapshot period in seconds (5 minutes)
)
DAM_DEFAULT_PERIOD = 60.0  # Default DAM activity sampling period in seconds


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
            self._base_headers = {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "t": "INTEGER",
            }
        else:  # MySQL
            self._base_headers = {
                "id": "INT NOT NULL AUTO_INCREMENT PRIMARY KEY",
                "t": "INT",
            }

        # Build table headers with appropriate data types
        self._table_headers = {
            **self._base_headers,
            **self._get_sensor_types_for_database(),
        }

    def flush(self, t):
        """
        Save sensor data if enough time has elapsed since last save.

        Args:
            t (int): Current time in milliseconds

        Returns:
            tuple: (SQL command, args) or None if not time to save
        """
        tick = int(round((t / 1000.0) / self._period))
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
                    + " ("
                    + ",".join(columns)
                    + ")"
                    + " VALUES ("
                    + ",".join(values)
                    + ")"
                )
            else:
                # For MySQL, explicit ID=0 is fine (will be auto-incremented)
                values = [str(v) for v in ((0, int(t)) + self.sensor.read_all())]
                cmd = (
                    "INSERT into "
                    + self._table_name
                    + " VALUES ("
                    + ",".join(values)
                    + ")"
                )
            self._last_tick = tick
            return cmd, None

        except:
            logging.error("The sensor data are not available")
            self._last_tick = tick
            return

    @property
    def table_name(self):
        """Get the sensor table name."""
        return self._table_name

    def _get_sensor_types_for_database(self):
        """
        Convert sensor types to appropriate database format.

        Returns:
            dict: Sensor field names mapped to database-appropriate data types
        """
        if not hasattr(self.sensor, "sensor_types"):
            return {}

        sensor_types = {}
        for field_name, mysql_type in self.sensor.sensor_types.items():
            if self._database_type == "SQLite3":
                # Convert MySQL types to SQLite equivalents
                if mysql_type.upper() in ["FLOAT", "DOUBLE"]:
                    sqlite_type = "REAL"
                elif mysql_type.upper().startswith("INT"):
                    sqlite_type = "INTEGER"
                elif mysql_type.upper().startswith(("CHAR", "VARCHAR", "TEXT")):
                    sqlite_type = "TEXT"
                else:
                    sqlite_type = "TEXT"  # Default fallback
                sensor_types[field_name] = sqlite_type
            else:
                # Use original MySQL types
                sensor_types[field_name] = mysql_type

        return sensor_types

    @property
    def create_command(self):
        """Generate SQL CREATE TABLE command for sensor data."""
        return ",".join(
            ["%s %s" % (key, self._table_headers[key]) for key in self._table_headers]
        )


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
            self._table_headers = {
                "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                "t": "INTEGER",
                "img": "BLOB",
            }
        else:  # MySQL
            self._table_headers = {
                "id": "INT NOT NULL AUTO_INCREMENT PRIMARY KEY",
                "t": "INT",
                "img": "LONGBLOB",
            }

    @property
    def table_name(self):
        """Get the image snapshots table name."""
        return self._table_name

    @property
    def create_command(self):
        """Generate SQL CREATE TABLE command for image snapshots."""
        return ",".join(
            ["%s %s" % (key, self._table_headers[key]) for key in self._table_headers]
        )

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
        tick = int(round((t / 1000.0) / self._period))
        if tick == self._last_tick:
            return
        imwrite(self._tmp_file, img, [int(IMWRITE_JPEG_QUALITY), 50])
        with open(self._tmp_file, "rb") as f:
            bstring = f.read()

        if self._database_type == "SQLite3":
            # For SQLite, don't specify ID - let AUTOINCREMENT handle it
            cmd = "INSERT INTO " + self._table_name + "(t,img) VALUES (?,?)"
            args = (int(t), bstring)
        else:
            # For MySQL, explicit ID=0 is fine (will be auto-incremented)
            cmd = "INSERT INTO " + self._table_name + "(id,t,img) VALUES (%s,%s,%s)"
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
        self._distance_map = {}
        self._last_positions = {}
        self._scale = 100  # multiply by this factor before converting to int activity
        for i in range(1, self._n_rois + 1):
            self._distance_map[i] = 0
            self._last_positions[i] = None

    def make_dam_file_sql_fields(self):
        """
        Generate SQL field definitions for DAM-compatible activity table.

        Returns:
            str: Comma-separated field definitions for CREATE TABLE
        """
        fields = [
            "id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY",
            "date CHAR(100)",
            "time CHAR(100)",
        ]
        for r in range(1, self._n_rois + 1):
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
        current_pos = data["x"] + 1j * data["y"]
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
        tick = int(round((t / 1000.0) / self._period))
        act = self._compute_distance_for_roi(roi, data)
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
        for i in range(1, self._n_rois + 1):
            values.append(int(round(self._scale * vals[i])))
        command = (
            """INSERT INTO CSV_DAM_ACTIVITY (date, time, """
            + ", ".join([f"ROI_{i}" for i in range(1, self._n_rois + 1)])
            + """) VALUES %s""" % str(tuple(values))
        )
        return command

    def flush(self, t):
        """
        Generate SQL commands for all accumulated activity data.

        Args:
            t (int): Current time in milliseconds

        Returns:
            list: SQL INSERT commands for accumulated data
        """
        out = OrderedDict()
        tick = int(round((t / 1000.0) / self._period))
        if len(self._activity_accum) < 1:
            self._activity_accum[tick] = OrderedDict()
            for r in range(1, self._n_rois + 1):
                self._activity_accum[tick][r] = 0
            return []

        m = min(self._activity_accum.keys())
        todel = []
        for i in range(m, tick):
            if i not in list(self._activity_accum.keys()):
                self._activity_accum[i] = OrderedDict()
                for r in range(1, self._n_rois + 1):
                    self._activity_accum[i][r] = 0
            out[i] = self._activity_accum[i].copy()
            todel.append(i)
            for r in range(1, self._n_rois + 1):
                out[i][r] = round(out[i][r], 5)

        for i in todel:
            del self._activity_accum[i]

        if tick - m > 1:
            logging.warning(
                "DAM file writer skipping a tick. No data for more than one period!"
            )
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
# VARIOUS OTHER CLASSES
#
# =============================================================================================================#


class NpyAppendableFile:
    """
    Custom file format for efficiently appending numpy arrays.

    Creates .anpy files that can be incrementally written to without loading
    the entire file into memory. Can be converted to standard .npy format.
    """

    def __init__(self, fname, newfile=True):
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

        if filename is None:
            filepath, _ = os.path.splitext(self.fname)
            filename = filepath + ".npy"

        with open(filename, "wb") as fh:
            np.save(fh, content)

        print(
            "New .npy compatible file saved with name %s. Use numpy.load to load data from it. The array has a shape of %s"
            % (filename, content.shape)
        )

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

        return version, {"descr": dtype, "fortran_order": fortran, "shape": shape}


class RawDataWriter:
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
        self._basename, _ = os.path.splitext(basename)

        self.entities = entities
        self.files = [
            NpyAppendableFile(
                os.path.join("%s_%03d" % (self._basename, n_rois) + ".anpy"),
                newfile=True,
            )
            for r in range(n_rois)
        ]

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
        # Convert data_rows to an array with shape (nf, 5) where nf is the number of flies in the ROI
        arr = np.asarray(
            [
                [t, fly["x"], fly["y"], fly["w"], fly["h"], fly["phi"]]
                for fly in data_rows
            ]
        )
        # The size of data_rows depends on how many contours were found. The array needs to have a fixed shape so we round it to self.entities as the max number of flies allowed
        arr.resize((self.entities, 6, 1), refcheck=False)
        self.data[roi.idx] = arr
