__author__ = 'quentin'

# from pysolovideo.utils.debug import PSVException
import os
import logging
import sqlite3

#
class ResultWriter(object):

    def __init__(self, path,  metadata=None):
        self._path = path
        self.metadata = metadata
        if self.metadata is None:
            self.metadata  = {}
        self._initialised = set()
        try :
            os.remove(path)
        except:
            pass
        logging.info("Connecting to local database")
        self._conn = sqlite3.connect(path, check_same_thread=False)
        logging.info("Creating master table 'ROI_MAP'")
        command = "CREATE TABLE ROI_MAP (roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT)"
        c = self._conn.cursor()
        c.execute(command)
    @property
    def path(self):
        return self._path

    def write(self, t, roi, data_row):
        if roi.idx not in self._initialised:
            self._initialise(roi, data_row)
        self._add(t, roi, data_row)

    def flush(self):
        self._conn.commit()

    def _add(self,t, roi, data_row):
        # We make a new dir to store results
        fields = [t]


        for dt in data_row.values():
            val = dt
            if isinstance(val, bool):
                val = int(val)
            fields.append(val)

        tp = tuple(fields)
        command = '''INSERT INTO ROI_%i VALUES %s''' % (roi.idx, tp)
        c = self._conn.cursor()
        c.execute(command)


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
        c = self._conn.cursor()
        c.execute(command)

    def __del__(self):
        self._conn.close()
