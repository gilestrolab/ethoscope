from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError

import os
import logging
import time
import multiprocessing
import traceback

import urllib.request
import json

import threading

def receive_devices(server = "localhost"):
    '''
    Interrogates the NODE on its current knowledge of devices
    '''
    url = "http://%s/devices" % server
    devices = []
    
    try:
        req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})            
        f = urllib.request.urlopen(req, timeout=10)
        devices = json.load(f)
        return devices

    except:
        logging.error("The node ethoscope server %s is not running or cannot be reached. A list of available ethoscopes could not be found." % server)
        return
        #logging.error(traceback.format_exc())
        

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


    def run(self):
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

        except DBNotReadyError as e:
            logging.warning(e)
            logging.warning("Database %s on IP %s not ready, will try later" % (self._db_credentials["name"], self._database_ip) )
            pass

        except Exception as e:
            logging.error(traceback.format_exc())


class GenericBackupWrapper(threading.Thread):
    def __init__(self, results_dir, safe, node_address):
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._results_dir = results_dir
        self._safe = safe
        self._node_address = node_address
        self.devices_to_backup = []

        super(GenericBackupWrapper, self).__init__()
            

    def _backup_job(self, args):
        '''
        '''
        try:
            device_info, results_dir = args
            logging.info("Initiating backup for device  %s" % device_info["id"])
            
            backup_job = BackupClass(device_info, results_dir=results_dir)

            logging.info("Running backup for device  %s" % device_info["id"])
            self.devices_to_backup['id'] = {'started': int(time.time()), 'ended' : 0 }

            backup_job.run()

            logging.info("Backup done for for device  %s" % device_info["id"])
            self.devices_to_backup['id']['ended'] = datetime.datetime.now()

            return 1
            
        except Exception as e:
            logging.error("Unexpected error in backup. args are: %s" % str(args))
            logging.error(traceback.format_exc())
            return

    def get_devices(self):
        '''
        '''
        
        logging.info("Updating list of devices")
        devices = receive_devices(self._node_address)
        
        if not devices:
            logging.info("Using Ethoscope Scanner to look for devices")

            self._device_scanner = EthoscopeScanner()
            self._device_scanner.start()
            time.sleep(20)
            self._device_scanner.stop()
            del self._device_scanner
            
        return devices

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
            devices = self.get_devices()

            if not devices:
                devices = self._device_scanner.get_all_devices_info()

            self._devices_information = [ (d, self._results_dir) for d in list(devices.values()) 
                                        if (d["status"] not in ["not_in_use", "offline"] and d["name"] != "ETHOSCOPE_000")
                                     ]
            
            ids_to_backup = [d[0]['id'] for d in self._devices_information]
            
            logging.info("Found %s devices online: %s" % (
                              len(self._devices_information),
                              ', '.join( ids_to_backup )
                              )
                         )
                         
            self.devices_to_backup = {}.fromkeys(ids_to_backup, {'started': 0, 'ended' : 0 })

            if self._safe:
                logging.info("Safe mode set to True: processing backups one by one.")
                for dtb in self._devices_information:
                    self._backup_job(dtb)

            else:
                logging.info("Safe mode set to False: processing all backups at once.")
                pool = multiprocessing.Pool(4)
                _ = pool.map(self._backup_job, self._devices_information)
                pool.close()
                pool.join()
                
            t1 = time.time()
            logging.info("Backup finished at t=%i" % t1)
            t0 = t1

