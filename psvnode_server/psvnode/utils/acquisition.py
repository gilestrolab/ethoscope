import time
import datetime
import logging
import os
from threading import Thread
from mysql_backup import MySQLdbToSQlite, DBNotReadyError
import json
import urllib2
import traceback

class Acquisition(Thread):
    _db_credentials = {
            "name":"psv_db",
            "user":"psv",
            "password":"psv"
        }


    _delay_between_updates = 5 # seconds


    def __init__(self, device_info, result_main_dir="/psv_results/"):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])

        date_time = datetime.datetime.fromtimestamp(int(self._device_info["time"]))


        formated_time = date_time.strftime('%Y-%m-%d_%H:%M:%S')
        device_name = self._device_info["id"]
        self._file_name = "%s_%s.db" % (formated_time, device_name)

        self._output_db_file = os.path.join(result_main_dir,
                                            device_name,
                                            formated_time,
                                            self._file_name
                                            )

        self._force_stop = False


        logging.info("Linking%s, %s\n\tsaving at '%s'" % (device_name, self._database_ip, self._output_db_file))

        # fixme THIS SHOULD BE a different LOG FILE **PER ACQUISITION**/ or we should format log accordingly
        # the latter solution is prob better actually! so we have a global log for server and no need to link it in different thread
        # also, the next few lines are in order to reset log file, we don't need that anymore, do we ?
        # to discuss also, do we give the lig to the user?
        self._info={"log_file":"/tmp/node.log"}

        # logging.basicConfig(filename=self._info['log_file'], level=logging.INFO)
        #
        # logger = logging.getLogger()
        # logger.handlers[0].stream.close()
        # logger.removeHandler(logger.handlers[0])
        #
        # file_handler = logging.FileHandler(self._info["log_file"])
        # file_handler.setLevel(logging.INFO)
        # formatter = logging.Formatter("%(asctime)s %(filename)s, %(lineno)d, %(funcName)s: %(message)s")
        # file_handler.setFormatter(formatter)
        # logger.addHandler(file_handler)

        super(Acquisition, self).__init__()

    def _update_device_info(self, what="data", port=9000):
        try:
            ip = self._device_info["ip"]
            id = self._device_info["id"]

            request_url = "{ip}:{port}/{what}/{id}".format(ip=ip,port=port,what=what,id=id)
            req = urllib2.Request(url=request_url, headers={'Content-Type': 'application/json'})
            f = urllib2.urlopen(req)
            message = f.read()

            if message:
                data = json.loads(message)
                self._device_info.update(data)
        except Exception as e:
            logging.error(traceback.format_exc(e))

    def run(self):


        t0 = time.time()
        mirror = None

        while not self._force_stop:
            try:
                time.sleep(.3)
                now = time.time()
                if now - t0 < self._delay_between_updates:
                    continue
                t0 = now
                self._update_device_info()
                if self._device_info["status"] != "running":
                    mirror = None
                    continue

                if mirror is None:
                    mirror= MySQLdbToSQlite(self._output_db_file, self._db_credentials["name"],
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
                raise e

    def __del__(self):
        logging.info("Stopping acquisition thread")
        self.stop()

    def stop(self):
        self._force_stop = True

