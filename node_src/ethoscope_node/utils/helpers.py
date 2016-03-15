
import logging
import json
import  urllib2 as urllib2
import subprocess
import os
import traceback
import concurrent
import concurrent.futures as futures
from netifaces import ifaddresses, AF_INET
import datetime, time
import MySQLdb
from functools import wraps
import socket


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
                except ExceptionToCheck, e:
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return f_retry
    return deco_retry

class ScanException(Exception):
    pass


@retry(ScanException, tries=3,delay=1, backoff=1)
def scan_one_device(ip, timeout=3, port=9000, page="id"):
    """
    :param url: the url to parse
    :param timeout: the timeout of the url request
    :param port: the port to request
    :return: The message, parsed as dictionary. the "ip" field is also added to the result.
    If the url could not be reached/parsed, (None,None) is returned
    """


    url="%s:%i/%s" % (ip, port, page)
    try:
        req = urllib2.Request(url)
        f = urllib2.urlopen(req, timeout=timeout)
        message = f.read()

        if not message:
            logging.error("URL error whist scanning url: %s. No message back." % url )
            raise ScanException("No message back")
        try:
            resp = json.loads(message)
            return (resp['id'],ip)
        except ValueError:
            logging.error("Could not parse response from %s as JSON object" % url )
            raise ScanException("Could not parse Json object")
    except urllib2.URLError as e:
        raise ScanException(str(e))
    except Exception as e:
        raise ScanException("Unexpected error" + str(e))



@retry(ScanException, tries=3,delay=3, backoff=1)
def update_dev_map_wrapped (devices_map,id, what="data",type=None, port=9000, data=None,
                           result_main_dir="/ethoscope_results",timeout=5):
    """
    Just a routine to format our GET urls. This improves readability whilst allowing us to change convention (e.g. port) without rewriting everything.

    :param id: machine unique identifier
    :param what: e.g. /data, /control
    :param type: the type of request for POST
    :param port:
    :return:
    """

    ip = devices_map[id]["ip"]

    request_url = "{ip}:{port}/{what}/{id}".format(ip=ip,port=port,what=what,id=id)

    if type is not None:
        request_url = request_url + "/" + type

    req = urllib2.Request(url=request_url, data = data, headers={'Content-Type': 'application/json'})

    try:
        f = urllib2.urlopen(req,timeout=timeout)
        message = f.read()

        if message:
            data = json.loads(message)

            if not id in devices_map:
                logging.warning("Device %s is not in device map. Rescanning subnet..." % id)
                devices_map = generate_new_device_map(result_main_dir=result_main_dir)
            try:
                if data is None:
                    raise Exception("No data in JSON")
                devices_map[id].update(data)
                return data

            except KeyError:
                logging.error("Device %s is not detected" % id)
                raise KeyError("Device %s is not detected" % id)
    except urllib2.URLError as e:
        raise ScanException(str(e))

    except Exception as e:
        logging.error("Unexpected error whilst scanning url: %s" % request_url)
        raise Exception(str(e))


def make_backup_path(device, result_main_dir, timeout=30):

    try:
        com = "SELECT value from METADATA WHERE field = 'date_time'"
        raw_ip = os.path.basename(device["ip"]) #without http://
        mysql_db = MySQLdb.connect( host=raw_ip,
                                    #fixme import this info as a global var
                                    user="ethoscope",
                                    passwd="ethoscope",
                                    db="ethoscope_db",
                                    connect_timeout=timeout)

        cur = mysql_db.cursor()
        cur.execute(com)
        query = [c for c in cur]
        timestamp = float(query[0][0])
        mysql_db.close()

        date_time = datetime.datetime.fromtimestamp(timestamp)

        formated_time = date_time.strftime('%Y-%m-%d_%H-%M-%S')
        device_id = device["id"]
        device_name = device["name"]
        file_name = "%s_%s.db" % (formated_time, device_id)

        output_db_file = os.path.join(result_main_dir,
                                            device_id,
                                            device_name,
                                            formated_time,
                                            file_name
                                            )

    except Exception as e:
        logging.error("Could not generate backup path for device. Probably a MySQL issue")
        logging.error(traceback.format_exc(e))
        return None
    return output_db_file

