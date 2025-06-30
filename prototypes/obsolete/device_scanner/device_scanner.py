from threading import Thread
import urllib.request, urllib.error, urllib.parse
import os
import datetime
import json
import time
import logging
import traceback
from functools import wraps

class ScanException(Exception):
    pass


def retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    """
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return f_retry
    return deco_retry



class DeviceScanner(Thread):
    def __init__(self, local_ip = "192.169.123.1", ip_range = (6,8)):
        self._is_active = True
        self._devices = {}
        self._device_id_map = {}
        for i in range(ip_range[0], ip_range[1] + 1):
            subnet_ip = local_ip.split(".")[0:3]
            subnet_ip = ".".join(subnet_ip)
            ip = "%s.%i" % (subnet_ip, i)
            self._devices[ip] = Device(ip)
            self._devices[ip].start()

        super(DeviceScanner, self).__init__()

    def run(self):
        while self._is_active :
            time.sleep(1)
            for d in list(self._devices.values()):
                id = d["id"]
                if id:
                    self._device_id_map[id] = d

    def get_device(self, id):
        try:
            self._device_id_map[id]
        except KeyError:
            raise KeyError("No such device: %s" % id)


    def stop(self):
        for i,d in self._devices.items():
            d.stop()
        self._is_active = False

class Device(Thread):
    _ethoscope_db_credentials = {"user": "ethoscope",
                                "passwd": "ethoscope",
                                "db":"ethoscope_db"}
    _result_main_dir = "/ethoscope_results/"
    _id_page = "id"
    _user_options_page = "user_options"
    _static_page = "static"
    def __init__(self,ip, port = 9000):

        self._ip = ip
        self._port = port
        self._id_url = "http://%s:%i/%s" % (ip, port, self._id_page)
        self._user_options_url= "http://%s:%i/%s" % (ip, port, self._user_options_page)
        self._id = ""
        self._info = {}
        self._is_active = True
        super(Device,self).__init__()

    def run(self):
        while self._is_active:
            time.sleep(5)
            self._update_info()

    def data(self):
        return self._info

    def user_options(self):
        return self._get_json(self._user_options_url)
    def last_image(self):
        try:
            img_path = self._info["last_drawn_img"]
        except KeyError:
            raise KeyError("Cannot find last image for device %s" % self._id)

        img_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._static_page, img_path)
        file_like = urllib.request.urlopen(img_url)
        return file_like

    @retry(ScanException, tries=3, delay=1, backoff=1)
    def _get_json(self, url,timeout=2):

        try:
            req = urllib.request.Request(url)
            f = urllib.request.urlopen(req, timeout=timeout)
            message = f.read()

            if not message:
                # logging.error("URL error whist scanning url: %s. No message back." % self._id_url)
                raise ScanException("No message back")
            try:
                resp = json.loads(message)
                return resp
            except ValueError:
                # logging.error("Could not parse response from %s as JSON object" % self._id_url)
                raise ScanException("Could not parse Json object")
        except urllib.error.URLError as e:
            raise ScanException(str(e))
        except Exception as e:
            raise ScanException("Unexpected error" + str(e))


    def _update_id(self):
        old_id = self._id
        resp = self._get_json(self._id_url)
        self._id = resp['id']
        if self._id != old_id:
            logging.warning("Device id changed!")
            self._info = {}

    def _update_info(self):

        try:
            #todo what happens when change of id for same ip ?

            self._update_id()
            self._data_url = "http://%s:%i/data/%s" % (self._ip, self._port, self._id)
            resp = self._get_json(self._data_url)
            self._info.update(resp)
            resp = self._make_backup_path(self._result_main_dir)
            self._info.update(resp)
        except ScanException:
            pass

    def _make_backup_path(self, result_main_dir, timeout=30):

        try:
            import mysql.connector
            device_id = self._info["id"]
            device_name = self._info["name"]
            com = "SELECT value from METADATA WHERE field = 'date_time'"

            mysql_db = mysql.connector.connect(host=self._ip,
                                       connect_timeout=timeout,
                                       **self._ethoscope_db_credentials)
            cur = mysql_db.cursor()
            cur.execute(com)
            query = [c for c in cur]
            timestamp = float(query[0][0])
            mysql_db.close()
            date_time = datetime.datetime.fromtimestamp(timestamp)
            formatted_time = date_time.strftime('%Y-%m-%d_%H-%M-%S')
            file_name = "%s_%s.db" % (formatted_time, device_id)
            output_db_file = os.path.join(result_main_dir,
                                          device_id,
                                          device_name,
                                          formatted_time,
                                          file_name
                                          )

        except Exception as e:
            logging.error("Could not generate backup path for device. Probably a MySQL issue")
            logging.error(traceback.format_exc())
            return {}

        return {"backup_path": output_db_file}

    def stop(self):
        self._is_active = False

scan = DeviceScanner()
scan.start()

try:
    while True:
        time.sleep(1)
finally:
    scan.stop()




