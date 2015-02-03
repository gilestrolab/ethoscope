# #import csv
# __author__ = 'quentin'
#
from pysolovideo.utils.debug import PSVException
import gzip
import os
import json
import csv
import logging
import sqlite3

#
class ResultWriter(object):
    db_name = "psv_result.db"
    def __init__(self, dir_path,  metadata=None):
        self.metadata = metadata
        self._dir_path = dir_path
        if self.metadata is None:
            self.metadata  = {}
        self._initialised = set()
        os.makedirs(self._dir_path)
        db_path = os.path.join(self._dir_path, self.db_name)

        try :
            os.remove(db_path)
        except:
            pass
        self._conn = sqlite3.connect(db_path)
        command = "CREATE TABLE ROI_MAP (roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT)"
        c = self._conn.cursor()
        c.execute(command)

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
        # try:
        #
        # except:
        #     pass

    # @property
    # def header(self):
    #     return self._header
    #
    # @property
    # def file_list(self):
    #     return self._file_list
    #
    #
    # def set_header(self, header):
    #     self._header = header
    #     metadata_string = json.dumps(self.metadata)
    #     metadata_string = metadata_string .replace("\n", "")
    #     metadata_string = metadata_string .replace("\r", "")
    #
    #     logging.info("Setting metadata %s" % metadata_string)
    #
    #     self._current_file.write("#" + metadata_string + "\n")
    #     self._csv_writer.writerow(self._header)
    #
    #
    #
    #
    # def _new_file(self, t):
    #     if self._current_file is not None:
    #         self._current_file.close()
    #     if self._chunk_size > 0 : # negative chunck size means a single chunk
    #         basename = "chunk_%08d.csv.gz" % len(self._file_list)
    #     else:
    #         basename = "result.csv.gz"
    #
    #     path = os.path.join(self._dir_path,basename)
    #
    #     logging.info("Making a ne result chunk at %s" % path)
    #
    #     file = gzip.open(path,"w")
    #     self._current_file=file
    #
    #     if len(self._file_list) > 0:
    #         self._file_list[-1]["end"] = t
    #
    #
    #     self._file_list.append({"start":t, "end":None, "path": path})
    #     self._csv_writer  = csv.writer(file , quoting=csv.QUOTE_NONE)
    #
    #
    #
    #
    # def write_row(self, t, row_dict):
    #     if self._header is None:
    #         raise PSVException("File writer headers have not been set")
    #
    #     if self._chunk_size > 0 : # negative chunck size means a single chunk
    #         if t - self._file_list[-1]["start"] >= self._chunk_size:
    #             self._new_file(t)
    #
    #
    #     row = []
    #     for f in self._header:
    #         dt = row_dict[f]
    #         if isinstance(dt,float):
    #             if dt == 0:
    #                 dt = 0
    #             elif dt < 1:
    #                 dt ="%.2e" % dt
    #             else:
    #                 dt ="%.2f" % dt
    #
    #         elif isinstance(dt, bool):
    #             dt = int(dt)
    #
    #         row.append(dt)
    #
    #     self._csv_writer.writerow(row)
    #
