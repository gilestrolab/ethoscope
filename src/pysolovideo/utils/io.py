__author__ = 'quentin'

# from pysolovideo.utils.debug import PSVException
import os
import logging
import sqlite3

#
class ResultWriter(object):
    _sqlite_basename = "psv_result.db"

    def __init__(self, dir_path,  metadata=None):

        self._last_t, self._last_flush_t = 0, 0

        self._path = os.path.join(dir_path, self._sqlite_basename)

        self.metadata = metadata
        if self.metadata is None:
            self.metadata  = {}
        self._initialised = set()
        self._var_map_initialised = False
        try :
            os.remove(self._path )
        except:
            pass
        logging.info("Connecting to local database:")
        logging.info(self._path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        c = self._conn.cursor()
        logging.info("Creating master table 'ROI_MAP'")
        command = "CREATE TABLE ROI_MAP (roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT)"
        c.execute(command)

        logging.info("Creating variable map table 'VAR_MAP'")
        command = "CREATE TABLE VAR_MAP (var_name CHAR(100), sql_type CHAR(100), functional_type CHAR(100))"
        c.execute(command)

        logging.info("Creating 'METADATA' table")
        command = "CREATE TABLE METADATA (field CHAR(100), value CHAR(200))"
        c.execute(command)
        for k,v in metadata.items():
            command = "INSERT INTO METADATA VALUES %s" % str((k, v))
            c.execute(command)
        logging.info("Result writer initialised")
    @property
    def path(self):
        return self._path

    def write(self, t, roi, data_row):
        self._last_t = t
        if not self._var_map_initialised:
            self._initialise_var_map(data_row)
        if roi.idx not in self._initialised:
            self._initialise(roi, data_row)
        self._add(t, roi, data_row)

    def flush(self):
        if (self._last_t - self._last_flush_t) < 10 * 1000:
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
        fields = ["t INT PRIMARY KEY"]

        for dt in data_row.values():
            fields.append("%s %s" % (dt.header_name, dt.sql_data_type))

        fields = ", ".join(fields)

        self._initialised |= {roi.idx}

        command = "CREATE TABLE ROI_%i (%s)" % (roi.idx, fields)

        c = self._conn.cursor()
        c.execute(command)
        fd = roi.get_feature_dict()
        command = "INSERT INTO ROI_MAP VALUES %s" % str((fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))
        c = self._conn.cursor()
        c.execute(command)

    def __del__(self):
        self.flush()
        self._conn.close()
