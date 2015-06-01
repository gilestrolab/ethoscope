__author__ = 'quentin'


from psvnode.utils.helpers import generate_new_device_map
from psvnode.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError
import logging
import optparse
import time
import  multiprocessing
import  traceback
import os

class BackupClass(object):
    _db_credentials = {
            "name":"psv_db",
            "user":"psv",
            "password":"psv"
        }


    _delay_between_updates = 5 * 60 # seconds
    _last_backup_timeout = 60*5 #seconds

    def __init__(self, device_info):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])

    def run(self):
        try:

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


        RESULTS_DIR = "/psv_results"
        SUBNET_DEVICE = b'wlan0'
        TICK = 1.0 #s
        BACKUP_DT = 10 # 5min
        if DEBUG:
            import getpass
            if getpass.getuser() == "quentin":
                SUBNET_DEVICE = b'enp3s0'


            if getpass.getuser() == "asterix":
                SUBNET_DEVICE = b'lo'
                RESULTS_DIR = "/data1/todel/psv_results"
        t0 = time.time()
        pool = multiprocessing.Pool(3)
        while True:
            time.sleep(TICK)
            t1 = time.time()

            if t1 - t0 < BACKUP_DT:
                continue

            logging.info("Starting backup")
            dev_map = generate_new_device_map(device=SUBNET_DEVICE)
            pool_res =  pool.map(backup_job, dev_map.values())
            t0 = t1

    except Exception as e:
        logging.error(traceback.format_exc(e))
