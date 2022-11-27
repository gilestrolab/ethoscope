from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError

import os
import logging
import time
import traceback

import urllib.request
import json

import threading

class BackupClass(object):
    '''
    The default backup class. Will connect to the ethoscope mysql and mirror its content into the local sqlite3
    '''
    
    _db_credentials = {
            "name":"ethoscope_db",
            "user":"ethoscope",
            "password":"ethoscope"
        }
    
    def __init__(self, device_info, results_dir):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])
        self._results_dir = results_dir


    def backup (self):
        try:
            if "backup_path" not in self._device_info:
                raise KeyError("Could not obtain device backup path for %s" % self._device_info["id"])

            if self._device_info["backup_path"] is None:
                raise ValueError("backup path is None for device %s" % self._device_info["id"])
            backup_path = os.path.join(self._results_dir, self._device_info["backup_path"])

            self._db_credentials["name"] = "%s_db" % self._device_info["name"]

            mirror = MySQLdbToSQlite(backup_path, self._db_credentials["name"],
                            remote_host=self._database_ip,
                            remote_pass=self._db_credentials["password"],
                            remote_user=self._db_credentials["user"])

            mirror.update_roi_tables()
            
            logging.info("Backup status for %s is %0.2f%%" %(self._device_info["id"], mirror.compare_databases() ))
            return True

        except DBNotReadyError as e:
            logging.warning(e)
            logging.warning("Database %s on IP %s not ready, will try later" % (self._db_credentials["name"], self._database_ip) )
            return False

        except Exception as e:
            logging.error(traceback.format_exc())
            return False


class GenericBackupWrapper(threading.Thread):
    def __init__(self, results_dir, node_address):
        '''
        '''
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._results_dir = results_dir
        self._node_address = node_address
        self.backup_status = {}

        super(GenericBackupWrapper, self).__init__()

    def find_devices(self, only_active=True):
        '''
        Interrogates the NODE on its current knowledge of devices
        '''
        url = "http://%s/devices" % self._node_address
        timeout = 10
        devices = {}
        
        try:
            req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})            
            f = urllib.request.urlopen(req, timeout=timeout)
            devices = json.load(f)

        except urllib.error.URLError as e:
            logging.error("The node ethoscope server %s is not running or cannot be reached. A list of available ethoscopes could not be found." % server)
            logging.info("Using Ethoscope Scanner to look for devices")

            _device_scanner = EthoscopeScanner()
            _device_scanner.start()
            time.sleep(timeout) #let's just wait a bit
            devices = _device_scanner.get_all_devices_info()
            del _device_scanner
                
        
        if only_active:
            return [ d for d in list( devices.values() ) if (d["status"] not in ["not_in_use", "offline"] and d["name"] != "ETHOSCOPE_000") ]
        
        return devices
            

    def _backup_job(self,  device_info):
        '''
        '''
        try:
            dev_id = device_info["id"]
            logging.info("Initiating backup for device  %s" % dev_id)
            
            backup_job = BackupClass(device_info, results_dir=self._results_dir)

            logging.info("Running backup for device  %s" % dev_id)
            self.backup_status[dev_id] = {'started': int(time.time()), 'ended' : 0 }

            if backup_job.backup():

                logging.info("Backup done for for device %s" % dev_id)
                self.backup_status[dev_id]['ended'] = int(time.time())
            else:
                logging.error("Problem backing up device %s" % dev_id)
                self.backup_status[dev_id]['ended'] = -1
            
            del backup_job
            return True
            
        except Exception as e:

            logging.error("Unexpected error in backup. args are: %s" % str(args))
            logging.error(traceback.format_exc())
            return False

    def run (self):
        '''
        '''
        
        t0 = time.time()
        t1 = t0 + self._BACKUP_DT

        while True:
            if t1 - t0 < self._BACKUP_DT:
                t1 = time.time()
                time.sleep(self._TICK)
                continue

            logging.info("Starting backup round")
            active_devices = self.find_devices()

            logging.info("Found %s devices online: %s" % (
                              len(active_devices),
                              ', '.join( [dev['id'] for dev in active_devices] )
                              ) )
            
            for dev in active_devices:
                if dev['id'] not in self.backup_status:
                    self.backup_status[dev['id']] = { 'started' : 0, 'ended' : 0 }
                self._backup_job (dev)
                
            t0 = t1 = time.time()
            logging.info("Backup finished at t=%i" % t1)
