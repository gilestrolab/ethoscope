__author__ = 'quentin'



import MySQLdb
import sqlite3
import os
import logging


class DBNotReadyError(Exception):
    pass

class MySQLdbToSQlite(object):
    _max_n_rows_to_insert = 1000

    def     __init__(self, dst_path, remote_db_name="psv_db", remote_host="localhost", remote_user="root", remote_pass="", overwrite=True):
        """
        A class to backup remote psv MySQL data base into a local sqlite3 one.
        The name of the static (not updated during run) and the dynamic tables is hardcoded.
        The `update_roi_tables` method will fetch only the new datapoint at each run.

        :param dst_path: where to save the data (expect a `.db` file)
        :param remote_db_name: the name of the remote database
        :param remote_host: the ip of the database
        :param remote_user: the user name for the remote database
        :param remote_pass: teh password for the remote database
        :param overwrite: whether the destination file should be overwritten. If False, data are appended to it


        """

        self._remote_host = remote_host
        self._remote_user = remote_user
        self._remote_pass = remote_pass
        self._remote_db_name = remote_db_name

        src = MySQLdb.connect(host=self._remote_host, user=self._remote_user,
                                         passwd=self._remote_pass, db=self._remote_db_name)


        self._dst_path=dst_path
        self._dst_dir = os.path.dirname(self._dst_path)

        logging.info("Initializing local database static tables at %s" % dst_path)
        # we remove file and create dir, if needed

        try:
            if overwrite:
                logging.info("Trying to remove old database")
                os.remove(self._dst_path)
                logging.info("Success")
        except OSError as e:
            logging.warning(e)
            pass
        try:
            logging.info("Making parent directories")
            os.makedirs(os.path.dirname(self._dst_path))
            logging.info("Success")
        except OSError as e:
            logging.warning(e)
            pass

        with sqlite3.connect(self._dst_path, check_same_thread=False) as conn:
            src_cur = src.cursor()

            command = "SELECT * FROM VAR_MAP"
            src_cur.execute(command)
            #empty var map means no reads are present yet
            if len([i for i in src_cur]) == 0:
                raise DBNotReadyError("No read are available for this database yet")

            command = "SHOW TABLES"
            src_cur.execute(command)
            tables = [c[0] for c in src_cur]
            for t in tables:
                self._copy_table(t, src, conn)

            #TODO checksum of ordered metadata ?
            logging.info("Database mirroring initialised")

    def update_roi_tables(self):
        """
        Fetch new ROI tables and new data points in the remote and use them to update local db

        :return:
        """
        src = MySQLdb.connect(host=self._remote_host, user=self._remote_user,
                                         passwd=self._remote_pass, db=self._remote_db_name)

        with sqlite3.connect(self._dst_path, check_same_thread=False) as dst:
            dst_cur = src.cursor()
            command = "SELECT roi_idx FROM ROI_MAP"
            dst_cur.execute(command)
            rois_in_src = set([c[0] for c in dst_cur])
            for i in rois_in_src :
                self._update_one_roi_table("ROI_%i" % i, src, dst)
            self._update_one_roi_table("CSV_DAM_ACTIVITY", src, dst, True)

    def _copy_table(self,table_name, src, dst):
        src_cur = src.cursor()
        dst_cur = dst.cursor()

        src_command = "SHOW COLUMNS FROM %s " % table_name

        src_cur.execute(src_command)
        col_list = []
        for c in src_cur:
             col_list.append(" ".join(c[0:2]))

        formated_cols_names = ", ".join(col_list)

        dst_command = "DROP TABLE IF EXISTS %s" % table_name
        dst_cur.execute(dst_command)
        dst_command = "CREATE TABLE %s (%s) " % (table_name ,formated_cols_names)
        dst_cur.execute(dst_command)

        src_command = "SELECT * FROM %s " % table_name

        src_cur.execute(src_command)

        to_insert = []
        i = 0
        for sc in src_cur:
            i+=1
            tp = tuple([str(v) for v in sc ])
            to_insert.append(str(tp))
            if len(to_insert) > self._max_n_rows_to_insert:
                value_string = ",".join(to_insert)
                dst_command = "INSERT INTO %s VALUES %s" % (table_name, value_string )
                dst_cur.execute(dst_command)
                dst.commit()
                to_insert = []

        if len(to_insert) > 0:
            value_string = ",".join(to_insert)
            dst_command = "INSERT INTO %s VALUES %s" % (table_name, value_string )
            dst_cur.execute(dst_command)
        dst.commit()


        #
        # for c in src_cur:
        #     tp = tuple([str(v) for v in c ])
        #
        #     dst_command = "INSERT INTO %s VALUES %s" % (table_name, tp)
        #     dst_cur.execute(dst_command)
        # dst.commit()

    def _update_one_roi_table(self, table_name, src, dst, dump_in_csv=None):

        src_cur = src.cursor()
        dst_cur = dst.cursor()

        try:
            dst_command= "SELECT id FROM %s ORDER BY id DESC LIMIT 1" % table_name
            dst_cur.execute(dst_command)
        except (sqlite3.OperationalError, MySQLdb.ProgrammingError):
            self._copy_table(table_name, src, dst)
            return

        last_t_in_dst = 0
        for c in dst_cur:
            last_t_in_dst = c[0]
        src_command = "SELECT * FROM %s WHERE id > %d" % (table_name, last_t_in_dst)
        src_cur.execute(src_command)



        to_insert = []
        i = 0
        for sc in src_cur:
            i+=1
            tp = tuple([str(v) for v in sc ])
            to_insert.append(str(tp))
            if len(to_insert) > self._max_n_rows_to_insert:
                value_string = ",".join(to_insert)
                dst_command = "INSERT INTO %s VALUES %s" % (table_name, value_string )
                dst_cur.execute(dst_command)
                dst.commit()
                to_insert = []

        if len(to_insert) > 0:
            value_string = ",".join(to_insert)
            dst_command = "INSERT INTO %s VALUES %s" % (table_name, value_string )
            dst_cur.execute(dst_command)
        dst.commit()


            # if dump_in_csv is not None:
            #     out_file = os.path.join(self._dst_dir, table_name + ".txt")
            #     with open(out_file,"a") as f:
            #         row = "\t".join(["{0}".format(val) for val in sc])
            #         f.write(row)
            #         f.write("\n")



