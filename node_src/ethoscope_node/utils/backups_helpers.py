__author__ = 'quentin'

from ethoscope_node.utils.helpers import generate_new_device_map, get_local_ip
import logging
import time
import  multiprocessing


class GenericBackupWrapper(object):
    def __init__(self,backup_job, result_dir,safe):
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._result_dir = result_dir
        self._local_ip = get_local_ip()
        self._safe = safe
        self._backup_job = backup_job


    def run(self):
        t0 = time.time()
        t1 = t0 + self._BACKUP_DT

        while True:
            if t1 - t0 < self._BACKUP_DT:
                t1 = time.time()
                time.sleep(self._TICK)
                continue

            logging.info("Starting backup")
            logging.info("Generating device map")
            dev_map = generate_new_device_map(self._local_ip, result_main_dir=self._result_dir)
            logging.info("Regenerated device map")
            if self._safe:
                map(self._backup_job, dev_map.values())
            else:
                pool = multiprocessing.Pool(4)
                _ = pool.map(self._backup_job, dev_map.values())
                logging.info("Pool mapped")
                pool.close()
                logging.info("Joining now")
                pool.join()
            t1 = time.time()
            logging.info("Backup finished at t=%i" % t1)
            t0 = t1


