__author__ = 'quentin'

import mysql.connector
import sqlite3
import os
import logging
import traceback

from ethoscope.utils.io import SQL_CHARSET


class DBNotReadyError(Exception):
    pass

class MySQLdbToSQlite(object):
    _max_n_rows_to_insert = 10000

    def __init__(self,
                 dst_path,
                 remote_db_name="ethoscope_db",
                 remote_host="localhost",
                 remote_user="ethoscope",
                 remote_pass="ethoscope",
                 overwrite=False):
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

        src = mysql.connector.connect(host=self._remote_host,
                                      user=self._remote_user,
                                      passwd=self._remote_pass,
                                      db=self._remote_db_name,
                                      connect_timeout=45,
                                      buffered=True,
                                      charset=SQL_CHARSET,
                                      use_unicode=True)


        self._dst_path=dst_path
        logging.info("Initializing local database static tables at %s" % self._dst_path)

        self._dam_file_name = os.path.splitext(self._dst_path)[0] + ".txt"


        # we remove file and create dir, if needed

        if overwrite:
            logging.info("Trying to remove old database")
            try:
                os.remove(self._dst_path)
                logging.info("Success")
            except OSError as e:
                logging.warning(e)
                pass

            logging.info("Trying to remove old DAM file")

            try:
                os.remove(self._dam_file_name)
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

        with open(self._dam_file_name,"a"):
            logging.info("Ensuring DAM file exists at %s" % self._dam_file_name)
            pass

        with sqlite3.connect(self._dst_path, check_same_thread=False) as conn:
            src_cur = src.cursor(buffered=True)

            command = "SELECT * FROM VAR_MAP"
            src_cur.execute(command)
            #empty var map means no reads are present yet
            if len([i for i in src_cur]) == 0:
                raise DBNotReadyError("No read are available for this database yet")

            command = "SHOW TABLES"
            src_cur.execute(command)
            tables = [c[0] for c in src_cur]
            for t in tables:
                if t == "CSV_DAM_ACTIVITY":
                    self._copy_table(t, src, conn, dump_in_csv=True)
                else:
                    self._copy_table(t, src, conn, dump_in_csv=False)

            #TODO checksum of ordered metadata ?

        logging.info("Database mirroring initialised")

    def _copy_table(self,table_name, src, dst, dump_in_csv=False):
        src_cur = src.cursor(buffered=True)
        dst_cur = dst.cursor()

        src_command = "SHOW COLUMNS FROM %s " % table_name

        src_cur.execute(src_command)
        col_list = []
        for c in src_cur:
             col_list.append(" ".join(c[0:2]))

        formated_cols_names = ", ".join(col_list)


        try:
            dst_command = "CREATE TABLE %s (%s)" % (table_name ,formated_cols_names)
            dst_cur.execute(dst_command)

        except sqlite3.OperationalError:
            logging.debug("Table %s exists, not copying it" % table_name)
            return
            
        if table_name == "IMG_SNAPSHOTS":
            self._replace_img_snapshot_table(table_name, src, dst)
        else:
            self._replace_table(table_name, src, dst, dump_in_csv)

    def _get_remote_db_info(self):
        """
        """
        #fetches data about the size of the remote db ( remote_local_tables_dictionary )
        src = mysql.connector.connect(host=self._remote_host,
                                      user=self._remote_user,
                                      passwd=self._remote_pass,
                                      buffered=True,
                                      charset=SQL_CHARSET,
                                      use_unicode=True)

            
        src_cur = src.cursor(buffered=True)
        
        command = 'SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA LIKE "ETHOSCOPE%";'
        src_cur.execute(command)
        tables = src_cur.fetchall()
        
        remote_local_tables_dictionary = {dbn : {} for dbn in set([entry[0] for entry in tables])}
        
        for entry in tables: 
            db_name = entry[0]
            table_name = entry[1]
            
            if table_name not in ["ROI_MAP", "VAR_MAP", "METADATA"]:
                command = 'SELECT max(id) FROM %s.%s' % (db_name, table_name)
            else:
                command = 'SELECT count(*) from %s.%s' % (db_name, table_name)
            
            src_cur.execute(command)
            remote_local_tables_dictionary [db_name] . update ( { table_name :  src_cur.fetchone()[0] } )

        src.commit()
        src.close()
        
        return remote_local_tables_dictionary

    def _get_local_db_info(self):
        """
        """
        local_tables_dictionary = {}
        
        with sqlite3.connect(self._dst_path, check_same_thread=False) as dst:
            dst_cur = dst.cursor()
            command = 'SELECT name FROM sqlite_master WHERE type ="table" AND name NOT LIKE "sqlite_%";'
            dst_cur.execute(command)
            tables = dst_cur.fetchall()


            
            for entry in tables: 
                table_name = entry[0]
                
                if table_name not in ["ROI_MAP", "VAR_MAP", "METADATA"]:
                    command = 'SELECT max(id) FROM %s;' % table_name
                else:
                    command = 'SELECT count(*) from %s' % table_name
                
                dst_cur.execute(command)
                local_tables_dictionary . update ( { table_name :  dst_cur.fetchone()[0] } )            
            
        return local_tables_dictionary
        
    def compare_databases(self):
        """
        """
        total_remote = 0
        total_local = 0
        
        try:
            remote_tables_info = self._get_remote_db_info()
        except:
            logging.error("Problem getting info from the remote database")
        
        try:
            local_tables_info = self._get_local_db_info()
        except:
            logging.error("Problem getting info from the local database %s" % self._dst_path)
        
        try:
            for table in sorted(local_tables_info):
                l = local_tables_info[table]
                r = remote_tables_info[self._remote_db_name][table]
                
                if r == None : r = 0
                if l == None : l = 0
                
                total_remote += int(r)
                total_local += int(l)
                
                #print ("Transferred %s / %s for table %s (%0.2f)" % (l, r, table, l/r*100))
                
            return total_local/total_remote*100

        except:
            return -1

        
            
    def update_roi_tables(self):
        """
        Fetch new ROI tables and new data points in the remote and use them to update local db

        :return:
        """
        src = mysql.connector.connect(host=self._remote_host,
                                      user=self._remote_user,
                                      passwd=self._remote_pass,
                                      db=self._remote_db_name,
                                      buffered=True,
                                      charset=SQL_CHARSET,
                                      use_unicode=True)

        with sqlite3.connect(self._dst_path, check_same_thread=False) as dst:

            dst_cur = src.cursor()
            command = "SELECT roi_idx FROM ROI_MAP"
            dst_cur.execute(command)
            rois_in_src = set([c[0] for c in dst_cur])
            for i in rois_in_src :
                self._update_one_roi_table("ROI_%i" % i, src, dst)


            self._update_one_roi_table("CSV_DAM_ACTIVITY", src, dst, dump_in_csv=True)
            try:
                self._update_one_roi_table("START_EVENTS", src, dst)
            except mysql.connector.errors.ProgrammingError:
                logging.error("Programming Error")
                pass


            for table in ["IMG_SNAPSHOTS", "SENSORS"]:
                try:
                    self._update_table(table, src, dst)

                except Exception as e:
                    logging.error("Cannot mirror the '%s' table" % table)
                    logging.error(e)


    def _replace_img_snapshot_table(self, table_name, src, dst):
        src_cur = src.cursor(buffered=True)
        dst_cur = dst.cursor()

        src_command = "SELECT id,t,img FROM %s" % table_name
        src_cur.execute(src_command)

        for sc in src_cur:
            id,t,img = sc
            command = "INSERT INTO %s (id,t,img) VALUES(?,?,?);" % table_name
            dst_cur.execute(command, [id,t,sqlite3.Binary(img)])
            dst.commit()

    def _replace_table(self,table_name, src, dst, dump_in_csv=False):
        src_cur = src.cursor(buffered=True)
        dst_cur = dst.cursor()

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
            if dump_in_csv:
                with open(self._dam_file_name,"a") as f:
                    row = "\t".join(["{0}".format(val) for val in sc])
                    f.write(row)
                    f.write("\n")

        if len(to_insert) > 0:
            value_string = ",".join(to_insert)
            dst_command = "INSERT INTO %s VALUES %s" % (table_name, value_string )
            dst_cur.execute(dst_command)
        dst.commit()


    def _update_one_roi_table(self, table_name, src, dst, dump_in_csv=False):
        src_cur = src.cursor(buffered=True)
        dst_cur = dst.cursor()

        try:
            dst_command= "SELECT MAX(id) FROM %s" % table_name
            dst_cur.execute(dst_command)
        except (sqlite3.OperationalError, mysql.connector.errors.ProgrammingError):
            logging.warning("Local table %s appears empty. Rebuilding it from source" % table_name)
            self._replace_table(table_name, src, dst)
            return

        last_id_in_dst = 0
        for c in dst_cur:
            if c[0] is None:
                logging.warning("There seem to be no data in %s, %s. Recreating it" % (os.path.basename(self._dst_path), table_name))
                self._replace_table(table_name, src, dst)
            else:
                last_id_in_dst = c[0]
        src_command = "SELECT * FROM %s WHERE id > %d" % (table_name, last_id_in_dst)
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

            if dump_in_csv:
                with open(self._dam_file_name,"a") as f:
                    row = "\t".join(["{0}".format(val) for val in sc])
                    f.write(row)
                    f.write("\n")

        if len(to_insert) > 0:
            value_string = ",".join(to_insert)
            dst_command = "INSERT INTO %s VALUES %s" % (table_name, value_string )
            dst_cur.execute(dst_command)
        dst.commit()


    def _update_table(self, table_name, src, dst, replace=False):
        """
        Updates the contents of a custom table
        """

        src_cur = src.cursor(buffered=True)
        dst_cur = dst.cursor()

        #find info about the datatype for each column in the source
        h = {}
        src_command = "SHOW COLUMNS FROM %s " % table_name
        src_cur.execute(src_command)
        for c in src_cur:
            h[c[0]] = c[1]

        #check what is the status in the destination
        try:
            dst_command= "SELECT MAX(id) FROM %s" % table_name
            dst_cur.execute(dst_command)
        except (sqlite3.OperationalError, mysql.connector.errors.ProgrammingError):
            logging.warning("Local table %s appears empty. Rebuilding it from source" % table_name)
            replace = True

        if not replace:

            last_id_in_dst = 0
            for c in dst_cur:
                last_id_in_dst = c[0]
                if last_id_in_dst is None:
                    logging.warning("There seem to be no data in %s, %s stopping here" % (os.path.basename(self._dst_path), table_name))
                    return

            #retrieve only new data
            src_command = "SELECT * FROM %s WHERE id > %d" % (table_name, last_id_in_dst)
        
        if replace:

            #retrieve all data, not just the new ones
            src_command = "SELECT * FROM %s" % table_name

        #grab the data from src
        src_cur.execute(src_command)
        #go through it row by row
        for sc in src_cur:
            nv = len(sc)
            command = "INSERT INTO " + table_name + " VALUES(" + ','.join(['?']*nv) + ");"
            
            args = []
            #populate args taking datatype into account
            for d,k in zip(sc, h):
                if h[k] == "longblob":
                    args.append(sqlite3.Binary(d))
                else:
                    args.append(d)
            
            #and add them row by row to destination 
            dst_cur.execute(command, args)
            dst.commit()


