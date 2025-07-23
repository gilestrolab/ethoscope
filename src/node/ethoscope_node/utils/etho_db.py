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
    _incubators_table_name = "incubators"
    
    def __init__(self, config_dir: str = "/etc/ethoscope"):
        super().__init__()
        self._config_dir = config_dir
        self._db_name = os.path.join(config_dir, "ethoscope-node.db")
        
        # Ensure config directory exists
        os.makedirs(config_dir, exist_ok=True)
        
        # Handle migration from old location
        migrate_conf_file('/etc/ethoscope-node.db', config_dir)
        self.create_tables()

    def executeSQL(self, command: str, params: tuple = None):
        """
        Execute an SQL command and return the results.
        
        Args:
            command (str): The SQL command to execute
            params (tuple): Optional parameters for parameterized queries
            
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
            if params:
                cursor.execute(command, params)
            else:
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

        sql_create_incubators_table = """CREATE TABLE IF NOT EXISTS %s (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                name TEXT NOT NULL UNIQUE,
                                location TEXT,
                                owner TEXT,
                                description TEXT,
                                created TIMESTAMP NOT NULL,
                                active INTEGER DEFAULT 1
                            );""" % self._incubators_table_name

        self.executeSQL ( sql_create_runs_table )
        self.executeSQL ( sql_create_experiments_table )
        self.executeSQL ( sql_create_users_table )
        self.executeSQL ( sql_create_ethoscopes_table )
        self.executeSQL ( sql_create_alert_logs_table )
        self.executeSQL ( sql_create_incubators_table )
        
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
            # Migration 4: Add telephone column to users table
            self._migrate_users_add_telephone()
            # Migration 5: Migrate users from configuration file to database
            self._migrate_users_from_config()
            # Migration 6: Migrate incubators from configuration file to database
            self._migrate_incubators_from_config()
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
    
    def _migrate_users_add_telephone(self):
        """
        Add telephone column to users table if it doesn't exist.
        """
        try:
            # Check if telephone column already exists
            check_columns = f"PRAGMA table_info({self._users_table_name})"
            table_info = self.executeSQL(check_columns)
            
            if not isinstance(table_info, list):
                # Table might not exist yet, let the regular creation handle it
                return
            
            # Check if telephone column exists
            has_telephone_column = any(col[1] == 'telephone' for col in table_info)
            
            if not has_telephone_column:
                logging.info("Adding telephone column to users table")
                
                # Add the telephone column
                sql_add_column = f"ALTER TABLE {self._users_table_name} ADD COLUMN telephone TEXT"
                self.executeSQL(sql_add_column)
                
                logging.info("Successfully added telephone column to users table")
                
        except Exception as e:
            logging.error(f"Error migrating users table (adding telephone): {e}")
    
    def _migrate_users_from_config(self):
        """
        Migrate users from configuration file to database if database is empty.
        """
        try:
            # Check if we already have users in the database
            existing_users = self.executeSQL(f"SELECT COUNT(*) as count FROM {self._users_table_name}")
            
            if isinstance(existing_users, list) and len(existing_users) > 0:
                user_count = existing_users[0][0] if hasattr(existing_users[0], '__getitem__') else existing_users[0]['count']
                if user_count > 0:
                    logging.info(f"Users table already has {user_count} users, skipping migration from config")
                    return
            
            # Try to import users from configuration
            from ethoscope_node.utils.configuration import EthoscopeConfiguration
            
            try:
                config = EthoscopeConfiguration()
                config_users = config.content.get('users', {})
                
                if not config_users:
                    logging.info("No users found in configuration file")
                    return
                
                migrated_count = 0
                for username, user_data in config_users.items():
                    try:
                        # Map configuration fields to database fields
                        db_user_data = {
                            'username': user_data.get('name', username),
                            'fullname': user_data.get('fullname', ''),
                            'pin': str(user_data.get('PIN', '')),
                            'email': user_data.get('email', ''),
                            'telephone': user_data.get('telephone', ''),
                            'labname': user_data.get('group', ''),
                            'active': 1 if user_data.get('active', True) else 0,
                            'isadmin': 1 if user_data.get('isAdmin', False) else 0,
                            'created': user_data.get('created', datetime.datetime.now().timestamp())
                        }
                        
                        # Insert user into database
                        result = self.addUser(**db_user_data)
                        if result > 0:
                            migrated_count += 1
                            logging.info(f"Migrated user: {db_user_data['username']}")
                        
                    except Exception as e:
                        logging.error(f"Error migrating user {username}: {e}")
                        continue
                
                if migrated_count > 0:
                    logging.info(f"Successfully migrated {migrated_count} users from configuration to database")
                else:
                    logging.info("No users were migrated from configuration")
                    
            except ImportError as e:
                logging.warning(f"Could not import configuration module for user migration: {e}")
            except Exception as e:
                logging.error(f"Error reading configuration file for user migration: {e}")
                
        except Exception as e:
            logging.error(f"Error during user migration from config: {e}")
    
    def _migrate_incubators_from_config(self):
        """
        Migrate incubators from configuration file to database if database is empty.
        """
        try:
            # Check if we already have incubators in the database
            existing_incubators = self.executeSQL(f"SELECT COUNT(*) as count FROM {self._incubators_table_name}")
            
            if isinstance(existing_incubators, list) and len(existing_incubators) > 0:
                incubator_count = existing_incubators[0][0] if hasattr(existing_incubators[0], '__getitem__') else existing_incubators[0]['count']
                if incubator_count > 0:
                    logging.info(f"Incubators table already has {incubator_count} incubators, skipping migration from config")
                    return
            
            # Try to import incubators from configuration
            from ethoscope_node.utils.configuration import EthoscopeConfiguration
            
            try:
                config = EthoscopeConfiguration()
                config_incubators = config.content.get('incubators', {})
                
                if not config_incubators:
                    logging.info("No incubators found in configuration file")
                    return
                
                migrated_count = 0
                for incubator_key, incubator_data in config_incubators.items():
                    try:
                        # Map configuration fields to database fields
                        db_incubator_data = {
                            'name': incubator_data.get('name', incubator_key),
                            'location': incubator_data.get('location', ''),
                            'owner': incubator_data.get('owner', ''),
                            'description': incubator_data.get('description', ''),
                            'created': datetime.datetime.now().timestamp(),
                            'active': 1
                        }
                        
                        # Insert incubator into database
                        result = self.addIncubator(**db_incubator_data)
                        if result > 0:
                            migrated_count += 1
                            logging.info(f"Migrated incubator: {db_incubator_data['name']}")
                        
                    except Exception as e:
                        logging.error(f"Error migrating incubator {incubator_key}: {e}")
                        continue
                
                if migrated_count > 0:
                    logging.info(f"Successfully migrated {migrated_count} incubators from configuration to database")
                else:
                    logging.info("No incubators were migrated from configuration")
                    
            except ImportError as e:
                logging.warning(f"Could not import configuration module for incubator migration: {e}")
            except Exception as e:
                logging.error(f"Error reading configuration file for incubator migration: {e}")
                
        except Exception as e:
            logging.error(f"Error during incubator migration from config: {e}")

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
    
    def addUser(self, username: str, fullname: str = "", pin: str = "", email: str = "", 
                telephone: str = "", labname: str = "", active: int = 1, isadmin: int = 0, created: float = None):
        """
        Add a new user to the database.
        
        Args:
            username: Username (required)
            fullname: Full name of the user
            pin: User's PIN code
            email: Email address (required)
            telephone: Phone number
            labname: Laboratory/group name
            active: Whether user is active (1) or not (0)
            isadmin: Whether user is admin (1) or not (0)
            created: Creation timestamp (uses current time if None)
            
        Returns:
            ID of the inserted user or -1 if error
        """
        if not username:
            logging.error("Username is required for adding user")
            return -1
            
        if not email:
            logging.error("Email is required for adding user")
            return -1
        
        if created is None:
            created = datetime.datetime.now().timestamp()
        
        try:
            # Check if username already exists
            existing = self.getUserByName(username)
            if existing:
                logging.error(f"User with username '{username}' already exists")
                return -1
            
            # Check if email already exists
            existing = self.getUserByEmail(email)
            if existing:
                logging.error(f"User with email '{email}' already exists")
                return -1
            
            # Escape single quotes in text fields
            escaped_username = username.replace("'", "''")
            escaped_fullname = fullname.replace("'", "''")
            escaped_pin = pin.replace("'", "''")
            escaped_email = email.replace("'", "''")
            escaped_telephone = telephone.replace("'", "''")
            escaped_labname = labname.replace("'", "''")
            
            sql_add_user = f"""
            INSERT INTO {self._users_table_name} 
            (username, fullname, pin, email, telephone, labname, active, isadmin, created) 
            VALUES ('{escaped_username}', '{escaped_fullname}', '{escaped_pin}', '{escaped_email}', 
                    '{escaped_telephone}', '{escaped_labname}', {active}, {isadmin}, '{created}')
            """
            
            result = self.executeSQL(sql_add_user)
            
            if result > 0:
                logging.info(f"Added new user: {username}")
            
            return result
            
        except Exception as e:
            logging.error(f"Error adding user {username}: {e}")
            return -1
    
    def updateUser(self, user_id: int = None, username: str = None, **updates):
        """
        Update an existing user in the database.
        
        Args:
            user_id: Database ID of user to update (either user_id or username required)
            username: Username of user to update (either user_id or username required)
            **updates: Fields to update (fullname, pin, email, telephone, labname, active, isadmin)
            
        Returns:
            Number of rows affected or -1 if error
        """
        if not user_id and not username:
            logging.error("Either user_id or username must be provided for updating user")
            return -1
        
        if not updates:
            logging.warning("No updates provided for user update")
            return 0
        
        try:
            # Build WHERE clause
            if user_id:
                where_clause = f"id = {user_id}"
            else:
                escaped_username = username.replace("'", "''")
                where_clause = f"username = '{escaped_username}'"
            
            # Build SET clause
            set_clauses = []
            for field, value in updates.items():
                if field in ['fullname', 'pin', 'email', 'telephone', 'labname']:
                    escaped_value = str(value).replace("'", "''")
                    set_clauses.append(f"{field} = '{escaped_value}'")
                elif field in ['active', 'isadmin']:
                    set_clauses.append(f"{field} = {int(value)}")
                elif field == 'created':
                    set_clauses.append(f"{field} = '{value}'")
                else:
                    logging.warning(f"Unknown field '{field}' in user update, skipping")
            
            if not set_clauses:
                logging.warning("No valid updates provided for user update")
                return 0
            
            sql_update_user = f"""
            UPDATE {self._users_table_name} 
            SET {', '.join(set_clauses)} 
            WHERE {where_clause}
            """
            
            result = self.executeSQL(sql_update_user)
            
            if result >= 0:
                identifier = f"ID {user_id}" if user_id else f"username {username}"
                logging.info(f"Updated user {identifier}")
            
            return result
            
        except Exception as e:
            identifier = f"ID {user_id}" if user_id else f"username {username}"
            logging.error(f"Error updating user {identifier}: {e}")
            return -1
    
    def deactivateUser(self, user_id: int = None, username: str = None):
        """
        Deactivate a user (set active=0) instead of deleting.
        
        Args:
            user_id: Database ID of user to deactivate (either user_id or username required)
            username: Username of user to deactivate (either user_id or username required)
            
        Returns:
            Number of rows affected or -1 if error
        """
        return self.updateUser(user_id=user_id, username=username, active=0)
    
    def getUserById(self, user_id: int, asdict: bool = False):
        """
        Get user information by database ID.
        
        Args:
            user_id: Database ID to look up
            asdict: Return as dictionary if True
            
        Returns:
            User data from database or empty dict if not found
        """
        sql_get_user = f"SELECT * FROM {self._users_table_name} WHERE id = {user_id}"
        
        row = self.executeSQL(sql_get_user)
        
        if type(row) != list or len(row) == 0:
            return {}
        
        if asdict:
            return dict(row[0])
        else:
            return row[0]
    
    def getAllUsers(self, active_only: bool = False, asdict: bool = False):
        """
        Get all users from the database.
        
        Args:
            active_only: If True, only return active users
            asdict: Return as dictionary if True
            
        Returns:
            List of user data or dictionary keyed by username
        """
        sql_get_users = f"SELECT * FROM {self._users_table_name}"
        
        if active_only:
            sql_get_users += " WHERE active = 1"
        
        sql_get_users += " ORDER BY username"
        
        rows = self.executeSQL(sql_get_users)
        
        if type(rows) != list:
            return {} if asdict else []
        
        if asdict:
            # Return dictionary keyed by username like the configuration format
            result = {}
            for row in rows:
                row_dict = dict(row)
                result[row_dict['username']] = row_dict
            return result
        else:
            return rows
    
    def addIncubator(self, name: str, location: str = "", owner: str = "", 
                     description: str = "", created: float = None, active: int = 1):
        """
        Add a new incubator to the database.
        
        Args:
            name: Incubator name (required, must be unique)
            location: Physical location of the incubator
            owner: Owner/responsible person for the incubator
            description: Description of the incubator
            created: Creation timestamp (uses current time if None)
            active: Whether incubator is active (1) or not (0)
            
        Returns:
            ID of the inserted incubator or -1 if error
        """
        if not name:
            logging.error("Name is required for adding incubator")
            return -1
        
        if created is None:
            created = datetime.datetime.now().timestamp()
        
        try:
            # Check if name already exists
            existing = self.getIncubatorByName(name)
            if existing:
                logging.error(f"Incubator with name '{name}' already exists")
                return -1
            
            # Escape single quotes in text fields
            escaped_name = name.replace("'", "''")
            escaped_location = location.replace("'", "''")
            escaped_owner = owner.replace("'", "''")
            escaped_description = description.replace("'", "''")
            
            sql_add_incubator = f"""
            INSERT INTO {self._incubators_table_name} 
            (name, location, owner, description, created, active) 
            VALUES ('{escaped_name}', '{escaped_location}', '{escaped_owner}', 
                    '{escaped_description}', '{created}', {active})
            """
            
            result = self.executeSQL(sql_add_incubator)
            
            if result > 0:
                logging.info(f"Added new incubator: {name}")
            
            return result
            
        except Exception as e:
            logging.error(f"Error adding incubator {name}: {e}")
            return -1
    
    def updateIncubator(self, incubator_id: int = None, name: str = None, **updates):
        """
        Update an existing incubator in the database.
        
        Args:
            incubator_id: Database ID of incubator to update (either incubator_id or name required)
            name: Name of incubator to update (either incubator_id or name required)
            **updates: Fields to update (location, owner, description, active)
            
        Returns:
            Number of rows affected or -1 if error
        """
        if not incubator_id and not name:
            logging.error("Either incubator_id or name must be provided for updating incubator")
            return -1
        
        if not updates:
            logging.warning("No updates provided for incubator update")
            return 0
        
        try:
            # Build WHERE clause
            if incubator_id:
                where_clause = f"id = {incubator_id}"
            else:
                escaped_name = name.replace("'", "''")
                where_clause = f"name = '{escaped_name}'"
            
            # Build SET clause
            set_clauses = []
            for field, value in updates.items():
                if field in ['name', 'location', 'owner', 'description']:
                    escaped_value = str(value).replace("'", "''")
                    set_clauses.append(f"{field} = '{escaped_value}'")
                elif field in ['active']:
                    set_clauses.append(f"{field} = {int(value)}")
                elif field == 'created':
                    set_clauses.append(f"{field} = '{value}'")
                else:
                    logging.warning(f"Unknown field '{field}' in incubator update, skipping")
            
            if not set_clauses:
                logging.warning("No valid updates provided for incubator update")
                return 0
            
            sql_update_incubator = f"""
            UPDATE {self._incubators_table_name} 
            SET {', '.join(set_clauses)} 
            WHERE {where_clause}
            """
            
            result = self.executeSQL(sql_update_incubator)
            
            if result >= 0:
                identifier = f"ID {incubator_id}" if incubator_id else f"name {name}"
                logging.info(f"Updated incubator {identifier}")
            
            return result
            
        except Exception as e:
            identifier = f"ID {incubator_id}" if incubator_id else f"name {name}"
            logging.error(f"Error updating incubator {identifier}: {e}")
            return -1
    
    def deactivateIncubator(self, incubator_id: int = None, name: str = None):
        """
        Deactivate an incubator (set active=0) instead of deleting.
        
        Args:
            incubator_id: Database ID of incubator to deactivate (either incubator_id or name required)
            name: Name of incubator to deactivate (either incubator_id or name required)
            
        Returns:
            Number of rows affected or -1 if error
        """
        return self.updateIncubator(incubator_id=incubator_id, name=name, active=0)
    
    def getIncubatorById(self, incubator_id: int, asdict: bool = False):
        """
        Get incubator information by database ID.
        
        Args:
            incubator_id: Database ID to look up
            asdict: Return as dictionary if True
            
        Returns:
            Incubator data from database or empty dict if not found
        """
        sql_get_incubator = f"SELECT * FROM {self._incubators_table_name} WHERE id = {incubator_id}"
        
        row = self.executeSQL(sql_get_incubator)
        
        if type(row) != list or len(row) == 0:
            return {}
        
        if asdict:
            return dict(row[0])
        else:
            return row[0]
    
    def getIncubatorByName(self, name: str, asdict: bool = False):
        """
        Get incubator information by name.
        
        Args:
            name: Name to look up
            asdict: Return as dictionary if True
            
        Returns:
            Incubator data from database or empty dict if not found
        """
        sql_get_incubator = "SELECT * FROM %s WHERE name = '%s'" % (self._incubators_table_name, name)
        
        row = self.executeSQL(sql_get_incubator)
        
        if type(row) != list or len(row) == 0:
            return {}
        
        if asdict:
            return dict(row[0])
        else:
            return row[0]
    
    def getAllIncubators(self, active_only: bool = False, asdict: bool = False):
        """
        Get all incubators from the database.
        
        Args:
            active_only: If True, only return active incubators
            asdict: Return as dictionary if True
            
        Returns:
            List of incubator data or dictionary keyed by name
        """
        sql_get_incubators = f"SELECT * FROM {self._incubators_table_name}"
        
        if active_only:
            sql_get_incubators += " WHERE active = 1"
        
        sql_get_incubators += " ORDER BY name"
        
        rows = self.executeSQL(sql_get_incubators)
        
        if type(rows) != list:
            return {} if asdict else []
        
        if asdict:
            # Return dictionary keyed by name like the configuration format
            result = {}
            for row in rows:
                row_dict = dict(row)
                result[row_dict['name']] = row_dict
            return result
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
        
        # Use proper parameter binding to avoid formatting issues
        sql_log_alert = """
        INSERT INTO alert_logs (device_id, alert_type, run_id, message, recipients, created_at, updated_at) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (device_id, alert_type, run_id, message, recipients, timestamp, timestamp)
        
        return self.executeSQL(sql_log_alert, params)
    
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
            if run_id:
                sql_check_alert = """
                SELECT COUNT(*) as count FROM alert_logs 
                WHERE device_id = ? AND alert_type = ? AND run_id = ?
                """
                params = (device_id, alert_type, run_id)
            else:
                sql_check_alert = """
                SELECT COUNT(*) as count FROM alert_logs 
                WHERE device_id = ? AND alert_type = ? AND run_id IS NULL
                """
                params = (device_id, alert_type)
            
            result = self.executeSQL(sql_check_alert, params)
            
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
    
    def cleanup_stale_busy_devices(self, timeout_minutes: int = 10) -> int:
        """
        Clean up devices that are marked as 'busy' but haven't been seen recently.
        
        Args:
            timeout_minutes: Minutes after which a busy device is considered stale
            
        Returns:
            Number of devices that were cleaned up
        """
        cutoff_date = datetime.datetime.now() - datetime.timedelta(minutes=timeout_minutes)
        cutoff_timestamp = cutoff_date.timestamp()
        
        # Get all devices with status 'busy'
        sql_get_busy = "SELECT ethoscope_id, last_seen FROM %s WHERE status = 'busy'" % self._ethoscopes_table_name
        
        busy_devices = self.executeSQL(sql_get_busy)
        if not isinstance(busy_devices, list):
            return 0
        
        devices_to_cleanup = []
        
        for device in busy_devices:
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
                            # If all parsing fails, consider it for cleanup
                            devices_to_cleanup.append(ethoscope_id)
                            continue
                else:
                    # Try as numeric timestamp
                    last_seen_dt = datetime.datetime.fromtimestamp(float(last_seen))
                
                # Check if device should be cleaned up
                if last_seen_dt.timestamp() < cutoff_timestamp:
                    devices_to_cleanup.append(ethoscope_id)
                    
            except Exception as e:
                # If any parsing fails, consider device for cleanup
                logging.warning(f"Failed to parse timestamp for busy device {ethoscope_id}: {e}")
                devices_to_cleanup.append(ethoscope_id)
        
        # Clean up the devices by marking them as offline
        cleaned_count = 0
        for ethoscope_id in devices_to_cleanup:
            sql_cleanup = "UPDATE %s SET status = 'offline' WHERE ethoscope_id = '%s'" % (
                self._ethoscopes_table_name, ethoscope_id
            )
            
            result = self.executeSQL(sql_cleanup)
            if result != -1:
                cleaned_count += 1
            else:
                logging.error(f"Failed to cleanup busy device {ethoscope_id}")
        
        if cleaned_count > 0:
            logging.info(f"Cleaned up {cleaned_count} stale busy devices (busy for >{timeout_minutes} minutes)")
        else:
            logging.info(f"No stale busy devices found to cleanup (busy for >{timeout_minutes} minutes)")
        
        return cleaned_count
    
    def cleanup_offline_busy_devices(self, threshold_hours: int = 2) -> int:
        """
        Clean up devices that are marked as 'busy' or 'unreached' but haven't been seen for hours 
        (indicating they're actually offline or orphaned entries).
        
        Args:
            threshold_hours: Hours after which a busy/unreached device is considered offline
            
        Returns:
            Number of devices that were cleaned up
        """
        cutoff_date = datetime.datetime.now() - datetime.timedelta(hours=threshold_hours)
        cutoff_timestamp = cutoff_date.timestamp()
        
        # Get all devices with status 'busy' or 'unreached'
        sql_get_devices = "SELECT ethoscope_id, ethoscope_name, last_seen, status FROM %s WHERE status IN ('busy', 'unreached')" % self._ethoscopes_table_name
        
        devices = self.executeSQL(sql_get_devices)
        if not isinstance(devices, list):
            return 0
        
        devices_to_cleanup = []
        
        for device in devices:
            ethoscope_id = device[0]
            ethoscope_name = device[1]
            last_seen = device[2]
            status = device[3]
            
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
                            # If all parsing fails, consider it for cleanup
                            devices_to_cleanup.append((ethoscope_id, ethoscope_name, status))
                            continue
                else:
                    # Try as numeric timestamp
                    last_seen_dt = datetime.datetime.fromtimestamp(float(last_seen))
                
                # Check if device should be cleaned up
                if last_seen_dt.timestamp() < cutoff_timestamp:
                    devices_to_cleanup.append((ethoscope_id, ethoscope_name, status))
                    
            except Exception as e:
                # If any parsing fails, consider device for cleanup
                logging.warning(f"Failed to parse timestamp for {status} device {ethoscope_id}: {e}")
                devices_to_cleanup.append((ethoscope_id, ethoscope_name, status))
        
        # Clean up the devices by marking them as offline
        cleaned_count = 0
        busy_count = 0
        unreached_count = 0
        
        for ethoscope_id, ethoscope_name, status in devices_to_cleanup:
            sql_cleanup = "UPDATE %s SET status = 'offline' WHERE ethoscope_id = '%s'" % (
                self._ethoscopes_table_name, ethoscope_id
            )
            
            result = self.executeSQL(sql_cleanup)
            if result != -1:
                cleaned_count += 1
                if status == 'busy':
                    busy_count += 1
                elif status == 'unreached':
                    unreached_count += 1
                logging.info(f"Cleaned up {status} device: {ethoscope_name} ({ethoscope_id})")
            else:
                logging.error(f"Failed to cleanup {status} device {ethoscope_id}")
        
        if cleaned_count > 0:
            summary_parts = []
            if busy_count > 0:
                summary_parts.append(f"{busy_count} busy")
            if unreached_count > 0:
                summary_parts.append(f"{unreached_count} unreached")
            summary = " and ".join(summary_parts)
            logging.info(f"Cleaned up {cleaned_count} total devices ({summary}) not seen for >{threshold_hours} hours")
        else:
            logging.info(f"No stale devices found to cleanup (not seen for >{threshold_hours} hours)")
        
        return cleaned_count
        
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
        
            
