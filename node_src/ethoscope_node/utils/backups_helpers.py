__author__ = 'quentin'

from ethoscope_node.utils.helpers import  get_local_ip
from ethoscope_node.utils.device_scanner import DeviceScanner


import logging
import time
import  multiprocessing


class GenericBackupWrapper(object):
    def __init__(self,backup_job, results_dir,safe, local_ip):
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._results_dir = results_dir
        self._safe = safe
        self._backup_job = backup_job
        local_ip = "192.169.123.1"
        self._device_scanner = DeviceScanner(local_ip, device_refresh_period=60, results_dir=self._results_dir)
        for d in self._device_scanner.get_all_devices_info():
            d._update_info()


    def run(self):
        try:
            self._device_scanner.start()
            time.sleep(5)
            t0 = time.time()
            t1 = t0 + self._BACKUP_DT

            while True:
                if t1 - t0 < self._BACKUP_DT:
                    t1 = time.time()
                    time.sleep(self._TICK)
                    continue

                logging.info("Starting backup")

                dev_map = self._device_scanner.get_all_devices_info()

                dev_list =  str([d for d in sorted(dev_map.keys())])
                logging.info("device map is: %s" %dev_list)

                args = []
                for d in dev_map.values():
                    if d["status"] != "not_in_use":
                        args.append((d, self._results_dir))

                if self._safe:
                    map(self._backup_job, args)
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
            self._device_scanner.stop()
