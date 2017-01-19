__author__ = 'quentin'
import multiprocessing
import time, datetime
import traceback
import logging
from collections import OrderedDict
import cv2
import tempfile
import os


class AsyncMySQLWriter(multiprocessing.Process):

    def __init__(self, db_credentials, queue, erase_old_db=True):
        self._db_name = db_credentials["name"]
        self._db_user_name = db_credentials["user"]
        self._db_user_pass = db_credentials["password"]
        self._erase_old_db = erase_old_db

        self._queue = queue

        # if erase_old_db:
        #     self._delete_my_sql_db()
        #     self._create_mysql_db()
        super(AsyncMySQLWriter,self).__init__()


    def _delete_my_sql_db(self):
        import MySQLdb
        try:
            db =   MySQLdb.connect(host="localhost",
                 user=self._db_user_name, passwd=self._db_user_pass, db=self._db_name)
        except MySQLdb.OperationalError:
            logging.warning("Database does not exist. Cannot delete it")
            return

        logging.info("connecting to mysql db")
        c = db.cursor()
        #Truncate all tables before dropping db for performance
        command = "SHOW TABLES"
        c.execute(command)

        # we remove bin logs o save space!
        command = "RESET MASTER"
        c.execute(command)

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
        import MySQLdb
        db =   MySQLdb.connect(host="localhost",
                 user=self._db_user_name, passwd=self._db_user_pass)

        c = db.cursor()

        cmd = "CREATE DATABASE %s" % self._db_name
        c.execute(cmd)
        logging.info("Database created")

        cmd = "SET GLOBAL innodb_file_per_table=1"
        c.execute(cmd)
        cmd = "SET GLOBAL innodb_file_format=Barracuda"
        c.execute(cmd)
        cmd = "SET GLOBAL autocommit=0"
        c.execute(cmd)
        db.close()

    def _get_connection(self):
        import MySQLdb
        db =   MySQLdb.connect(host="localhost",
                 user=self._db_user_name, passwd=self._db_user_pass,
                  db=self._db_name)
        return db

    def run(self):

        db = None
        do_run = True
        try:
            if self._erase_old_db:
                self._delete_my_sql_db()
                self._create_mysql_db()

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
                    do_run = False
                    try:
                        logging.error("Failed to run mysql command:\n%s" % command)
                    except:
                        logging.error("Did not retrieve queue value")

                finally:
                    if self._queue.empty():
                        #we sleep iff we have an empty queue. this way, we don't over use a cpu
                        time.sleep(.1)

        except KeyboardInterrupt as e:
            logging.warning("DB async process interrupted with KeyboardInterrupt")
            raise e

        except Exception as e:
            logging.error("DB async process stopped with an exception")
            raise e

        finally:
            logging.info("Closing async mysql writer")
            while not self._queue.empty():
                self._queue.get()

            self._queue.close()
            if db is not None:
                db.close()

class ImgToMySQLHelper(object):
    _table_name = "IMG_SNAPSHOTS"
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

        cv2.imwrite(self._tmp_file, img, [int(cv2.IMWRITE_JPEG_QUALITY), 50])

        bstring = open(self._tmp_file, "rb").read()
        cmd = 'INSERT INTO ' + self._table_name + '(id,t,img) VALUES(%s,%s,%s)'

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
            if i not in self._activity_accum.keys():
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

        out = [self._make_sql_command(v) for v in out.values()]

        return out

class ResultWriter(object):
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _async_writing_class = AsyncMySQLWriter
    _null = 0
    def __init__(self, db_credentials, rois, metadata=None, make_dam_like_table=True, take_frame_shots=False, erase_old_db=True, *args, **kwargs):
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

        self._var_map_initialised = False
        if erase_old_db:
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
            self._create_table("IMG_SNAPSHOTS", "id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY , t INT, img LONGBLOB")


        logging.info("Creating 'CSV_DAM_ACTIVITY' table")
        if self._dam_file_helper is not None:
            fields = self._dam_file_helper.make_dam_file_sql_fields()
            self._create_table("CSV_DAM_ACTIVITY", fields)


        logging.info("Creating 'METADATA' table")
        self._create_table("METADATA", "field CHAR(100), value VARCHAR(3000)")

        logging.info("Creating 'START_EVENTS' table")
        self._create_table("START_EVENTS", "id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY, t INT, event CHAR(100)")
        event = "graceful_start"
        command = "INSERT INTO START_EVENTS VALUES %s" % str((self._null, int(time.time()), event))
        self._write_async_command(command)


        for k,v in self.metadata.items():
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
        if self._dam_file_helper is not None:
            out = self._dam_file_helper.flush(t)
            for c in out:
                self._write_async_command(c)

        if self._shot_saver is not None and img is not None:
            c_args = self._shot_saver.flush(t, img)
            if c_args is not None:
                self._write_async_command(*c_args)

        for k, v in self._insert_dict.items():
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

        for dt in data_row.values():
            command = "INSERT INTO VAR_MAP VALUES %s"% str((dt.header_name, dt.sql_data_type, dt.functional_type))
            self._write_async_command(command)
        self._var_map_initialised = True



    def _initialise(self, roi, data_row):
        # We make a new dir to store results
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY" ,"t INT"]
        for dt in data_row.values():
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))
        fields = ", ".join(fields)
        table_name = "ROI_%i" % roi.idx
        self._create_table(table_name, fields)


    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.info("Closing result writer...")
        for k, v in self._insert_dict.items():
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
            logging.error(traceback.format_exc(e))
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
        if not self._async_writer.is_alive():
            raise Exception("Async database writer has stopped unexpectedly")
        self._queue.put((command, args))

    def _create_table(self, name, fields, engine="InnoDB"):
        command = "CREATE TABLE IF NOT EXISTS %s (%s) ENGINE %s KEY_BLOCK_SIZE=16" % (name, fields, engine)
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
            for k,v in self._pragmas.items():
                command = "PRAGMA %s = %s" %(str(k), str(v))
                c.execute(command)

        
    def _get_connection(self):
        import sqlite3
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
                        #we sleep iff we have an empty queue. this way, we don't over use a cpu
                        time.sleep(.1)

        except KeyboardInterrupt as e:
            logging.warning("DB async process interrupted with KeyboardInterrupt")
            raise e

        except Exception as e:
            logging.error("DB async process stopped with an exception")
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
