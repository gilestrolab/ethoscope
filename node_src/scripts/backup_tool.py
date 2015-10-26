__author__ = 'quentin'


from ethoscope_node.utils.helpers import generate_new_device_map
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError
import logging
import optparse
import time
import  multiprocessing
import  traceback
import os
import subprocess
import re

class BackupClass(object):
    _db_credentials = {
            "name":"ethoscope_db",
            "user":"ethoscope",
            "password":"ethoscope"
        }
    def __init__(self, device_info):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])

    def run(self):
        try:
            if self._device_info["backup_path"] is None:
                raise ValueError("backup path is None for device %s" % self._device_info["id"])

            mirror= MySQLdbToSQlite(self._device_info["backup_path"], self._db_credentials["name"],
                            remote_host=self._database_ip,
                            remote_pass=self._db_credentials["password"],
                            remote_user=self._db_credentials["user"])

            mirror.update_roi_tables()

        except DBNotReadyError as e:
            logging.warning(e)
            logging.warning("Database not ready, will try later")
            pass

        except Exception as e:
            logging.error(traceback.format_exc(e))

def backup_job(device_info):
    backup_job = BackupClass(device_info)
    backup_job.run()


if __name__ == '__main__':
    # TODO where to save the files and the logs

    logging.getLogger().setLevel(logging.INFO)

    try:

        parser = optparse.OptionParser()
        parser.add_option("-d", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")


        (options, args) = parser.parse_args()

        option_dict = vars(options)
        DEBUG = option_dict["debug"]


        RESULTS_DIR = "/ethoscope_results"
        #SUBNET_DEVICE = b'wlan0'

        p1 = subprocess.Popen(["ip", "link", "show"], stdout=subprocess.PIPE)
        network_devices, err = p1.communicate()

        wireless = re.search(r'[0-9]: (wl.*):', network_devices)
        if wireless is not None:
            SUBNET_DEVICE = wireless.group(1)
        else:
            logging.error("Not Wireless adapter has been detected. It is necessary for connect to Devices.")

        TICK = 1.0 #s
        BACKUP_DT = 5*60 # 5min
        if DEBUG:
            import getpass
            if getpass.getuser() == "quentin":
                SUBNET_DEVICE = b'enp3s0'


            if getpass.getuser() == "asterix":
                SUBNET_DEVICE = b'lo'
                RESULTS_DIR = "/data1/todel/psv_results"
        t0 = time.time()
        t1 = t0 + BACKUP_DT


        while True:
            if t1 - t0 < BACKUP_DT:
                t1 = time.time()
                time.sleep(TICK)
                continue

            logging.info("Starting backup")
            pool = multiprocessing.Pool(4)
            logging.info("Generating device map")
            dev_map = generate_new_device_map(device=SUBNET_DEVICE,result_main_dir=RESULTS_DIR)
            logging.info("Regenerated device map")
            pool_res =  pool.map(backup_job, dev_map.values())
            logging.info("Pool mapped")
            pool.close()
            logging.info("Joining now")
            pool.join()
            t1 = time.time()
            logging.info("Backup finished at t=%i" % t1)

            t0 = t1


    except Exception as e:
        logging.error(traceback.format_exc(e))
