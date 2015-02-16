import time
import logging
import os
from threading import Thread
import traceback
from mysql_backup import MySQLdbToSQlite

class Acquisition(Thread):
    _db_credentials = {
            "name":"psv_db",
            "user":"psv",
            "password":"psv"
        }

    _delay_between_updates = 5 # seconds

    def __init__(self, url, id, result_main_dir="/psv_results/"):
        self.url = url
        self.id = id
        self._output_db_file = os.path.join(result_main_dir, self.id, self.id  + ".db")

        self._force_stop = False
        self.timeout = 10

        # fixme THIS SHOULD BE a different LOG FILE **PER ACQUISITION**/ or we should format log accordingly
        # the latter solution is prob better actually! so we have a global log for server and no need to link it in different thread
        # also, the next few lines are in order to reset log file, we don't need that anymore, do we ?
        # to discuss also, do we give the lig to the user?
        self._info={"log_file":"/tmp/node.log"}

        logging.basicConfig(filename=self._info['log_file'], level=logging.INFO)

        logger = logging.getLogger()
        logger.handlers[0].stream.close()
        logger.removeHandler(logger.handlers[0])

        file_handler = logging.FileHandler(self._info["log_file"])
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(filename)s, %(lineno)d, %(funcName)s: %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        super(Acquisition, self).__init__()

    def run(self):
        db_ip = os.path.basename(self.url)
        try:
            mirror= MySQLdbToSQlite(self._output_db_file, self._db_credentials["name"], remote_host=db_ip, remote_pass=self._db_credentials["password"], remote_user=self._db_credentials["user"])
            while not self._force_stop:
                time.sleep(self._delay_between_updates)
                mirror.update_roi_tables()
        except Exception as e:
            logging.error(traceback.format_exc(e))

    # let us ensure the garbage collector does its work
    def __del__(self):
        self.stop()

    def stop(self):
        self._force_stop = True

