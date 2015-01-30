# #import csv
# __author__ = 'quentin'
#
from pysolovideo.utils.debug import PSVException
import gzip
import os
import json
import csv
import logging

#
class ResultWriter(object):
    def __init__(self, dir_path, use_compression=True, chunk_size= 60*30, metadata=None):


        self.metadata = metadata

        self._dir_path = dir_path
        self._last_file_stamp = 0
        self._header = None
        self._chunk_size = chunk_size

        if self.metadata is None:
            self.metadata  = {}


        # We make a new dir to store results
        os.makedirs(self._dir_path)

        self._current_file = None
        self._file_list = []
        self._new_file(self._last_file_stamp)


    def __del__(self):
        try:
            self._current_file.close()
        except:
            pass

    @property
    def header(self):
        return self._header

    @property
    def file_list(self):
        return self._file_list


    def set_header(self, header):
        self._header = header
        metadata_string = json.dumps(self.metadata)
        metadata_string = metadata_string .replace("\n", "")
        metadata_string = metadata_string .replace("\r", "")

        logging.info("Setting metadata %s" % metadata_string)

        self._current_file.write("#" + metadata_string + "\n")
        self._csv_writer.writerow(self._header)




    def _new_file(self, t):
        if self._current_file is not None:
            self._current_file.close()

        basename = "chunk_%08d.csv.gz" % len(self._file_list)

        path = os.path.join(self._dir_path,basename)

        logging.info("Making a ne result chunk at %s" % path)

        file = gzip.open(path,"w")
        self._current_file=file

        if len(self._file_list) > 0:
            self._file_list[-1]["end"] = t


        self._file_list.append({"start":t, "end":None, "path": path})
        self._csv_writer  = csv.writer(file , quoting=csv.QUOTE_NONE)




    def write_row(self, t, row_dict):
        if self._header is None:
            raise PSVException("File writer headers have not been set")

        if t - self._file_list[-1]["start"] >= self._chunk_size:
            self._new_file(t)


        row = []
        for f in self._header:
            dt = row_dict[f]
            if isinstance(dt,float):
                if dt == 0:
                    dt = 0
                elif dt < 1:
                    dt ="%.2e" % dt
                else:
                    dt ="%.2f" % dt

            elif isinstance(dt, bool):
                dt = int(dt)

            row.append(dt)

        self._csv_writer.writerow(row)

