from test.test_set import cube

__author__ = 'quentin'

# from pysolovideo.utils.debug import PSVException
import time, datetime
import traceback
import os
import logging
import sqlite3
import MySQLdb
import multiprocessing

_MYSQL_DB_NAME = "psv_db"

def _delete_my_sql_db():

    db_name = _MYSQL_DB_NAME
    try:
        db =   MySQLdb.connect(host="localhost",
             user="psv", passwd="psv", db=db_name)
    except MySQLdb.OperationalError:
        logging.warning("Database does not exist. Cannot delete it")
        return

    logging.info("connecting to mysql db")
    c = db.cursor()
    #Truncate all tables before dropping db for performance
    command = "SHOW TABLES"
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
    command = "DROP DATABASE IF EXISTS %s" %db_name
    c.execute(command)
    db.commit()
    db.close()


def _create_mysql_db():
    db_name = _MYSQL_DB_NAME
    db =   MySQLdb.connect(host="localhost",
             user="psv", passwd="psv")

    c = db.cursor()

    cmd = "CREATE DATABASE %s" % db_name
    c.execute(cmd)
    logging.info("Database created")

    cmd = "SET GLOBAL innodb_file_per_table=1"
    c.execute(cmd)
    cmd = "SET GLOBAL innodb_file_format=Barracuda"
    c.execute(cmd)
    cmd = "SET GLOBAL autocommit=0"
    c.execute(cmd)
    db.close()




def async_mysql_writer(queue):

    _delete_my_sql_db()
    _create_mysql_db()

    db =   MySQLdb.connect(host="localhost",
                 user="psv", passwd="psv",
                  db=_MYSQL_DB_NAME)
    run = True
    try:
        while run:
            try:
                msg = queue.get()
                if (msg == 'DONE'):
                    run=False
                    continue
                c = db.cursor()
                c.execute(msg)
                db.commit()
            except:
                run=False
                try:
                    logging.error("Failed to run mysql command:\n%s" % msg)
                except:
                    logging.error("Did not retrieve queue value")

            finally:
                if queue.empty():
                    #we sleep iff we have an empty queue. this way, we don't over use a cpu
                    time.sleep(.1)



    except KeyboardInterrupt:
        logging.warning("MySQL async process interupted with KeyboardInterrupt")
    except:
        logging.error("MySQL async process stopped with an exception")

    finally:
        logging.info("Closing async mysql writer")
        queue.close()
        db.close()





class AsyncMySQLWriter(object):
    def __init__(self):
        self._queue = multiprocessing.JoinableQueue()
        self._mysql_writer = multiprocessing.Process(target=async_mysql_writer, args=((self._queue),))
        self._mysql_writer.start()
    def write_command(self, command):
        self._queue.put(command)

    def close(self):
        logging.info("Closing mysql async queue")
        self._queue.put("DONE")
        logging.info("Freeing queue")
        self._queue.cancel_join_thread()
        logging.info("Joining thread")
        self._mysql_writer.join()
        logging.info("Joined OK")


#

class ResultWriter(object):
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _dam_file_period = 60 # Get activity for every N s of data


    def _write_async_command(self, command):
        self._async_writer.write_command(command)

    def _create_table(self, name, fields, engine="MyISAM"):
        command = "CREATE TABLE %s (%s) ENGINE %s KEY_BLOCK_SIZE=16" % (name, fields, engine)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)


    def __init__(self, dummy_db_name, rois, metadata=None, make_dam_like_table=True, *args, **kwargs):
        self._async_writer = AsyncMySQLWriter()
        self._last_t, self._last_flush_t, self._last_dam_t = [0] * 3

        self.metadata = metadata
        self._rois = rois
        self._make_dam_like_table = make_dam_like_table

        self._insert_dict = {}
        if self.metadata is None:
            self.metadata  = {}

        self._var_map_initialised = False

        logging.info("Creating master table 'ROI_MAP'")
        self._create_table("ROI_MAP", "roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT")

        for r in self._rois:
            fd = r.get_feature_dict()
            command = "INSERT INTO ROI_MAP VALUES %s" % str((fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))
            self._write_async_command(command)


        logging.info("Creating variable map table 'VAR_MAP'")
        self._create_table("VAR_MAP", "var_name CHAR(100), sql_type CHAR(100), functional_type CHAR(100)")

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
            self._create_table("CSV_DAM_ACTIVITY", fields)
            self._dam_history_dic = {}
            for r in rois:
                self._dam_history_dic[r.idx] = {"last_pos":None,
                                                "cummul_dist":0
                                                }

        logging.info("Creating 'METADATA' table")
        self._create_table("METADATA", "field CHAR(100), value CHAR(200)")

        for k,v in self.metadata.items():
            command = "INSERT INTO METADATA VALUES %s" % str((k, v))
            self._write_async_command(command)
        logging.info("Result writer initialised")


    def write(self, t, roi, data_row):
        if not self._var_map_initialised:
            for r in self._rois:
                self._initialise(r, data_row)
            self._initialise_var_map(data_row)

        self._add(t, roi, data_row)
        self._last_t = t

    def flush(self):
        for k, v in self._insert_dict.iteritems():
            if len(v) > self._max_insert_string_len:
                self._write_async_command(v)
                self._insert_dict[k] = ""
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
        logging.info("Closing result writer")
        self._async_writer.close()

    def close(self):
        pass


