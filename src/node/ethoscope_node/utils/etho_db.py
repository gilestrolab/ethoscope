#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  etho_db.py
#  
#  Copyright 2019 Giorgio <giorgio@gilest.ro>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  
__author__ = 'giorgio'

import datetime
import string
import random
import pickle
import os
import secrets
import multiprocessing
import sqlite3
import logging
import traceback

from ethoscope_node.utils.configuration import migrate_conf_file

class ExperimentalDB(multiprocessing.Process):
    
    _runs_table_name = "runs"
    _users_table_name = "users"
    _experiments_table_name = "experiments"
    _ethoscopes_table_name = "ethoscopes"
    
    def __init__(self, config_dir: str = "/etc/ethoscope"):
        super().__init__()
        self._config_dir = config_dir
        self._db_name = os.path.join(config_dir, "ethoscope-node.db")
        
        # Ensure config directory exists
        os.makedirs(config_dir, exist_ok=True)
        
        # Handle migration from old location
        migrate_conf_file('/etc/ethoscope-node.db', config_dir)
        self.create_tables()

    def executeSQL(self, command: str):
        """
        Execute an SQL command and return the results.
        
        Args:
            command (str): The SQL command to execute
            
        Returns:
            Union[int, list, int]: 
                - For INSERT: returns the last inserted row id
                - For SELECT: returns list of rows
                - For other commands: returns 0
                - Returns -1 if there's an error
        """
        db = None
        cursor = None
        try:
            db = sqlite3.connect(self._db_name)
            
            if command.upper().startswith("SELECT"):
                db.row_factory = sqlite3.Row
                
            cursor = db.cursor()
            cursor.execute(command)
            lid = cursor.lastrowid  # the last id inserted / 0 if not an INSERT command
            rows = cursor.fetchall()  # return the result of a SELECT query / [] if not a SELECT query
            
            db.commit()
            return lid or rows or 0
                
        except sqlite3.Error as e:
            logging.error(f"SQLite error while executing '{command}': {str(e)}")
            logging.error(traceback.format_exc())
            return -1
        except Exception as e:
            logging.error(f"Unexpected error while executing '{command}': {str(e)}")
            logging.error(traceback.format_exc())
            return -1
        finally:
            if cursor:
                cursor.close()
            if db:
                db.close()    
    
    def create_tables(self):
        """
        Create the necessary tables in the database if they do not exist.
        """
        
        sql_create_runs_table = """CREATE TABLE IF NOT EXISTS %s (
                                run_id TEXT PRIMARY KEY,
                                type TEXT NOT NULL,
                                ethoscope_name TEXT NOT NULL,
                                ethoscope_id TEXT NOT NULL,
                                user_name TEXT,
                                user_id INTEGER NOT NULL,
                                location TEXT,
                                start_time TIMESTAMP NOT NULL,
                                end_time TIMESTAMP,
                                alert INTEGER,
                                problems TEXT,
                                experimental_data TEXT,
                                comments TEXT,
                                status TEXT
                            );""" % self._runs_table_name

        #self.executeSQL ( "DROP TABLE ethoscopes;" )

        sql_create_experiments_table = """CREATE TABLE IF NOT EXISTS %s (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                runs TEXT,
                                metadata BLOB,
                                tags TEXT,
                                comments TEXT
                            );""" % self._experiments_table_name
    

        sql_create_users_table = """CREATE TABLE IF NOT EXISTS %s (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                username TEXT NOT NULL,
                                fullname TEXT NOT NULL,
                                pin TEXT,
                                email TEXT NOT NULL,
                                labname TEXT,
                                active INTEGER,
                                isadmin INTEGER,
                                created TIMESTAMP
                            );""" % self._users_table_name


        sql_create_ethoscopes_table = """CREATE TABLE IF NOT EXISTS %s (
                                ethoscope_id TEXT PRIMARY KEY,
                                ethoscope_name TEXT NOT NULL,
                                first_seen TIMESTAMP NOT NULL,
                                last_seen TIMESTAMP NOT NULL,
                                active INTEGER,
                                last_ip TEXT,
                                machineinfo TEXT,
                                problems TEXT,
                                comments TEXT,
                                status TEXT
                            );""" % self._ethoscopes_table_name

        sql_create_alert_logs_table = """CREATE TABLE IF NOT EXISTS alert_logs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                device_id TEXT NOT NULL,
                                alert_type TEXT NOT NULL,
                                run_id TEXT,
                                message TEXT NOT NULL,
                                recipients TEXT,
                                created_at TIMESTAMP NOT NULL,
                                updated_at TIMESTAMP NOT NULL
                            );"""

        self.executeSQL ( sql_create_runs_table )
        self.executeSQL ( sql_create_experiments_table )
        self.executeSQL ( sql_create_users_table )
        self.executeSQL ( sql_create_ethoscopes_table )
        self.executeSQL ( sql_create_alert_logs_table )
        
        # Run database migrations
        self._migrate_database()
    
    def _migrate_database(self):
        """
        Handle database schema migrations.
        """
        try:
            # Migration 1: Convert ethoscopes table to use ethoscope_id as primary key
            self._migrate_ethoscopes_primary_key()
            # Migration 2: Convert runs table to use run_id as primary key
            self._migrate_runs_primary_key()
            # Migration 3: Add run_id column to alert_logs table
            self._migrate_alert_logs_run_id()
        except Exception as e:
            logging.error(f"Error during database migration: {e}")
    
    def _migrate_ethoscopes_primary_key(self):
        """
        Migrate ethoscopes table to use ethoscope_id as primary key instead of auto-incrementing id.
        """
        try:
            # Check if the table has the old structure (id column exists)
            check_old_structure = f"PRAGMA table_info({self._ethoscopes_table_name})"
            table_info = self.executeSQL(check_old_structure)
            
            if not isinstance(table_info, list):
                return
            
            # Check if 'id' column exists (old structure) and ethoscope_id is not primary key
            has_id_column = any(col[1] == 'id' for col in table_info)
            ethoscope_id_is_primary = any(col[1] == 'ethoscope_id' and col[5] == 1 for col in table_info)
            
            if has_id_column and not ethoscope_id_is_primary:
                logging.info("Migrating ethoscopes table to use ethoscope_id as primary key")
                
                # Create new table with correct structure
                sql_create_new_table = f"""CREATE TABLE {self._ethoscopes_table_name}_new (
                    ethoscope_id TEXT PRIMARY KEY,
                    ethoscope_name TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL,
                    active INTEGER,
                    last_ip TEXT,
                    machineinfo TEXT,
                    problems TEXT,
                    comments TEXT,
                    status TEXT
                )"""
                
                # Copy data from old table to new table, handling duplicates by keeping the most recent
                sql_copy_data = f"""INSERT INTO {self._ethoscopes_table_name}_new 
                    (ethoscope_id, ethoscope_name, first_seen, last_seen, active, last_ip, machineinfo, problems, comments, status)
                    SELECT ethoscope_id, ethoscope_name, first_seen, last_seen, active, last_ip, machineinfo, problems, comments, status
                    FROM {self._ethoscopes_table_name}
                    WHERE id IN (
                        SELECT MAX(id) FROM {self._ethoscopes_table_name} GROUP BY ethoscope_id
                    )"""
                
                # Drop old table
                sql_drop_old = f"DROP TABLE {self._ethoscopes_table_name}"
                
                # Rename new table
                sql_rename_new = f"ALTER TABLE {self._ethoscopes_table_name}_new RENAME TO {self._ethoscopes_table_name}"
                
                # Execute migration
                self.executeSQL(sql_create_new_table)
                self.executeSQL(sql_copy_data)
                self.executeSQL(sql_drop_old)
                self.executeSQL(sql_rename_new)
                
                logging.info("Successfully migrated ethoscopes table to use ethoscope_id as primary key")
                
        except Exception as e:
            logging.error(f"Error migrating ethoscopes table: {e}")
    
    def _migrate_runs_primary_key(self):
        """
        Migrate runs table to use run_id as primary key instead of auto-incrementing id.
        """
        try:
            # Check if the table has the old structure (id column exists)
            check_old_structure = f"PRAGMA table_info({self._runs_table_name})"
            table_info = self.executeSQL(check_old_structure)
            
            if not isinstance(table_info, list):
                return
            
            # Check if 'id' column exists (old structure) and run_id is not primary key
            has_id_column = any(col[1] == 'id' for col in table_info)
            run_id_is_primary = any(col[1] == 'run_id' and col[5] == 1 for col in table_info)
            
            if has_id_column and not run_id_is_primary:
                logging.info("Migrating runs table to use run_id as primary key")
                
                # Create new table with correct structure
                sql_create_new_table = f"""CREATE TABLE {self._runs_table_name}_new (
                    run_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    ethoscope_name TEXT NOT NULL,
                    ethoscope_id TEXT NOT NULL,
                    user_name TEXT,
                    user_id INTEGER NOT NULL,
                    location TEXT,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    alert INTEGER,
                    problems TEXT,
                    experimental_data TEXT,
                    comments TEXT,
                    status TEXT
                )"""
                
                # Copy data from old table to new table, handling duplicates by keeping the most recent
                sql_copy_data = f"""INSERT INTO {self._runs_table_name}_new 
                    (run_id, type, ethoscope_name, ethoscope_id, user_name, user_id, location, start_time, end_time, alert, problems, experimental_data, comments, status)
                    SELECT run_id, type, ethoscope_name, ethoscope_id, user_name, user_id, location, start_time, end_time, alert, problems, experimental_data, comments, status
                    FROM {self._runs_table_name}
                    WHERE id IN (
                        SELECT MAX(id) FROM {self._runs_table_name} GROUP BY run_id
                    )"""
                
                # Drop old table
                sql_drop_old = f"DROP TABLE {self._runs_table_name}"
                
                # Rename new table
                sql_rename_new = f"ALTER TABLE {self._runs_table_name}_new RENAME TO {self._runs_table_name}"
                
                # Execute migration
                self.executeSQL(sql_create_new_table)
                self.executeSQL(sql_copy_data)
                self.executeSQL(sql_drop_old)
                self.executeSQL(sql_rename_new)
                
                logging.info("Successfully migrated runs table to use run_id as primary key")
                
        except Exception as e:
            logging.error(f"Error migrating runs table: {e}")
    
    def _migrate_alert_logs_run_id(self):
        """
        Add run_id column to alert_logs table if it doesn't exist.
        """
        try:
            # Check if run_id column already exists
            check_columns = f"PRAGMA table_info(alert_logs)"
            table_info = self.executeSQL(check_columns)
            
            if not isinstance(table_info, list):
                # Table might not exist yet, let the regular creation handle it
                return
            
            # Check if run_id column exists
            has_run_id_column = any(col[1] == 'run_id' for col in table_info)
            
            if not has_run_id_column:
                logging.info("Adding run_id column to alert_logs table")
                
                # Add the run_id column
                sql_add_column = "ALTER TABLE alert_logs ADD COLUMN run_id TEXT"
                self.executeSQL(sql_add_column)
                
                # Create index for better performance
                sql_create_index = "CREATE INDEX IF NOT EXISTS idx_alert_logs_device_type_run ON alert_logs(device_id, alert_type, run_id)"
                self.executeSQL(sql_create_index)
                
                logging.info("Successfully added run_id column to alert_logs table")
                
        except Exception as e:
            logging.error(f"Error migrating alert_logs table: {e}")

    def getRun (self, run_id, asdict=False):
        """
        Gather runs with given ID if provided, if run_id equals 'all', it will collect all available runs
        :param run_id: the ID of the run to be interrogated
        :param asdict: returns the rows as dictionaries
        :return: either a sqlite3 row object or a dictionary
        """
        
        if run_id == 'all':
            sql_get_experiment = "SELECT * FROM %s" % (self._runs_table_name)
        else:
            sql_get_experiment = "SELECT * FROM %s WHERE run_id = '%s'" % (self._runs_table_name, run_id)
        
        row = self.executeSQL(sql_get_experiment)
        
        if row == 0:
            return {}
        
        if asdict:
            keys = row[0].keys()
            #return [dict([(key, value) for key, value in zip(keys, line)]) for line in row]
            return {line['run_id'] : {key: value for key, value in zip(keys, line)} for line in row}
            
        else:
            return row
                    

    def addRun (self, run_id="", experiment_type="tracking", ethoscope_name="", ethoscope_id="n/a", username="n/a", user_id=0, location="", alert=False, comments="", experimental_data=""):
        """
        Add a new row with a new experiment
        :param run_id: A unique run ID
        :param experiment_type: Type of experiment e.g. tracking, video, etc
        :param etho_num: Ethoscope number
        :param etho_id:  Ethoscope id string
        :param username: Username of the user who started the experiment
        :param user_id:  User ID of the user who started the experiment
        :param location: The location where the ethoscope is running
        :param alert:    Send alert via email, sms?
        :param comments: Any comment
        :param experimental_data: link to the metadata (currently unsupported)
        :return: the ID of the experiment assigned by the database
        """

        #if a run_id is not provided, it will be generated on the spot
        if run_id == "": run_id = secrets.token_hex(8)
        
        start_time = datetime.datetime.now()
        end_time = 0
        status = "running"

        problems = ""
        
        sql_enter_new_experiment = "INSERT INTO %s VALUES( '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s')" % ( self._runs_table_name, run_id, experiment_type, ethoscope_name, ethoscope_id, username, user_id, location, start_time, end_time, alert, problems, experimental_data, comments, status)
        return self.executeSQL ( sql_enter_new_experiment )
    
    
    def stopRun (self, run_id):
        """
        Stop the experiment with the provided id
        :param run_id: the ID of the run to be stopped
        :param ethoscope_id: the ethoscope id of the run to be stopped
        :return status: the new status of the experiment 
        """
        end_time = datetime.datetime.now()
        status = "stopped"
        
        sql_update_experiment = "UPDATE %s SET end_time = '%s', status = '%s' WHERE run_id = '%s'" % ( self._runs_table_name, end_time, status, run_id )
        self.executeSQL(sql_update_experiment)
        return self.getRun(run_id)[0]['status']
            

    def flagProblem (self, run_id, message=""):
        '''
        '''
        ct = datetime.datetime.now()

        problems = self.getRun(run_id)[0]['problems']
        problems = "%s, %s;" % (ct, message) + problems # append in front
        
        sql_update_experiment = "UPDATE %s SET problems = '%s' WHERE run_id = '%s'" % ( self._runs_table_name, problems, run_id )
        return self.executeSQL ( sql_update_experiment )

    def addToExperiment(self, experiment_id=None, runs=None, metadata=None, comments=None):
        '''
        '''
        if type(runs) == list:
            runs = ";".join(runs)
        
        if experiment_id == None:
            sql_enter_new_experiment = "INSERT INTO %s VALUES( NULL, '%s', '%s', '%s')" % ( self._experiments_table_name, runs, metadata, comments)
        else:
            updates = {name: value for (name, value) in zip(['runs', 'metadata', 'comments'], [runs, metadata, comments]) if value != None}
            values = " , ".join(["%s = '%s'" % (name, updates[name]) for name in updates.keys()])
            sql_enter_new_experiment = "UPDATE "+ self._experiments_table_name +" SET "+ values + " WHERE experiment_id = '"+str(experiment_id)+"'"
            
        return self.executeSQL ( sql_enter_new_experiment )
            

    def getExperiment(self, experiment_id, asdict=False):
        """
        Gather experiments with given ID if provided, if experiment_id equals 'all', it will collect all available experiments
        :param experiment_id: the ID of the experiment to be interrogated
        :param asdict: returns the rows as dictionaries
        :return: either a sqlite3 row object or a dictionary
        """
        
        if experiment_id == 'all':
            sql_get_experiment = "SELECT * FROM %s" % (self._experiments_table_name)
        else:
            sql_get_experiment = "SELECT * FROM %s WHERE run_id = '%s'" % (self._experiments_table_name, experiment_id)
        
        row = self.executeSQL(sql_get_experiment)
        
        if row == 0:
            return {}
        
        if asdict:
            keys = row[0].keys()
            #return [dict([(key, value) for key, value in zip(keys, line)]) for line in row]
            return {line['id'] : {key: value for key, value in zip(keys, line)} for line in row}
            
        else:
            return row
    
    def getEthoscope (self, ethoscope_id, asdict=False):
        """
        Gather ethoscope with given ID if provided, if experiment_id equals 'all', it will collect all available ethoscopes
        :param ethoscope_id: the ID of the ethoscope to be interrogated
        :param asdict: returns the rows as dictionaries
        :return: either a sqlite3 row object or a dictionary
        """

        if ethoscope_id == 'all':
            sql_get_ethoscope = "SELECT * FROM %s" % (self._ethoscopes_table_name)
        else:
            sql_get_ethoscope = "SELECT * FROM %s WHERE ethoscope_id = '%s'" % (self._ethoscopes_table_name, ethoscope_id)
        
        #this returns a row if the query is successful, a 0 if no entry was found and -1 if there is an issue connecting to the db
        row = self.executeSQL(sql_get_ethoscope)
        
        if type(row) != list and row <= 0:
            return {}
        
        if asdict:
            # Convert sqlite3.Row objects to regular dicts to avoid connection leaks
            result = {}
            for line in row:
                line_dict = dict(line)  # Convert sqlite3.Row to dict
                result[line_dict['ethoscope_id']] = line_dict
            return result
            
        else:
            return row
        
    
    def updateEthoscopes(self, ethoscope_id, ethoscope_name=None, active=None, last_ip=None, problems=None, machineinfo=None, comments=None, status=None, blacklist=['ETHOSCOPE_000']):
        """
        Updates the parameters of a given ethoscope
        if an ethoscope with the same ID is not found in the current database
        it will create a new entry for it
        """
        e = self.getEthoscope(ethoscope_id, True)
        now = datetime.datetime.now()

        if ethoscope_name in blacklist:
            return

        if machineinfo:
            machineinfo = machineinfo.replace("'", "''")

        if type(e) is dict and e != {}:
            updates = {name: value for (name, value) in zip(['ethoscope_name', 'active', 'last_ip', 'machineinfo', 'problems', 'comments', 'status'], [ethoscope_name, active, last_ip, machineinfo, problems, comments, status]) if value is not None}
            values = " , ".join(["%s = '%s'" % (name, updates[name]) for name in updates.keys()])
            sql_update_ethoscope = "UPDATE " + self._ethoscopes_table_name + " SET last_seen = '" + str(now) + "', " + values + " WHERE ethoscope_id = '" + str(ethoscope_id) + "'"

        else:
            # Don't create new ethoscope entries without a valid name
            if not ethoscope_name or ethoscope_name in ['', 'None', 'NULL'] or ethoscope_name is None:
                logging.warning("Refusing to create new ethoscope entry without valid name. ID: %s, Name: %s" % (ethoscope_id, ethoscope_name))
                return None
            
            active = 1
            sql_update_ethoscope = "INSERT INTO %s VALUES( '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s')" % (self._ethoscopes_table_name, ethoscope_id, ethoscope_name, now, now, active, last_ip, machineinfo, problems, comments, status)
            logging.warning("Adding a new ethoscope to the db. Welcome %s with id %s" % (ethoscope_name, ethoscope_id))

        return self.executeSQL(sql_update_ethoscope)
    
    def getUserByName(self, username: str, asdict: bool = False):
        """
        Get user information by username.
        
        Args:
            username: Username to look up
            asdict: Return as dictionary if True
            
        Returns:
            User data from database or empty dict if not found
        """
        sql_get_user = "SELECT * FROM %s WHERE username = '%s'" % (self._users_table_name, username)
        
        row = self.executeSQL(sql_get_user)
        
        if type(row) != list or len(row) == 0:
            return {}
        
        if asdict:
            return dict(row[0])
        else:
            return row[0]
    
    def getUserByEmail(self, email: str, asdict: bool = False):
        """
        Get user information by email address.
        
        Args:
            email: Email address to look up
            asdict: Return as dictionary if True
            
        Returns:
            User data from database or empty dict if not found
        """
        sql_get_user = "SELECT * FROM %s WHERE email = '%s'" % (self._users_table_name, email)
        
        row = self.executeSQL(sql_get_user)
        
        if type(row) != list or len(row) == 0:
            return {}
        
        if asdict:
            return dict(row[0])
        else:
            return row[0]
    
    def getUsersForDevice(self, device_id: str, asdict: bool = False):
        """
        Get all users who have run experiments on a specific device.
        
        Args:
            device_id: Device ID to look up
            asdict: Return as dictionary if True
            
        Returns:
            List of user data for users who have used this device
        """
        sql_get_users = """
        SELECT DISTINCT u.* FROM %s u 
        JOIN %s r ON u.username = r.user_name 
        WHERE r.ethoscope_id = '%s' AND u.active = 1
        """ % (self._users_table_name, self._runs_table_name, device_id)
        
        rows = self.executeSQL(sql_get_users)
        
        if type(rows) != list or len(rows) == 0:
            return []
        
        if asdict:
            return [dict(row) for row in rows]
        else:
            return rows
    
    def logAlert(self, device_id: str, alert_type: str, message: str, recipients: str = "", run_id: str = None):
        """
        Log an alert that was sent.
        
        Args:
            device_id: Device ID that triggered the alert
            alert_type: Type of alert (device_stopped, storage_warning, etc.)
            message: Alert message content
            recipients: Comma-separated list of email recipients
            run_id: Run ID associated with the alert (optional)
            
        Returns:
            ID of the inserted alert log entry
        """
        timestamp = datetime.datetime.now()
        
        # Escape single quotes in message
        escaped_message = message.replace("'", "''")
        
        # Handle run_id - use NULL if not provided
        run_id_sql = f"'{run_id}'" if run_id else "NULL"
        
        sql_log_alert = """
        INSERT INTO alert_logs VALUES(
            NULL, '%s', '%s', %s, '%s', '%s', '%s', '%s'
        )
        """ % (device_id, alert_type, run_id_sql, escaped_message, recipients, timestamp, timestamp)
        
        return self.executeSQL(sql_log_alert)
    
    def hasAlertBeenSent(self, device_id: str, alert_type: str, run_id: str = None) -> bool:
        """
        Check if an alert has already been sent for a specific device, alert type, and run_id.
        
        Args:
            device_id: Device ID to check
            alert_type: Type of alert to check
            run_id: Run ID to check (optional)
            
        Returns:
            True if alert has already been sent, False otherwise
        """
        try:
            sql_conditions = ["device_id = '%s'" % device_id, "alert_type = '%s'" % alert_type]
            
            if run_id:
                sql_conditions.append("run_id = '%s'" % run_id)
            else:
                sql_conditions.append("run_id IS NULL")
            
            where_clause = " AND ".join(sql_conditions)
            
            sql_check_alert = f"""
            SELECT COUNT(*) as count FROM alert_logs 
            WHERE {where_clause}
            """
            
            result = self.executeSQL(sql_check_alert)
            
            if isinstance(result, list) and len(result) > 0:
                count = result[0][0] if hasattr(result[0], '__getitem__') else result[0]['count']
                return count > 0
            
            return False
            
        except Exception as e:
            logging.error(f"Error checking alert history for {device_id}, {alert_type}, {run_id}: {e}")
            return False
    
    def getAlertHistory(self, device_id: str = None, alert_type: str = None, 
                       limit: int = 100, asdict: bool = False):
        """
        Get alert history with optional filtering.
        
        Args:
            device_id: Filter by device ID (optional)
            alert_type: Filter by alert type (optional)
            limit: Maximum number of records to return
            asdict: Return as dictionary if True
            
        Returns:
            List of alert log entries
        """
        sql_conditions = []
        
        if device_id:
            sql_conditions.append("device_id = '%s'" % device_id)
        
        if alert_type:
            sql_conditions.append("alert_type = '%s'" % alert_type)
        
        where_clause = ""
        if sql_conditions:
            where_clause = " WHERE " + " AND ".join(sql_conditions)
        
        sql_get_alerts = """
        SELECT * FROM alert_logs%s 
        ORDER BY created_at DESC 
        LIMIT %d
        """ % (where_clause, limit)
        
        rows = self.executeSQL(sql_get_alerts)
        
        if type(rows) != list:
            return []
        
        if asdict:
            return [dict(row) for row in rows]
        else:
            return rows
    
    def retire_inactive_devices(self, threshold_days: int = 90) -> int:
        """
        Retire devices that haven't been seen for more than threshold_days.
        
        Args:
            threshold_days: Number of days after which to retire inactive devices
            
        Returns:
            Number of devices that were retired
        """
        cutoff_date = datetime.datetime.now() - datetime.timedelta(days=threshold_days)
        cutoff_timestamp = cutoff_date.timestamp()
        
        # Get all active devices and check their timestamps manually
        # This handles different timestamp formats more robustly
        sql_get_active = "SELECT ethoscope_id, last_seen FROM %s WHERE active = 1" % self._ethoscopes_table_name
        
        active_devices = self.executeSQL(sql_get_active)
        if not isinstance(active_devices, list):
            return 0
        
        devices_to_retire = []
        
        for device in active_devices:
            ethoscope_id = device[0]
            last_seen = device[1]
            
            try:
                # Try to parse the last_seen timestamp
                if isinstance(last_seen, str):
                    # Try different datetime formats
                    for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f %Z']:
                        try:
                            last_seen_dt = datetime.datetime.strptime(last_seen, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        # If no format worked, try parsing as timestamp
                        try:
                            last_seen_dt = datetime.datetime.fromtimestamp(float(last_seen))
                        except:
                            # If all parsing fails, consider it for retirement
                            devices_to_retire.append(ethoscope_id)
                            continue
                else:
                    # Try as numeric timestamp
                    last_seen_dt = datetime.datetime.fromtimestamp(float(last_seen))
                
                # Check if device should be retired
                if last_seen_dt.timestamp() < cutoff_timestamp:
                    devices_to_retire.append(ethoscope_id)
                    
            except Exception as e:
                # If any parsing fails, consider device for retirement
                logging.warning(f"Failed to parse timestamp for device {ethoscope_id}: {e}")
                devices_to_retire.append(ethoscope_id)
        
        # Retire the devices
        retired_count = 0
        for ethoscope_id in devices_to_retire:
            sql_retire = "UPDATE %s SET active = 0 WHERE ethoscope_id = '%s'" % (
                self._ethoscopes_table_name, ethoscope_id
            )
            
            result = self.executeSQL(sql_retire)
            if result != -1:
                retired_count += 1
            else:
                logging.error(f"Failed to retire device {ethoscope_id}")
        
        if retired_count > 0:
            logging.info(f"Retired {retired_count} inactive devices (offline for >{threshold_days} days)")
        else:
            logging.info(f"No devices found to retire (offline for >{threshold_days} days)")
        
        return retired_count
    
    def purge_unnamed_devices(self) -> int:
        """
        Purge devices that have no name (None or empty string) or invalid timestamps.
        
        Returns:
            Number of devices that were purged
        """
        # Get all devices and check them manually for better detection
        sql_get_all = "SELECT ethoscope_id, ethoscope_name, last_seen, first_seen FROM %s" % self._ethoscopes_table_name
        
        all_devices = self.executeSQL(sql_get_all)
        if not isinstance(all_devices, list):
            return 0
        
        devices_to_purge = []
        
        for device in all_devices:
            ethoscope_id = device[0]
            ethoscope_name = device[1]
            last_seen = device[2]
            first_seen = device[3]
            
            should_purge = False
            
            # Check for unnamed devices
            if not ethoscope_name or ethoscope_name in ['', 'None', 'NULL'] or ethoscope_name is None:
                should_purge = True
            
            # Check for invalid timestamps
            if not should_purge:
                for timestamp_field in [last_seen, first_seen]:
                    if timestamp_field is None or timestamp_field == '':
                        should_purge = True
                        break
                    
                    # Try to parse timestamp to see if it's valid
                    if isinstance(timestamp_field, str):
                        try:
                            # Try different formats
                            for fmt in ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f %Z']:
                                try:
                                    datetime.datetime.strptime(timestamp_field, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                # If no format worked, try as timestamp
                                try:
                                    datetime.datetime.fromtimestamp(float(timestamp_field))
                                except:
                                    should_purge = True
                                    break
                        except:
                            should_purge = True
                            break
            
            if should_purge:
                devices_to_purge.append(ethoscope_id)
        
        # Purge the devices
        purged_count = 0
        for ethoscope_id in devices_to_purge:
            sql_purge = "DELETE FROM %s WHERE ethoscope_id = '%s'" % (
                self._ethoscopes_table_name, ethoscope_id
            )
            
            result = self.executeSQL(sql_purge)
            if result != -1:
                purged_count += 1
            else:
                logging.error(f"Failed to purge device {ethoscope_id}")
        
        if purged_count > 0:
            logging.info(f"Purged {purged_count} unnamed/invalid devices from database")
        else:
            logging.info(f"No unnamed/invalid devices found to purge")
        
        return purged_count
        
class simpleDB(object):
    '''
    '''
    
    def __init__(self, dbfile, keys=[]):
        self._db = []
        self._db_file = dbfile
        self._keys = ['id'] + keys
        
    def _get_unique_id(self, size=4):
        '''
        '''
        chars=string.ascii_uppercase + string.digits
        uid = ''.join(random.choice(chars) for _ in range(size))
        all_ids = [item['id'] for item in self._db]
        
        if uid not in all_ids: return uid
        else: return self._get_unique_id()
            
    
    def add (self, dic, active=True):
        '''
        '''
        dic['id'] = self._get_unique_id()
        dic['active'] = active
        dic['created'] = datetime.datetime.now()
        
        self._db.append(dic)
        
    def remove (self, eid):
        '''
        '''
        for i in range(len(self._db)): 
            if self._db[i]['id'] == eid: 
                del self._db[i]
                return True
            
        return False
        
    def list (self, onlyfield=None, active=False):
        '''
        '''
        if onlyfield == None:
            return [u for u in self._db if (u['active'] or not active)]
            
        elif onlyfield in self._keys:
            return [u[onlyfield] for u in self._db if (u['active'] or not active)]
            
        else:
            return []
       
    def save (self):
        '''
        '''
        try:
            with open(self._db_file, 'wb') as file:
                pickle.dump(self._db, file, pickle.HIGHEST_PROTOCOL)
            return True
        except:
            return False


    def load (self):
        '''
        '''
        if os.path.exists(self._db_file):
            with open(self._db_file, 'rb') as file:
                try:
                    self._db = pickle.load(file)
                    return True
                except:
                    return False
                
class UsersDB(simpleDB):
    def __init__(self, dbfile):
        '''
        '''
        keys = ['name', 'email', 'laboratory']
        super(UsersDB, self).__init__(dbfile, keys)                


class Incubators(simpleDB):
    def __init__(self, dbfile):
        '''
        '''
        keys = ['name', 'set_temperature', 'set_humidity', 'set_light', 'lat_temperature', 'lat_humidity', 'lat_light', 'lat_reading']
        super(Incubators, self).__init__(dbfile, keys)                


def random_date(start, end):
    """
    This function will return a random datetime between two datetime 
    objects.
    """
    delta = end - start
    int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
    random_second = random.randrange(int_delta)
    return start + datetime.timedelta(seconds=random_second)


def createRandomRuns(number):

    edb = ExperimentalDB()
    users = ["ggilestro", "afrench", "hjones", "mjoyce", "ebeckwith", "qgeissmann"]
    ethoscopes = {"ETHOSCOPE_%03d" % num : eid for (num, eid) in zip (range(1,150), [secrets.token_hex(8) for i in range(149)] ) }
    
    for run in [secrets.token_hex(8) for i in range(number)]:
        user = random.choice(users)
        user_id = users.index(user)
        ethoscope_name = random.choice([n for n in ethoscopes.keys()])
        ethoscope_id = ethoscopes[ethoscope_name]
        location = random.choice(["Incubator_%02d" % i for i in range(1,11)])
        date = random_date(datetime.datetime(2020,1,1), datetime.datetime(2020,12,31)).strftime("%Y-%m-%d_%H-%M-%S")
        database = "%s_%s.db" % (date, ethoscope_id)
        filepath = "/ethoscope_data/results/%s/%s/%s/%s" % (ethoscope_id, ethoscope_name, date, database)
        r = edb.addRun(run, "tracking", ethoscope_name, ethoscope_id, user, user_id, location, random.choice([1,0]), "", filepath)
        print (r)

def createRandomEthoscopes(number):

    edb = ExperimentalDB()
    ethoscopes = {"ETHOSCOPE_%03d" % num : eid for (num, eid) in zip (range(1,number+1), [secrets.token_hex(8) for i in range(number)] ) }
    
    for etho in [name for name in ethoscopes.keys()]:
        print (edb.updateEthoscopes(ethoscopes[etho], etho))

                
if __name__ == '__main__':

    test_users = False
    test_experiments = True

    if test_users:
        db = UsersDB('/home/gg/users_db.db')
        db.load()
        #print (db.list())
        db.add({'name': "Giorgio Gilestro", 'email': "g.gilestro@imperial.ac.uk", 'laboratory': "gilestro lab"})
        db.add({'name' : "Mickey Mouse", 'email': "m.mouse@imperial.ac.uk", 'laboratory' : "gilestro lab"})
        #print (db.removeUser('5Q6E'))
        db.save()
    
    if test_experiments:
        
        #createRandomRuns(350)
        createRandomEthoscopes(100)
        
        #print ("added row: ", edb.getRun(run_id, asdict=True))
        #ro = edb.stopRun(run_id)
        #print ("stopped row: ", ro)
        #print (edb.getRun("all", asdict=True))

        
        
        
        #edb.addToExperiment(runs=run_id)
        #edb.addToExperiment(runs=run_id, comments = "some random comment")
        #edb.addToExperiment(runs=more_runs, metadata = "here should go some file content")
        #print (edb.getExperiment('all', asdict=True))
        
            
