from test.test_set import cube

__author__ = 'quentin'

# from pysolovideo.utils.debug import PSVException
import time, datetime
import os
import logging
import sqlite3
import MySQLdb


#
#TODO add HIGH_PRIORITY to inserts!
class ResultDBWriterBase(object):
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _dam_file_period = 60 # Get activity for every N s of data

    def _create_table(self, cursor, name, fields):
        raise NotImplementedError()

    def __init__(self,  rois, metadata=None, make_dam_like_table=True, *args, **kwargs):
        self._last_t, self._last_flush_t, self._last_dam_t = [0] * 3

        self.metadata = metadata
        self._rois = rois
        self._make_dam_like_table = make_dam_like_table
        self._conn = None
        self._insert_dict = {}
        if self.metadata is None:
            self.metadata  = {}

        self._clean_up()
        self._conn = self._get_connection()
        c = self._conn.cursor()
        self._var_map_initialised = False

        logging.info("Creating master table 'ROI_MAP'")
        self._create_table(c, "ROI_MAP", "roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT")

        for r in self._rois:
            fd = r.get_feature_dict()
            command = "INSERT INTO ROI_MAP VALUES %s" % str((fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))
            c.execute(command)


        logging.info("Creating variable map table 'VAR_MAP'")
        self._create_table(c, "VAR_MAP", "var_name CHAR(100), sql_type CHAR(100), functional_type CHAR(100)")

        if self._make_dam_like_table:
            fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY",
                      "day CHAR(100)",
                      "month CHAR(100)",
                      "year CHAR(100)",
                      "time CHAR(100)"]

            for i in range(7):
                fields.append("DUMMY_FIELD_%d SMALLINT" % i)
            for r in rois:
                fields.append("ROI_%d FLOAT(8,5)" % r.idx)
            logging.info("Creating 'CSV_DAM_ACTIVITY' table")
            fields = ",".join(fields)
            self._create_table(c,"CSV_DAM_ACTIVITY", fields)
            self._dam_history_dic = {}
            for r in rois:
                self._dam_history_dic[r.idx] = {"last_pos":None,
                                                "cummul_dist":0
                                                }

        logging.info("Creating 'METADATA' table")
        self._create_table(c,"METADATA", "field CHAR(100), value CHAR(200)")

        for k,v in self.metadata.items():
            command = "INSERT INTO METADATA VALUES %s" % str((k, v))
            c.execute(command)
        logging.info("Result writer initialised")


    def _clean_up(self, *args, **kwargs):
        raise NotImplementedError()
    def _get_connection(self, *args, **kwargs):
        raise NotImplementedError()

    def write(self, t, roi, data_row):
        if self._make_dam_like_table:
            current_pos =  data_row["x"] + 1j*data_row["y"]

            if self._dam_history_dic[roi.idx]["last_pos"] is not None:
                dist = abs(current_pos - self._dam_history_dic[roi.idx]["last_pos"] )
                dist /= roi.longest_axis
                self._dam_history_dic[roi.idx]["cummul_dist"] += dist
            self._dam_history_dic[roi.idx]["last_pos"] = current_pos


        self._last_t = t
        if not self._var_map_initialised:
            for r in self._rois:
                self._initialise(r, data_row)
            self._initialise_var_map(data_row)

        self._add(t, roi, data_row)

    def _update_dam_table(self):
        return

        dt = datetime.datetime.fromtimestamp(int(time.time()))
        date_time_fields = dt.strftime("%d,%b,%Y,%H:%M:%S").split(",")
        values = [0] + date_time_fields


        for i in range(7):
            values.append(str(i))
        for r in self._rois:
            values.append(self._dam_history_dic[r.idx]["cummul_dist"])

        command = '''INSERT INTO CSV_DAM_ACTIVITY VALUES %s''' % str(tuple(values))

        c = self._conn.cursor()

        c.execute(command)
        for r in self._rois:
            self._dam_history_dic[r.idx]["cummul_dist"] = 0

    def flush(self):
        if self._make_dam_like_table and (self._last_t - self._last_dam_t) > (self._dam_file_period * 1000):
            self._last_dam_t =  self._last_t
            self._update_dam_table()


        # if (self._last_t - self._last_flush_t) < (self._flush_every_ns ):
        #     return
        c = self._conn.cursor()
        to_commit = False
        for k, v in self._insert_dict.iteritems():
            if len(v) > self._max_insert_string_len:
                to_commit = True
                c.execute(v)

                self._insert_dict[k] = ""

        self._last_flush_t =  self._last_t

        if to_commit:
            self._conn.commit()
            return True

        return False

    def _add(self,t, roi, data_row):

        roi_id = roi.idx
        tp = (0, t) + tuple(data_row.values())

        if roi_id not in self._insert_dict  or self._insert_dict[roi_id] == "":
            command = 'INSERT INTO ROI_%i VALUES %s' % (roi_id, str(tp))
            self._insert_dict[roi_id] = command
        else:
            self._insert_dict[roi_id] += ("," + str(tp))


    def _initialise_var_map(self,  data_row):
        logging.info("Filling 'VAR_MAP' with values")
        c = self._conn.cursor()
        for dt in data_row.values():
            command = "INSERT INTO VAR_MAP VALUES %s"% str((dt.header_name, dt.sql_data_type, dt.functional_type))
            c.execute(command)
        self._var_map_initialised = True


    def _initialise(self, roi, data_row):
        # We make a new dir to store results
        fields = ["id INT  NOT NULL AUTO_INCREMENT PRIMARY KEY" ,"t INT"]
        for dt in data_row.values():
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))
        fields = ", ".join(fields)
        c = self._conn.cursor()
        table_name = "ROI_%i" % roi.idx
        self._create_table(c, table_name, fields)


    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logging.info("Closing result writer")
        self._conn.commit()
        if self._conn is not None:
            self._conn.close()
    def close(self):
        pass