#TODO add HIGH_PRIORITY to inserts!
class ResultDBWriterBase(object):
    # _flush_every_ns = 30 # flush every 10s of data
    _max_insert_string_len = 1000
    _dam_file_period = 60 # Get activity for every N s of data

    def _create_table(self,  name, fields):
        raise NotImplementedError()

    def __init__(self,  rois, metadata=None, make_dam_like_table=True, *args, **kwargs):
        self._last_t, self._last_flush_t, self._last_dam_t = [0] * 3

        self.metadata = metadata
        self._rois = rois
        self._make_dam_like_table = make_dam_like_table

        self._insert_dict = {}
        if self.metadata is None:
            self.metadata  = {}

        self._clean_up()
        self._var_map_initialised = False

        logging.info("Creating master table 'ROI_MAP'")
        self._create_table("ROI_MAP", "roi_idx SMALLINT, roi_value SMALLINT, x SMALLINT,y SMALLINT,w SMALLINT,h SMALLINT")

        for r in self._rois:
            fd = r.get_feature_dict()
            command = "INSERT INTO ROI_MAP VALUES %s" % str((fd["idx"], fd["value"], fd["x"], fd["y"], fd["w"], fd["h"]))
            self._write_async_command(command)


        logging.info("Creating variable map table 'VAR_MAP'")
        self._create_table("VAR_MAP", "var_name CHAR(100), sql_type CHAR(100), functional_type CHAR(100)")

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
            self._create_table("CSV_DAM_ACTIVITY", fields)
            self._dam_history_dic = {}
            for r in rois:
                self._dam_history_dic[r.idx] = {"last_pos":None,
                                                "cummul_dist":0
                                                }

        logging.info("Creating 'METADATA' table")
        self._create_table("METADATA", "field CHAR(100), value CHAR(200)")

        for k,v in self.metadata.items():
            command = "INSERT INTO METADATA VALUES %s" % str((k, v))
            self._write_async_command(command)
        logging.info("Result writer initialised")



    def _clean_up(self, *args, **kwargs):
        raise NotImplementedError()
    def _get_connection(self, *args, **kwargs):
        raise NotImplementedError()
    def _write_async_command(self, command):
        raise NotImplementedError()
    def write(self, t, roi, data_row):
        # if self._make_dam_like_table:
        #     current_pos =  data_row["x"] + 1j*data_row["y"]
        #     if self._dam_history_dic[roi.idx]["last_pos"] is not None:
        #         dist = abs(current_pos - self._dam_history_dic[roi.idx]["last_pos"] )
        #         dist /= roi.longest_axis
        #         self._dam_history_dic[roi.idx]["cummul_dist"] += dist
        #     self._dam_history_dic[roi.idx]["last_pos"] = current_pos

        if not self._var_map_initialised:
            for r in self._rois:
                self._initialise(r, data_row)
            self._initialise_var_map(data_row)

        self._add(t, roi, data_row)
        self._last_t = t

    # def _update_dam_table(self):
    #
    #     dt = datetime.datetime.fromtimestamp(int(time.time()))
    #     date_time_fields = dt.strftime("%d,%b,%Y,%H:%M:%S").split(",")
    #     values = [0] + date_time_fields
    #
    #
    #     for i in range(7):
    #         values.append(str(i))
    #     for r in self._rois:
    #         values.append(self._dam_history_dic[r.idx]["cummul_dist"])
    #
    #     command = '''INSERT INTO CSV_DAM_ACTIVITY VALUES %s''' % str(tuple(values))
    #
    #     self._write_async_command(command)
    #     for r in self._rois:
    #         self._dam_history_dic[r.idx]["cummul_dist"] = 0

    def flush(self):
        # if self._make_dam_like_table:
        #     if (self._last_t - self._last_dam_t) > (self._dam_file_period * 1000):
        #         self._last_dam_t =  self._last_t
        #         self._update_dam_table()



        for k, v in self._insert_dict.iteritems():
            if len(v) > self._max_insert_string_len:
                self._write_async_command(v)
                self._insert_dict[k] = ""


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
        logging.info("Closing result writer")

    def close(self):
        pass



class ResultWriterBak(ResultDBWriterBase):

    _flush_every_ns = 10 # flush every 10s of data
    _db_name = _MYSQL_DB_NAME

    def __init__(self, db_name, *args, **kwargs):
        self._async_writer = AsyncMySQLWriter()
        super(ResultWriter, self).__init__(*args, **kwargs)



    def _write_async_command(self, command):
        self._async_writer.write_command(command)




    # def _clean_up(self):
    #
    #     c.execute(command)
    #     cn.close()

    def _create_table(self, name, fields, engine="MyISAM"):
        command = "CREATE TABLE %s (%s) ENGINE %s KEY_BLOCK_SIZE=16" % (name, fields, engine)
        logging.info("Creating database table with: " + command)
        self._write_async_command(command)



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




