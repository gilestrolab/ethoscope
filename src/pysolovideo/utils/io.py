__author__ = 'quentin'

# from pysolovideo.utils.debug import PSVException
import os
import logging
import sqlite3
import MySQLdb


#

class ResultDBWriterBase(object):
    _flush_every_ns = 10 # flush every 10s of data

    def __init__(self,  metadata=None, *args, **kwargs):
        self._last_t, self._last_flush_t = 0, 0
        self.metadata = metadata
        if self.metadata is None:
            self.metadata  = {}

        self._clean_up()
        self._conn = self._get_connection()
        c = self._conn.cursor()

        self._initialised = set()
        self._var_map_initialised = False

        logging.info("Creating master table 'ROI_MAP'")

        command = "CREATE TABLE ROI_MAP (roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT)"
        c.execute(command)


        logging.info("Creating variable map table 'VAR_MAP'")
        command = "CREATE TABLE VAR_MAP (var_name CHAR(100), sql_type CHAR(100), functional_type CHAR(100))"
        c.execute(command)

        logging.info("Creating 'METADATA' table")
        command = "CREATE TABLE METADATA (field CHAR(100), value CHAR(200))"
        c.execute(command)
        for k,v in self.metadata.items():
            command = "INSERT INTO METADATA VALUES %s" % str((k, v))
            c.execute(command)
        logging.info("Result writer initialised")


    def _clean_up(self, *args, **kwargs):
        raise NotImplementedError()
    def _get_connection(self, *args, **kwargs):
        raise NotImplementedError()

    def write(self, t, roi, data_row):
        self._last_t = t
        if not self._var_map_initialised:
            self._initialise_var_map(data_row)
        if roi.idx not in self._initialised:
            self._initialise(roi, data_row)
        self._add(t, roi, data_row)

    def flush(self):
        if (self._last_t - self._last_flush_t) < self._flush_every_ns * 1000:
            return
        self._conn.commit()
        self._last_flush_t =  self._last_t


    def _add(self,t, roi, data_row):
        tp = (t,) + tuple(data_row.values())
        command = '''INSERT INTO ROI_%i VALUES %s''' % (roi.idx, tp)
        c = self._conn.cursor()
        c.execute(command)


    def _initialise_var_map(self,  data_row):
        logging.info("Filling 'VAR_MAP' with values")
        c = self._conn.cursor()
        for dt in data_row.values():
            command = "INSERT INTO VAR_MAP VALUES %s"% str((dt.header_name, dt.sql_data_type, dt.functional_type))
            c.execute(command)
        self._var_map_initialised = True


    def _initialise(self, roi, data_row):
        # We make a new dir to store results
        fields = ["t INT"]

        for dt in data_row.values():
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))

        fields = ", ".join(fields)

        self._initialised |= {roi.idx}

        command = "CREATE TABLE ROI_%i (%s)" % (roi.idx, fields)

        c = self._conn.cursor()
        c.execute(command)
        fd = roi.get_feature_dict()
        command = "INSERT INTO ROI_MAP VALUES %s" % str((fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))

        c.execute(command)

    def __del__(self):
        self.close()
    def close(self):
        self.flush()
        self._conn.commit()
        self._conn.close()


class ResultWriter(ResultDBWriterBase):

    _flush_every_ns = 10 # flush every 10s of data

    def __init__(self, db_name, *args, **kwargs):
        self._db_name = db_name
        super(ResultWriter, self).__init__(*args, **kwargs)



    def _get_connection(self):

        return  MySQLdb.connect(host="localhost",
                     user="root",
                      passwd="",
                      db=self._db_name)

    def _clean_up(self):
        logging.info("connecting to mysql db")
        cn = MySQLdb.connect(host="localhost",
                     user="root",
                      passwd="")
        logging.info("Settign up cursor")
        c = cn.cursor()
        command = "DROP DATABASE IF EXISTS %s" % self._db_name
        logging.info("Resetting DB")
        c.execute(command)

        command = "CREATE DATABASE %s" % self._db_name
        c.execute(command)
        logging.info("Cleaned up")
        cn.close()



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




