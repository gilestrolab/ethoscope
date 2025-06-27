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

#for mariadb
SQL_CHARSET = 'latin1'


def list_local_video_files(rootdir, createMD5=True):
    """
    Creates an index of all the video files in the provided formats and their associated MD5 checksum values.

    Scans the `rootdir` directory and subdirectories for video files with the specified formats,
    and retrieves the corresponding MD5 checksum values from `.md5` files located in the same directory
    as each video file. Returns the information as a JSON dictionary. 

    With createMD5 set to True (Default) it will compute the hash and save a new file when
    an associated `.md5` is not found on the first place.

    Returns:
        dict: A dictionary with video file paths as keys and their associated MD5 checksum values as values.
        Example:
            {
                "/path/to/video1.mp4": "e99a18c428cb38d5f260853678922e03",
                "/path/to/video2.avi": "098f6bcd4621d373cade4e832627b4f6"
            }

    Raises:
        KeyError: If a required property such as `_ETHOSCOPE_DIR` is missing.
        IOError: If there is an issue reading the video or `.md5` files.
    """
    #video_formats = ['h264', 'avi', 'mp4']
    video_formats = ['h264']
    result = {}

    # Retrieve all video files in the specified formats
    all_video_files = [
        video_file
        for root, dirs, files in os.walk(rootdir)
        for video_file in glob.glob(os.path.join(root, '*.*'))
        if video_file.endswith(tuple(video_formats))
    ]

    for video_file in all_video_files:
        # Generate the corresponding `.md5` filename
        filename = os.path.basename(video_file)
        md5_file = f"{video_file}.md5"
        try:
            # Read the MD5 checksum from the `.md5` file
            if os.path.exists(md5_file):
                with open(md5_file, "r") as f:
                    md5sum_value = f.read().strip()
            else:
                if createMD5:
                    logging.info (f"MD5 file {md5_file} not found. Calculating ex novo for {video_file}")                
                    md5sum_value = save_hash_info_file (video_file)
                else:
                    md5sum_value = ""

            result[filename] = {'path' : video_file, 'hash' : md5sum_value}

        except Exception as e:
            logging.error(f"Failed to process file {video_file} or its MD5 checksum: {str(e)}")
            result[filename] = {}

    return result


