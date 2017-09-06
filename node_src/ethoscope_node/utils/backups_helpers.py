__author__ = 'quentin'

from ethoscope_node.utils.helpers import  get_local_ip
from ethoscope_node.utils.device_scanner import DeviceScanner


import logging
import time
import  multiprocessing
import os
import glob

class GenericBackupWrapper(object):
    def __init__(self,
                 backup_job,
                 results_dir,
                 safe,
                 remote_dir = None,
                 local_ip = "192.169.123.1"):
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._ARCHIVE_DT = 8 * 60 *  60  # 6h # send to remote every 6h
        self._results_dir = results_dir
        self._remote_dir = remote_dir
        self._safe = safe
        self._backup_job = backup_job
        self._device_scanner = DeviceScanner(local_ip, device_refresh_period=60, results_dir=self._results_dir)
        for d in self._device_scanner.get_all_devices_info():
            d._update_info()

    def __del__(self):
        if self._device_scanner._is_active:
            self._device_scanner.stop()

    def archive_results(self):
        command = "rsync -avrz %s/ %s/%s/ --whole-file --exclude=*.txt --exclude=*.db.*" % (self._results_dir,
                                                                                          self._remote_dir,
                                                                                          self._results_dir)
        os.system(command)
        idx_path = os.path.join(self._results_dir, "index.txt")

        command = "rsync -v %s %s/%s/ " % (idx_path,
                                            self._remote_dir,
                                            self._results_dir)
        os.system(command)


    def index_file(self, basename="index.txt"):
        idx_path = os.path.join(self._results_dir, basename)
        with open(idx_path,"w") as f:
            for x in sorted(os.walk(self._results_dir)):
                for abs_path in glob.glob(os.path.join(x[0], "*.*")):
                    rel_path = os.path.relpath(abs_path, start=self._results_dir)
                    size = os.stat(abs_path).st_size
                    f.write('"%s",%i\n' % (rel_path,size))

    def run(self):
        try:
            self._device_scanner.start()
            time.sleep(5)

            t0 = time.time()
            t1 = t0 + self._BACKUP_DT

            t0_archive = t0
            t1_archive = t0_archive + self._ARCHIVE_DT

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
                logging.info("Backup finished at t=%i" % t1)

                logging.info("Making index file")
                self.index_file()

                if t1_archive - t0_archive < self._ARCHIVE_DT:
                    t1_archive = time.time()
                    continue

                if self._remote_dir is not None:
                    logging.info("Syncing files to remote archive at t=%i" % t1)
                    try:
                        self.archive_results()
                    except Exception as e:
                        logging.error("Could not remote backup:")
                        logging.error(e)

                    t1_archive = time.time()
                    t0_archive = t1_archive


                t1 = time.time()
                t0 = t1


        finally:
            self._device_scanner.stop()
