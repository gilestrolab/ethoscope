#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  users.py
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
import datetime
import string
import random
import pickle
import os
import secrets


__author__ = 'giorgio'
import multiprocessing
import sqlite3
import datetime
import logging, traceback

class ExperimentalDB(multiprocessing.Process):
    
    
    _run_table_name = "runs"
    _db_name = "/etc/ethoscope-node.db"
    #_db_name = "/tmp/ethoscope-node.db"
    #_db_name = ":memory:"
    
    def __init__(self):
        self.create_tables()


    def executeSQL(self, command):
        """
        """
        lid = 0
        try:
            db = sqlite3.connect(self._db_name)
            
            if command.startswith("SELECT"):
                db.row_factory = sqlite3.Row

            try:
                #print ('executing command: \n %s' % command) 
                c = db.cursor()
                c.execute(command)
                
                lid = c.lastrowid # the last id inserted / 0 if not an INSERT command
                #print ('last inserted row was %s' % lid)
                
                rows = c.fetchall() # return the result of a SELECT query / [] if not a SELECT query
                #print ('select entries are %s' % rows)
                
                db.commit()
                db.close()

            except Exception as e:
                logging.error(traceback.format_exc())
                return -1

        except:
            logging.error("Cannot connect to the experimental database %s." % self._db_name)
            return -1
            
        return lid or rows or 0
    
    
    def create_tables(self):
        """
        Create the necessary tables in the database if they do not exist.
        """
        
        sql_create_experiments_table = """CREATE TABLE IF NOT EXISTS %s (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                run_id TEXT NOT NULL,
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
                            );""" % self._run_table_name

        self.executeSQL ( sql_create_experiments_table )

    def getRun (self, run_id, asdict=False):
        """
        Gather experiment with given ID
        """
        
        sql_get_experiment = "SELECT * FROM %s WHERE run_id = '%s'" % (self._run_table_name, run_id)
        row = self.executeSQL(sql_get_experiment)
        
        if asdict:
            keys = row[0].keys()
            return [dict([(key, value) for key, value in zip(keys, line)]) for line in row]
            
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
        
        sql_enter_new_experiment = "INSERT INTO %s VALUES( NULL, '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s')" % ( self._run_table_name, run_id, experiment_type, ethoscope_name, ethoscope_id, username, user_id, location, start_time, end_time, alert, problems, experimental_data, comments, status)
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
        
        sql_update_experiment = "UPDATE %s SET end_time = '%s', status = '%s' WHERE run_id = '%s'" % ( self._run_table_name, end_time, status, run_id )
        self.executeSQL(sql_update_experiment)
        return self.getRun(run_id)[0]['status']
            

    def flagProblem (self, run_id, message=""):
        '''
        '''
        ct = datetime.datetime.now()

        problems = self.getRun(run_id)[0]['problems']
        problems += "%s, %s;" % (ct, message)
        sql_update_experiment = "UPDATE %s SET problems = '%s', WHERE run_id = %s" % ( self._run_table_name, problems, run_id )
        return self.getRun(run_id)[0]['problems']
        
        
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
        edb = ExperimentalDB()
        run_id = secrets.token_hex(8)
        edb.addRun(run_id, "tracking", "ethoscope_101", secrets.token_hex(8), "ggilestro", 101, "Home", True, "", "")
        
        
        print ("added row: ", edb.getRun(run_id))
        ro = edb.stopRun(run_id)
        print ("stopped row: ", ro)
            
