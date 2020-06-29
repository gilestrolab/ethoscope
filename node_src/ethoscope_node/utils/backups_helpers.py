from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError

import os
import logging
import time
import multiprocessing
import traceback

import urllib.request
import json

def receive_devices(server = "localhost"):
    '''
    Interrogates the NODE on its current knowledge of devices, then extracts from the JSON record
    only the IPs
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
    _db_credentials = {
            "name":"ethoscope_db",
            "user":"ethoscope",
            "password":"ethoscope"
        }
    
    # #the db name is specific to the ethoscope being interrogated
    # #the user remotely accessing it is node/node
    
    # _db_credentials = {
            # "name":"ETHOSCOPE_000_db",
            # "user":"node",
            # "password":"node"
        # }
        
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

            mirror= MySQLdbToSQlite(backup_path, self._db_credentials["name"],
                            remote_host=self._database_ip,
                            remote_pass=self._db_credentials["password"],
                            remote_user=self._db_credentials["user"])

            mirror.update_roi_tables()

        except DBNotReadyError as e:
            logging.warning(e)
            logging.warning("Database %s on IP %s not ready, will try later" % (self._db_credentials["name"], self._database_ip) )
            pass

        except Exception as e:
            logging.error(traceback.format_exc())


class GenericBackupWrapper(object):
    def __init__(self, backup_job, results_dir, safe, server):
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._results_dir = results_dir
        self._safe = safe
        self._backup_job = backup_job
        self._server = server

        # for safety, starts device scanner too in case the node will go down at later stage
        self._device_scanner = EthoscopeScanner(results_dir = results_dir)
            
            


    def run(self):
        try:
            devices = receive_devices(self._server)
            
            if not devices:
                logging.info("Using Ethoscope Scanner to look for devices")
                self._device_scanner.start()
                time.sleep(20)

            t0 = time.time()
            t1 = t0 + self._BACKUP_DT

            while True:
                if t1 - t0 < self._BACKUP_DT:
                    t1 = time.time()
                    time.sleep(self._TICK)
                    continue

                logging.info("Starting backup")

                if not devices:
                    devices = self._device_scanner.get_all_devices_info()

                dev_list = str([d for d in sorted(devices.keys())])
                logging.info("device map is: %s" %dev_list)

                args = []
                for d in list(devices.values()):
                    if d["status"] not in ["not_in_use", "offline"]:
                        args.append((d, self._results_dir))

                logging.info("Found %s devices online" % len(args))

                if self._safe:
                    for arg in args:
                        self._backup_job(arg)

                    #map(self._backup_job, args)
                else:
                    pool = multiprocessing.Pool(4)
                    _ = pool.map(self._backup_job, args)
                    logging.info("Pool mapped")
                    pool.close()
                    logging.info("Joining now")
                    pool.join()
                t1 = time.time()
                logging.info("Backup finished at t=%i" % t1)
                t0 = t1

        finally:
            if not devices:
                self._device_scanner.stop()