def generate_new_device_map(local_ip, ip_range=(2,64), result_main_dir="/ethoscope_results"):
        devices_map = {}
        subnet_ip = local_ip.split(".")[0:3]
        subnet_ip = ".".join(subnet_ip)

        t0 = time.time()

        logging.info("Scanning attached devices")

        scanned = [ "%s.%i" % (subnet_ip, i) for i in range(*ip_range) ]
        urls= ["http://%s" % str(s) for s in scanned]


        # We can use a with statement to ensure threads are cleaned up promptly
        with futures.ThreadPoolExecutor(max_workers=64) as executor:
            # Start the load operations and mark each future with its URL

            fs = [executor.submit(scan_one_device, url) for url in urls]
            for f in concurrent.futures.as_completed(fs):

                try:
                    id, ip = f.result()
                    devices_map[id] = {"ip":ip, "id":id}

                except ScanException as e:
                    pass
                except Exception as e:
                    logging.error("Error whilst pinging url")
                    logging.error(traceback.format_exc(e))

        if len(devices_map) < 1:
            logging.warning("No device detected")
            return  devices_map

        all_devices = sorted(devices_map.keys())
        logging.info("DEVICE ID -> Detected %i devices in %i seconds:\n%s" % (len(devices_map),time.time() - t0, str(all_devices)))
        # We can use a with statement to ensure threads are cleaned up promptly

        with futures.ThreadPoolExecutor(max_workers=5) as executor:
            # Start the load operations and mark each future with its URL
            fs = {}
            for id in devices_map.keys():
                fs[executor.submit(update_dev_map_wrapped,devices_map, id)] = id

            for f in concurrent.futures.as_completed(fs):
                try:
                    id = fs[f]
                    data = f.result()
                    devices_map[id].update(data)

                except Exception as e:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc(e))
                    del devices_map[id]
        all_devices = sorted(devices_map.keys())
        logging.info("DEVICE INFO -> Detected %i devices in %i seconds:\n%s" % (len(devices_map),time.time() - t0, str(all_devices)))


 # We can use a with statement to ensure threads are cleaned up promptly
        with futures.ThreadPoolExecutor(max_workers=64) as executor:
            # Start the load operations and mark each future with its URL
            fs = {}
            for id in devices_map.keys():
                device = devices_map[id]
                fs[executor.submit(make_backup_path, device,result_main_dir)] = id

            for f in concurrent.futures.as_completed(fs):
                try:
                    id = fs[f]
                    path = f.result()
                    if path:
                        devices_map[id]["backup_path"] = path

                except Exception as e:
                    logging.error("Error whilst getting backup path for device")
                    logging.error(traceback.format_exc(e))


        for d in devices_map.values():
            d["time_since_backup"] = get_last_backup_time(d)


        all_devices = sorted(devices_map.keys())
        logging.info("BACKUP_PATH -> Detected %i devices in %i seconds:\n%s" % (len(devices_map),time.time() - t0, str(all_devices)))

        return devices_map

def get_last_backup_time(device):
    try:
        backup_path = device["backup_path"]
        time_since_last_backup = time.time() - os.path.getmtime(backup_path)
        return time_since_last_backup
    except Exception:
        return "No backup"





def get_local_ip(local_router_ip = "192.169.123.254", node_subnet_address="1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((local_router_ip ,80))
    except socket.gaierror:
        raise Exception("Cannot find local ip, check your connection")


    ip = s.getsockname()[0]
    s.close()

    router_ip = local_router_ip.split(".")
    ip_list = ip.split(".")
    if router_ip[0:3] != ip_list[0:3]:
        raise Exception("The local ip address does not match the expected router subnet: %s != %s" % (str(router_ip[0:3]), str(ip_list[0:3])))
    if  ip_list[3] != node_subnet_address:
        raise Exception("The ip of the node in the intranet should finish by %s. current ip = %s" % (node_subnet_address, ip))
    return ip


def get_internet_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        s.connect(("google.com", 80))
    except socket.gaierror:
        raise Exception("Cannot find internet (www) connection")

    ip = s.getsockname()[0]
    s.close()
    return ip
