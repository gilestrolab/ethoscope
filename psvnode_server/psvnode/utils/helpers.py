
import logging
import json
import  urllib2 as urllib2
import subprocess
import os
import traceback
import concurrent
import concurrent.futures as futures
from netifaces import ifaddresses, AF_INET
import datetime
import MySQLdb

def get_version(dir, branch):
    version = subprocess.Popen(['git', 'rev-parse', branch],
                                   cwd=dir,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    stdout, stderr = version.communicate()
    return stdout.strip('\n')

def which(program):
    # verbatim from
    # http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None



def scan_one_device(ip, timeout=1, port=9000, page="id"):
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
            raise urllib2.URLError("No message back")
        try:
            resp = json.loads(message)
            return (resp['id'],ip)
        except ValueError:
            logging.error("Could not parse response from %s as JSON object" % url )

    except urllib2.URLError:
        pass
        # logging.error("URL error whist scanning url: %s. Server down?" % url )

    except Exception as e:
        logging.error("Unexpected error whilst scanning url: %s" % url )
        raise e

    return None, ip


def update_dev_map_wrapped (devices_map,id, what="data",type=None, port=9000, data=None):
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
        f = urllib2.urlopen(req)
        message = f.read()

        if message:
            data = json.loads(message)

            if not id in devices_map:
                logging.warning("Device %s is not in device map. Rescanning subnet..." % id)
                generate_new_device_map()
            try:
                devices_map[id].update(data)
                return data

            except KeyError:
                logging.error("Device %s is not detected" % id)
                raise KeyError("Device %s is not detected" % id)

    except urllib2.httplib.BadStatusLine:
        logging.error('BadlineSatus, most probably due to update device and auto-reset')

    except urllib2.URLError as e:
        if hasattr(e, 'reason'):
            logging.error('We failed to reach a server.')
            logging.error('Reason: ', e.reason)
        elif hasattr(e, 'code'):
            logging.error('The server couldn\'t fulfill the request.')
            logging.error('Error code: ', e.code)
    return devices_map


def get_subnet_ip(device="wlan0"):
    try:
        ip = ifaddresses(device)[AF_INET][0]["addr"]
        return ".".join(ip.split(".")[0:3])
    except ValueError:
        raise ValueError("Device '%s' is not valid" % device)



def make_backup_path(device, result_main_dir="/psv_results"):

    try:
        com = "SELECT value from METADATA WHERE field = 'date_time'"
        raw_ip = os.path.basename(device["ip"]) #without http://
        mysql_db = MySQLdb.connect( host=raw_ip,
                                    #fixme import this info as a global var
                                    user="psv",
                                    passwd="psv",
                                    db="psv_db")

        cur = mysql_db.cursor()
        cur.execute(com)
        query = [c for c in cur]
        timestamp = float(query[0][0])
        mysql_db.close()



    except Exception as e:
        logging.error("Could not generate backup path for device. Probably a MySQL issue")
        logging.error(traceback.format_exc(e))
        return None

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
    return output_db_file

def generate_new_device_map(ip_range=(2,253),device="wlan0"):
        devices_map = {}
        subnet_ip = get_subnet_ip(device)
        logging.info("Scanning attached devices")
        scanned = [ "%s.%i" % (subnet_ip, i) for i in range(2,253) ]
        urls= ["http://%s" % str(s) for s in scanned]

        # We can use a with statement to ensure threads are cleaned up promptly
        with futures.ThreadPoolExecutor(max_workers=128) as executor:
            # Start the load operations and mark each future with its URL

            fs = [executor.submit(scan_one_device, url) for url in urls]
            for f in concurrent.futures.as_completed(fs):

                try:
                    id, ip = f.result()
                    if id is None:
                        continue
                    devices_map[id] = {"ip":ip}

                except Exception as e:
                    logging.error("Error whilst pinging url")
                    logging.error(traceback.format_exc(e))
        if len(devices_map) < 1:
            logging.warning("No device detected")
            return  devices_map

        logging.info("Detected %i devices:\n%s" % (len(devices_map), str(devices_map.keys())))
        # We can use a with statement to ensure threads are cleaned up promptly
        with futures.ThreadPoolExecutor(max_workers=128) as executor:
            # Start the load operations and mark each future with its URL
            fs = {}
            for id in devices_map.keys():
                fs[executor.submit(update_dev_map_wrapped,devices_map, id)] = id

            for f in concurrent.futures.as_completed(fs):
                id = fs[f]
                try:
                    data = f.result()
                    devices_map[id].update(data)
                except Exception as e:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc(e))

        for d in devices_map.values():
            d["backup_path"] = make_backup_path(d)

        return devices_map

