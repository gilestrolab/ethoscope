import time
import datetime
import logging
import os
from psvnode.utils.helpers import which
import multiprocessing
import ctypes
from mysql_backup import MySQLdbToSQlite, DBNotReadyError
import json
import urllib2
import traceback

class Acquisition(multiprocessing.Process):
    _db_credentials = {
            "name":"psv_db",
            "user":"psv",
            "password":"psv"
        }


    _delay_between_updates = 60 * 5 # seconds
    #_delay_between_updates = 10 # seconds
    _last_backup_timeout = 30 #seconds

    def __init__(self, device_info, result_main_dir="/psv_results/"):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])

        date_time = datetime.datetime.fromtimestamp(int(self._device_info["time"]))


        formated_time = date_time.strftime('%Y-%m-%d_%H-%M-%S')
        device_id = self._device_info["id"]
        device_name = self._device_info["name"]
        self._file_name = "%s_%s.db" % (formated_time, device_id)

        self._output_db_file = os.path.join(result_main_dir,
                                            device_id,
                                            device_name,
                                            formated_time,
                                            self._file_name
                                            )

        self._force_stop = multiprocessing.Value(ctypes.c_int, False)



        logging.info("Linking%s, %s\n\tsaving at '%s'" % (device_id, self._database_ip, self._output_db_file))

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

            try:
                if not which("fping"):
                    raise Exception("fping not available")
                ping = os.system(" fping %s -t 50  > /dev/null 2>&1 " % os.path.basename(ip))
            except Exception as f:
                ping = 0
                logging.error("Could not ping. Assuming 'alive'")
                logging.error(traceback.format_exc(f))

            if ping != 0:
                raise Exception("Target device '%s' is not responding to ping" % ip)

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
        mirror = None
        has_been_running_once = False
        try:
            t0 = time.time() - self._delay_between_updates # so we do not wait until first backup
            while not self._force_stop.value:
                try:
                    time.sleep(.3)
                    now = time.time()
                    if now - t0 < self._delay_between_updates:
                        continue
                    t0 = now
                    self._update_device_info()
                    if self._device_info["status"] != "running" and self._device_info["status"] != "stopping":
                        mirror = None
                        t0 = time.time() - self._delay_between_updates
                        continue
                    has_been_running_once = True
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
                    self._force_stop.value = True

        except KeyboardInterrupt:
            logging.info("Keyboard interrupt: stopping backup")
        except Exception as e:
            logging.error("unhandled error in process")
            logging.error(traceback.format_exc(e))


        finally:
            try:
                print "has_been_running_once", has_been_running_once
                if not has_been_running_once:
                    logging.info("Device was not running; not trying last backup")
                    return

                logging.info("Try final mirroring of the DB")
                logging.info("Waiting for device to stop...")
                i = 0
                while i < self._last_backup_timeout:
                    time.sleep(1.0)
                    i += 1
                    self._update_device_info()
                    if self._device_info["status"] != "stopped":
                        continue

                    if mirror is None:
                        mirror= MySQLdbToSQlite(self._output_db_file, self._db_credentials["name"],
                            remote_host=self._database_ip,
                            remote_pass=self._db_credentials["password"],
                            remote_user=self._db_credentials["user"])
                    mirror.update_roi_tables()
                    logging.info("Success")
                    return
                raise Exception("Last backup timed out. Device did not stop, or could not reach device.")

            except Exception as f:
                logging.error(traceback.format_exc(f))

    def __del__(self):
        self._force_stop.value = True

    def stop(self):
        logging.info("Stopping acquisition thread")
        self._force_stop.value = True



