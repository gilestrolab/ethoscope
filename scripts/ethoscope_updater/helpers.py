__author__ = 'quentin'


import os
import logging
import datetime
import urllib2
import json
import traceback
import random
import subprocess



try:
    from netifaces import ifaddresses, AF_INET, AF_LINK
except:
    logging.warning("Could not load netifaces. This is needed for node stuff")
try:
    import concurrent
    import concurrent.futures as futures
except:
    logging.warning("Could not load concurrent. This is needed for node stuff")

class UnexpectedAction(Exception):
    pass
class NotNode(Exception):
    pass
def get_commit_version(commit):
    return {"id":str(commit),
            "date":datetime.datetime.utcfromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                    }
def assert_node(is_node):
    if not is_node:
        raise NotNode("This device is not a node.")

def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)


def get_machine_info(path):
    """
    Reads the machine NAME file and returns the value.
    """
    try:
        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info
    except Exception as e:
        logging.warning(traceback.format_exc(e))
        return 'Debug-'+str(random.randint(1,100))




def scan_one_device(ip, timeout=2, port=8888, page="id"):
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


def update_dev_map_wrapped (devices_map,id, what="data",type=None, port=9000, data=None,result_main_dir="/ethoscope_results"):
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

    logging.info("requesting %s" % request_url)

    try:
        f = urllib2.urlopen(req)
        message = f.read()

        if message:
            data = json.loads(message)

            if not id in devices_map:
                logging.warning("Device %s is not in device map. Rescanning subnet..." % id)
                generate_new_device_map(result_main_dir=result_main_dir)
            try:
                devices_map[id].update(data)
                return data

            except KeyError:
                logging.error("Device %s is not detected" % id)
                raise KeyError("Device %s is not detected" % id)

    except urllib2.httplib.BadStatusLine as e:
        logging.error('BadlineSatus, most probably due to update device and auto-reset')
        raise e

    except urllib2.URLError as e:
        if hasattr(e, 'reason'):
            logging.error('We failed to reach a server.')
            logging.error('Reason: '+ str(e.reason))
            raise e
        elif hasattr(e, 'code'):
            logging.error('The server couldn\'t fulfill the request.')
            logging.error('Error code: '+ str(e.code))
            raise e

    return devices_map


def get_subnet_ip(device="wlan0"):
    try:
        ip = ifaddresses(device)[AF_INET][0]["addr"]
        return ".".join(ip.split(".")[0:3])
    except ValueError:
        raise ValueError("Device '%s' is not valid" % device)



def generate_new_device_map(ip_range=(2,253),device="wlan0"):
        devices_map = {}
        subnet_ip = get_subnet_ip(device)
        logging.info("Scanning attached devices")
        scanned = [ "%s.%i" % (subnet_ip, i) for i in range(*ip_range) ]
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
                    devices_map[id] = {"ip":ip, "status": "Software broken"}


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

        # Adds the active_branch to devices_,map
        with futures.ThreadPoolExecutor(max_workers=128) as executor:
            # Start the load operations and mark each future with its URL
            fs={}
            for id in devices_map.keys():
                fs[executor.submit(update_dev_map_wrapped,devices_map, id,what='device/active_branch',port='8888')] = id
            for f in concurrent.futures.as_completed(fs):
                id = fs[f]
                try:
                    data = f.result()
                    devices_map[id].update(data)
                except Exception as e:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc(e))

        # Adds the check_update to devices_,map
        with futures.ThreadPoolExecutor(max_workers=128) as executor:
            # Start the load operations and mark each future with its URL
            fs={}
            for id in devices_map.keys():
                fs[executor.submit(update_dev_map_wrapped,devices_map, id,what='device/check_update',port='8888')] = id
            for f in concurrent.futures.as_completed(fs):
                id = fs[f]
                try:
                    data = f.result()
                    devices_map[id].update(data)
                except Exception as e:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc(e))


        return devices_map

def updates_api_wrapper(ip,id, what="check_update",type=None, port=8888, data=None,):
    response = ''
    request_url = "{ip}:{port}/{what}/{id}".format(ip=ip,port=port,what=what,id=id)

    if type is not None:
        request_url = request_url + "/" + type

    req = urllib2.Request(url=request_url, data = data, headers={'Content-Type': 'application/json'})

    logging.info("requesting %s" %request_url)

    try:
        f = urllib2.urlopen(req)
        message = f.read()

        if message:
            response = json.loads(message)

    except urllib2.httplib.BadStatusLine as e:
        logging.error('BadlineSatus, most probably due to update device and auto-reset')
        raise e

    except urllib2.URLError as e:
        if hasattr(e, 'reason'):
            logging.error('We failed to reach a server.')
            logging.error('Reason: '+ str(e.reason))
            raise e
        elif hasattr(e, 'code'):
            logging.error('The server couldn\'t fulfill the request.')
            logging.error('Error code: '+ str(e.code))
            raise e

    return response



def _reload_daemon(name):
    subprocess.call(["systemctl","restart", name])

def reload_node_daemon():
    _reload_daemon("ethoscope_node")

def reload_device_daemon():
    _reload_daemon("ethoscope_device")