def save_hash_info_file(filename_to_hash, writefile=True):
    """
    Generate an MD5 hash for the specified file and save it to a new file with a ".md5" extension.

    This function computes the MD5 hash of the given file (e.g., a video file) and writes the
    computed hash string to a text file. The generated hash file will have the same name
    as the input file, with a ".md5" extension appended.

    Parameters:
    -----------
    filename_to_hash : str
        The path to the file for which the MD5 hash should be calculated and saved.

    Returns:
    --------
    str
        The computed MD5 hash of the input file.

    Internal Functions:
    -------------------
    compute_md5(file_path):
        Computes the MD5 hash of a given file. The file is read in chunks to conserve memory
        when processing large files.

    Example:
    --------
    If `filename_to_hash` is "example_video.mp4", this function will:
    1. Compute the MD5 hash of "example_video.mp4".
    2. Create a new file named "example_video.mp4.md5".
    3. Write the computed hash to "example_video.mp4.md5".

    Usage:
    ------
    >>> save_hash_info_file("example_video.mp4")
    'd41d8cd98f00b204e9800998ecf8427e'  # Example hash value (real values will differ)
    """
    def compute_md5(file_path):
        """
        Compute the MD5 hash of the provided file.

        Parameters:
        -----------
        file_path : str
            The path to the file for which the MD5 hash will be calculated.

        Returns:
        --------
        str
            The MD5 hash of the input file in hexadecimal format.
        """
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as file:
            # Read the file in 4 KB chunks to avoid high memory usage
            for chunk in iter(lambda: file.read(4096), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()


    # Wait until the file is fully written
    stable = False
    previous_size = os.path.getsize(filename_to_hash)
    time.sleep(0.5)
    while not stable:
        time.sleep(0.5)
        current_size = os.path.getsize(filename_to_hash)
        if current_size == previous_size:
            stable = True  # The file size has stabilized, we can proceed with the hash
        else:
            previous_size = current_size  # Update size for the next check

    file_hash = compute_md5(filename_to_hash)
    if writefile:
        hash_file = filename_to_hash + ".md5"
        with open(hash_file, "w") as file:
            file.write(file_hash)

    return file_hash

def get_and_hash(target, target_prefix, output_dir, cut_dirs=2):
    """
    Downloads a file from a specified target URL using wget and generates an MD5 checksum file.

    This function constructs a command to use the `wget` utility for downloading a file
    from a remote server. It calculates the exact local file path based on the target URL,
    ensures the necessary directories exist, and instructs `wget` to save the file to that path.
    After downloading, it computes the MD5 checksum of the downloaded file and writes it to
    an adjacent `.md5sum.txt` file.

    Args:
        target (str): The target file or directory to download, relative to the target_prefix.
        target_prefix (str): The base URL prefix to prepend to the target.
        output_dir (str): The local directory where the files will be downloaded.
        cut_dirs (int, optional): The number of directory levels to cut from the input URL.
                                Defaults to 3.

    Returns:
        bool: True if the download and MD5 checksum generation were successful; 
            False if no content was downloaded.

    Raises:
        Exception: If the wget command fails to execute successfully, an Exception
                is raised with the return code and the output from wget.
        FileNotFoundError: If the downloaded file is not found for MD5 computation.
    """
    
    # Ensure the target URL is properly formatted
    target_url = target_prefix.rstrip('/') + '/' + target.lstrip('/')
    
    # Split the target path into its components
    target_path_parts = target.strip('/').split('/')
    
    # Apply 'cut_dirs' to remove the specified number of directory levels
    if len(target_path_parts) <= cut_dirs:
        raise ValueError(f"The target path '{target}' does not have enough directories to cut {cut_dirs} levels.")
    
    relative_path_parts = target_path_parts[cut_dirs:]
    relative_path = os.path.join(*relative_path_parts)
    local_file_path = os.path.join(output_dir, relative_path)
    
    # Construct the wget command with '-O' to specify the exact output file path
    command = [
        "wget",
        target_url,
        "-nv",               # Non-verbose
        "-c",                # Resume incomplete downloads
        "-O",                # Specify output file
        local_file_path
    ]

    try:
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        #logging.info(f"Executing command: {' '.join(command)}")
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        #logging.debug(f"wget stdout: {result.stdout}")
        #logging.debug(f"wget stderr: {result.stderr}")

        if result.stdout: 
            # this is empty if wget finds the file was already downloaded
            # in that case we do not have to compute the hash
        
            if not os.path.isfile(local_file_path):
                logging.warning(f"No file found at '{local_file_path}'.")
                return False
            if os.path.getsize(local_file_path) == 0:
                logging.warning(f"Downloaded file '{local_file_path}' is empty.")
                return False
            logging.info("File downloaded. Now creating a md5 hash for it")	        
            save_hash_info_file (local_file_path)
        
            return True
        
        else:
            return False

    except subprocess.CalledProcessError as e:
        logging.error(f"wget failed with return code {e.returncode}: {e.stderr}")
        raise Exception(f"wget error {e.returncode}: {e.stderr}") from e
    except FileNotFoundError as fnf_error:
        logging.error(str(fnf_error))
        raise
    except Exception as ex:
        logging.error(f"An unexpected error occurred: {str(ex)}")
        raise

class AsyncMySQLWriter(multiprocessing.Process):
    
    _db_host = "localhost"
    #_db_host = "node" #uncomment this to save data on the node

    def __init__(self, db_credentials, queue, erase_old_db=True):
        """
        """
        self._db_name = db_credentials["name"]
        self._db_user_name = db_credentials["user"]
        self._db_user_pass = db_credentials["password"]
        self._erase_old_db = erase_old_db

        self._queue = queue
        self._ready_event = multiprocessing.Event()

        super(AsyncMySQLWriter,self).__init__()


    def _delete_my_sql_db(self):

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

        # In case we use binary logging, we remove bin logs to save space.
        # However, this will throw an error if binary logging is set to off
        # Which is what we should be doing because it reduces disk access and we do not need it anyway
        c.execute("SHOW VARIABLES LIKE 'log_bin';")
        log_bin_status = c.fetchone()
        if log_bin_status and log_bin_status[1] == 'ON':
            logging.info("The binary logs are set to true. Resetting them to save space.")
            c.execute("RESET MASTER")

        to_execute  = []
        for t in c:
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

        db = mysql.connector.connect(host=self._db_host,
                                     user=self._db_user_name,
                                     passwd=self._db_user_pass,
                                     buffered=True,
                                     charset=SQL_CHARSET,
                                     use_unicode=True)

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
        Processes the queue to commit changes to the db
        """
        
        db = None
        do_run = True
        
        try:
            if self._erase_old_db:
                self._delete_my_sql_db()
                self._create_mysql_db()

            db = self._get_connection()
            
            # Signal that the writer is ready to accept commands
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

                except:
                    do_run = False
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
            logging.error("DB async process stopped with an exception")
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
    _table_name = "SENSORS"
    _base_headers = {"id" : "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", 
                     "t"  : "INT" }
                          
    def __init__(self, sensor, period=120.0):
        """
        :param sensor: the sensor object to be interrogated
        :param period: how often sensor data are saved, in seconds
        :return:
        """
        self._period = period
        self._last_tick = 0
        self.sensor = sensor
        self._table_headers = {**self._base_headers, **self.sensor.sensor_types}
        
                            
    def flush(self, t):
        """
        :param t: the time since start of the experiment, in ms
        :param sensor_data: a dict containing the sensor data
        :type sensor_data: dict
        :return:
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
        return self._table_name

    @property
    def create_command(self):
        return ",".join([ "%s %s" % (key, self._table_headers[key]) for key in self._table_headers])



class ImgToMySQLHelper(object):
    _table_name = "IMG_SNAPSHOTS"
    _table_headers = {"id" : "INT NOT NULL AUTO_INCREMENT PRIMARY KEY", 
                      "t"  : "INT",
                      "img" : "LONGBLOB"}

    @property
    def table_name (self):
        return self._table_name

    @property
    def create_command(self):
        return ",".join([ "%s %s" % (key, self._table_headers[key]) for key in self._table_headers])
    
    def __init__(self, period=300.0):
        """
        :param period: how often snapshots are saved, in seconds
        :return:
        """

        self._period = period
        self._last_tick = 0
        self._tmp_file = tempfile.mktemp(prefix="ethoscope_", suffix=".jpg")

    def __del__(self):
        try:
            os.remove(self._tmp_file)
        except:
            logging.error("Could not remove temp file: %s" % self._tmp_file)


    def flush(self, t, img):
        """

        :param t: the time since start of the experiment, in ms
        :param img: an array representing an image.
        :type img: np.ndarray
        :return:
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

    def __init__(self, period=60.0, n_rois=32):
        self._period = period


        self._activity_accum = OrderedDict()
        self._n_rois = n_rois
        self._distance_map ={}
        self._last_positions ={}
        self._scale = 100 # multiply by this factor before converting wor to float activity

        for i in range(1, self._n_rois +1):
            self._distance_map[i] = 0
            self._last_positions[i] = None

    def make_dam_file_sql_fields(self):
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY",
          "date CHAR(100)",
          "time CHAR(100)"]

        for i in range(7):
            fields.append("DUMMY_FIELD_%d SMALLINT" % i)
        for r in range(1,self._n_rois +1):
            fields.append("ROI_%d SMALLINT" % r)
        logging.info("Creating 'CSV_DAM_ACTIVITY' table")
        fields = ",".join(fields)
        return fields

    def _compute_distance_for_roi(self, roi, data):
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
        tick = int(round((t/1000.0)/self._period))
        act  = self._compute_distance_for_roi(roi,data)
        if tick not in self._activity_accum:
            self._activity_accum[tick] = OrderedDict()
            for r in range(1, self._n_rois + 1):
                self._activity_accum[tick][r] = 0

        self._activity_accum[tick][roi.idx] += act

    def _make_sql_command(self, vals):

        dt = datetime.datetime.fromtimestamp(int(time.time()))
        date_time_fields = dt.strftime("%d %b %Y,%H:%M:%S").split(",")
        values = [0] + date_time_fields

        for i in range(7):
            values.append(str(i))
        for i in range(1, self._n_rois +1):
            values.append(int(round(self._scale * vals[i])))

        command = '''INSERT INTO CSV_DAM_ACTIVITY VALUES %s''' % str(tuple(values))
        return command


    def flush(self, t):

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
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _async_writing_class = AsyncMySQLWriter
    _null = 0
    
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=True, take_frame_shots=False, erase_old_db=True, sensor=None, *args, **kwargs):
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
            command = "INSERT INTO START_EVENTS VALUES %s" % str((self._null, int(time.time()), event))
            self._write_async_command(command)

        logging.info("Result writer initialised")
        
    def _create_all_tables(self):
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
        self._create_table("METADATA", "field CHAR(100), value VARCHAR(3000)")

        logging.info("Creating 'START_EVENTS' table")
        self._create_table("START_EVENTS", "id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY, t INT, event CHAR(100)")
        event = "graceful_start"
        command = "INSERT INTO START_EVENTS VALUES %s" % str((self._null, int(time.time()), event))
        self._write_async_command(command)


        for k,v in list(self.metadata.items()):
            command = "INSERT INTO METADATA VALUES %s" % str((k, v))
            self._write_async_command(command)
        
        while not self._queue.empty():
            logging.info("waiting for queue to be processed")
            time.sleep(.1)

    @property
    def metadata(self):
        return self._metadata

    def write(self, t, roi, data_rows):

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
        This is were we actually write SQL commands
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
        logging.info("Filling 'VAR_MAP' with values")
        # we recreate var map so we do not have duplicate entries
        self._write_async_command("DELETE FROM VAR_MAP")

        for dt in list(data_row.values()):
            command = "INSERT INTO VAR_MAP VALUES %s"% str((dt.header_name, dt.sql_data_type, dt.functional_type))
            self._write_async_command(command)
        self._var_map_initialised = True



    def _initialise(self, roi, data_row):
        # We make a new dir to store results
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY" ,"t INT"]
        for dt in list(data_row.values()):
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))
        fields = ", ".join(fields)
        table_name = "ROI_%i" % roi.idx
        self._create_table(table_name, fields)


    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.info("Closing result writer...")
        for k, v in list(self._insert_dict.items()):
            self._write_async_command(v)
            self._insert_dict[k] = ""

        try:
            command = "INSERT INTO METADATA VALUES %s" % str(("stop_date_time", str(int(time.time()))))
            self._write_async_command(command)
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
        pass

    def _write_async_command(self, command, args=None):
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
        command = "CREATE TABLE IF NOT EXISTS %s (%s) ENGINE %s KEY_BLOCK_SIZE=16;" % (name, fields, engine)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)

    # def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=True, take_frame_shots=False, erase_old_db=True *args, **kwargs):
    def __getstate__(self):
        return {"args": {"db_credentials": self._db_credentials,
                         "rois": self._rois,
                         "metadata": self._metadata,
                         "make_dam_like_table": self._make_dam_like_table,
                         "take_frame_shots": self._take_frame_shots,
                         "erase_old_db": False}}

    def __setstate__(self, state):
        self.__init__(**state["args"])


class AsyncSQLiteWriter(multiprocessing.Process):
    _pragmas = {"temp_store": "MEMORY",
                "journal_mode": "OFF",
                "locking_mode":  "EXCLUSIVE"}

    def __init__(self, db_name, queue, erase_old_db=True):
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

        db =   sqlite3.connect(self._db_name)
        return db


    def run(self):

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
            logging.error("DB async process stopped with an exception")
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
    def __repr__(self):
        return "NULL"
    def __str__(self):
        return "NULL"

class SQLiteResultWriter(ResultWriter):
    _async_writing_class = AsyncSQLiteWriter
    _null= Null()
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=False, take_frame_shots=False, *args, **kwargs):
        super(SQLiteResultWriter, self).__init__(db_credentials, rois, metadata,make_dam_like_table, take_frame_shots, *args, **kwargs)


    def _create_table(self, name, fields, engine=None):

        fields = fields.replace("NOT NULL", "")
        command = "CREATE TABLE IF NOT EXISTS %s (%s)" % (name,fields)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)

    def _add(self, t, roi, data_rows):
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
    def __init__(self, fname, newfile = True):
        '''
        Creates a new instance of the appendable filetype
        If newfile is True, recreate the file even if already exists
        '''
        filepath, extension = os.path.splitext(fname)
        self.fname = filepath + ".anpy"
        
        self._newfile = newfile
        self._first_write = True
        
    def write(self, data):
        '''
        append a new array to the file
        note that this will not change the header
        '''
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
        '''
        Load the whole file, returning all the arrays that were consecutively
        saved on top of each other
        axis defines how the arrays should be concatenated
        '''
        
        with open(self.fname, "rb") as fh:
            fsz = os.fstat(fh.fileno()).st_size
            out = np.load(fh)
            while fh.tell() < fsz:
                out = np.concatenate((out, np.load(fh)), axis=axis)
            
        return out
    
    
    def convert(self, filename=None):
        '''
        We created the new file by appending new arrays to an existing npy
        The header, however, has remained constant and describes the very first array
        Here we reload the all content and we save it with the appropriate array, hence transforming a .anpy file to a regular .npy one
        '''
        
        content = self.load()
        
        if filename == None:
            filepath, _ = os.path.splitext(self.fname)
            filename = filepath + ".npy"
        
        with open(filename, "wb") as fh:
            np.save(fh, content)
            
        print ("New .npy compatible file saved with name %s. Use numpy.load to load data from it. The array has a shape of %s" % (filename, content.shape))

    @property
    def _dtype(self):
        return self.load().dtype

    @property
    def _actual_shape(self):
        return self.load().shape
    
    @property
    def header(self):
        '''
        Reads the header of the npy file
        '''
        with open(self.fname, "rb") as fh:
            version = np.lib.format.read_magic(fh)
            shape, fortran, dtype = np.lib.format._read_array_header(fh, version)
        
        return version, {'descr': dtype,
                         'fortran_order' : fortran,
                         'shape' : shape}

class rawdatawriter():
    '''
    A writer used for offline data analysis
    Writes the raw data to a np array with extension .anpy
    Note that by default this is not a regular npy file because the header of the file
    describe a small array. The .anpy can be converted to .npy using the update_content property
    '''
    
    def __init__(self, basename, n_rois, entities=40):

        self._basename, _ = os.path.splitext (basename)
        
        
        self.entities = entities

        self.files = [ npyAppendableFile (os.path.join("%s_%03d" % (self._basename, n_rois) + ".anpy"), newfile = True ) for r in range(n_rois) ]
        
        self.data = dict()
        
    def flush(self, t, frame):
        '''
        Called at the end of each frame
        Used to commit the changes to the file and close it
        '''
        for row, fh in zip(self.data, self.files):
            fh.write(self.data[row])
        
    def write(self, t, roi, data_rows):
        '''
        Get data data for each roi at time t
        
        data_rows is something like the below:
        DataPoint([('x', 236), ('y', 94), ('w', 23), ('h', 9), ('phi', 39), ('is_inferred', 0), ('has_interacted', 0)])]

        '''

        #Convert data_rows to an array with shape (nf, 5) where nf is the number of flies in the ROI
        arr = np.asarray([[t, fly['x'], fly['y'], fly['w'], fly['h'], fly['phi']] for fly in data_rows])
        #The size of data_rows depends on how many contours were found. The array needs to have a fixed shape so we round it to self.entities as the max number of flies allowed
        arr.resize((self.entities, 6, 1), refcheck=False)
        self.data[roi.idx] = arr