class ResultWriter(ResultDBWriterBase):

    _flush_every_ns = 10 # flush every 10s of data

    def __init__(self, db_name, *args, **kwargs):
        self._db_name = db_name
        super(ResultWriter, self).__init__(*args, **kwargs)

    def _get_connection(self):
        try:
            db =   MySQLdb.connect(host="localhost",
                     user="psv", passwd="psv",
                      db=self._db_name)
        except MySQLdb.OperationalError:
            logging.warning("Database does not seem to exist. Creating it")
            db =   MySQLdb.connect(host="localhost",
                     user="psv", passwd="psv")

            c = db.cursor()
            cmd = "RESET MASTER"
            logging.info("Removing binary log")
            c.execute(cmd)
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

            db = self._get_connection()
        return  db

    def _clean_up(self):
        logging.info("connecting to mysql db")

        cn = self._get_connection()

        logging.info("Setting up cursor")
        c = cn.cursor()


        #Truncate all tables before dropping db for performance
        command = "SHOW TABLES"
        c.execute(command)

        # to_truncate = ["RENAME TABLE %s"% t
        to_execute  = []
        for t in c:
            t = t[0]
            command = "TRUNCATE TABLE %s" % t
            to_execute.append(command)
            # to_execute.append("RENAME TABLE %s TO OLD_%s, TMP_%s TO %s" % (t,t,t,t))
            # to_execute.append("DROP TABLE OLD_%s" % t)
        logging.info("Truncating all database tables")
        # import multiprocessing
        # multiprocessing.Pool(1)
        for te in to_execute:
            c.execute(te)
        cn.commit()

        logging.info("Dropping entire database")
        command = "DROP DATABASE IF EXISTS %s" % self._db_name
        c.execute(command)
        cn.close()

    def _create_table(self, cursor, name, fields, engine="MyISAM"):
        command = "CREATE TABLE %s (%s) ENGINE %s KEY_BLOCK_SIZE=16" % (name, fields, engine)
        logging.info("Creating database table with: " + command)
        cursor.execute(command)


class SQLiteResultWriter(ResultDBWriterBase):
    _sqlite_basename = "psv_result.db"

    _pragmas = {"temp_store": "MEMORY",
    "journal_mode": "OFF",
    "locking_mode":  "EXCLUSIVE"}

    def __init__(self, dir_path, *args, **kwargs):
        self._path = os.path.join(dir_path, self._sqlite_basename)
        super(SQLiteResultWriter, self).__init__(*args, **kwargs)

        c = self._conn.cursor()
        logging.info("Setting DB parameters'")
        for k,v in self._pragmas.items():
            command = "PRAGMA %s = %s" %(str(k), str(v))
            c.execute(command)

    def _clean_up(self):
        try :
            os.remove(self._path)
        except:
            pass

    def _get_connection(self):
        conn = sqlite3.connect(self._path, check_same_thread=False)
        return conn
    def _create_table(self, cursor, name, fields):
        command = "CREATE TABLE %s (%s)" % (name, fields)
        cursor.execute(command)