class db_diff():
    """
    Class used to compare the status of a local SQLlite3 db to the remote counterpart
    This is used to check if the db backup is in good shape
    The same functions are duplicated in node_src/ethoscope_node/utils/mysql_backup.py
    """

    _remote_user = "node"
    _remote_pass = "node"

    def __init__(self, db_name, remote_host, filename):
        """
        remote_host is the IP address of the ethoscope we are supposed to check on
        filename is the local SQLlite3 file to check
        db_name is the name of the database
        """
    
        self._remote_host = remote_host
        self._dst_path = filename
        self._remote_db_name = db_name

    
    def _get_remote_db_info(self):
        """
        """

        #fetches data about the size of the remote db ( remote_local_tables_dictionary )
        src = mysql.connector.connect(host=self._remote_host,
                                      user=self._remote_user,
                                      passwd=self._remote_pass,
                                      buffered=True,
                                      charset=SQL_CHARSET,
                                      use_unicode=True)
            
        src_cur = src.cursor(buffered=True)
        
        command = 'SELECT TABLE_SCHEMA, TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA LIKE "ETHOSCOPE%";'
        src_cur.execute(command)
        tables = src_cur.fetchall()
        
        remote_local_tables_dictionary = {dbn : {} for dbn in set([entry[0] for entry in tables])}
        
        for entry in tables: 
            db_name = entry[0]
            table_name = entry[1]
            
            if table_name in ["ROI_MAP", "VAR_MAP"] or table_name.startswith("METADATA"):
                #tables that do not have a unique id - slower command
                command = 'SELECT count(*) from %s.%s' % (db_name, table_name)
            else:
                #tables that do
                command = 'SELECT max(id) FROM %s.%s' % (db_name, table_name)
            
            src_cur.execute(command)
            remote_local_tables_dictionary [db_name] . update ( { table_name :  src_cur.fetchone()[0] } )

        src.commit()
        src.close()
        
        return remote_local_tables_dictionary

    def _get_local_db_info(self):
        """
        """

        local_tables_dictionary = {}
        
        if os.path.exists(self._dst_path):
        
            with sqlite3.connect(self._dst_path, check_same_thread=False) as dst:
                dst_cur = dst.cursor()
                command = 'SELECT name FROM sqlite_master WHERE type ="table" AND name NOT LIKE "sqlite_%";'
                dst_cur.execute(command)
                tables = dst_cur.fetchall()


                
                for entry in tables: 
                    table_name = entry[0]
                    
                    if table_name not in ["ROI_MAP", "VAR_MAP", "METADATA"]:
                        command = 'SELECT max(id) FROM %s;' % table_name
                    else:
                        command = 'SELECT count(*) from %s' % table_name
                    
                    dst_cur.execute(command)
                    local_tables_dictionary . update ( { table_name :  dst_cur.fetchone()[0] } )            
                
            return local_tables_dictionary
        
        else:
            
            return {} # sqlite3 file does not exist yet
            
    def compare_databases(self):
        """
        """
        total_remote = 0
        total_local = 0
        
        try:
            remote_tables_info = self._get_remote_db_info()
        except:
            logging.error("Problem getting info from the remote database: %s " % self._remote_db_name)
        
        try:
            local_tables_info = self._get_local_db_info()
        except:
            logging.error("Problem getting info from the local database %s - perhaps it is locked?" % self._dst_path)
        
        try:
            for table in sorted(local_tables_info):
                l = local_tables_info[table]
                r = remote_tables_info[self._remote_db_name][table]
                
                if r == None : r = 0
                if l == None : l = 0
                
                total_remote += int(r)
                total_local += int(l)
                
                #print ("Transferred %s / %s for table %s (%0.2f)" % (l, r, table, l/r*100))
                
            return total_local/total_remote*100

        except:
            return -1
