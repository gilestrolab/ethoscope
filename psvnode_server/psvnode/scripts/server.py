from bottle import *
import shlex
import urllib2
import subprocess
import socket
import json
import multiprocessing
import logging
import traceback
from pexpect.screen import screen
from psvnode.utils.acquisition import Acquisition
from netifaces import interfaces, ifaddresses, AF_INET
from os import walk
import optparse

app = Bottle()
STATIC_DIR = "../../static"


def scan_one_device(url, timeout=.5, port=9000):
    """
    Pings an url and try parsing its message as JSON data. This is typically used within a multithreading.Pool.map in
    order to request multiple arbitrary urls.

    :param url: the url to parse
    :param timeout: the timeout of the url request
    :param port: the port to request
    :return: The message, parsed as dictionary. the "ip" (==url) field is also added to the result.
    If the url could not be reached, None is returned
    """
    try:
        req = urllib2.Request(url="%s:%i/id" % (url, port))
        f = urllib2.urlopen(req, timeout=timeout)
        message = f.read()
        if not message:
            return
        resp = json.loads(message)
        return (resp['id'],url)

    except urllib2.URLError:
        logging.warning("URL error whist scanning url: %s" % url )
        return None, None
    except Exception as e:
        logging.error("Unexpected error whilst scanning url: %s" % url )
        raise e



def update_device_map(id, what="data",type=None, port=9000, data=None):
    """
    Just a routine to format our GET urls. This improves readability whilst allowing us to change convention (e.g. port) without rewriting everything.

    :param id: machine unique identifier
    :param what: e.g. /data, /control
    :param type: the type of request for POST
    :param port:
    :return:
    """
    global devices_map

    ip = devices_map[id]["ip"]

    request_url = "{ip}:{port}/{what}/{id}".format(ip=ip,port=port,what=what,id=id)

    if type is not None:
        request_url = request_url + "/" + type

    req = urllib2.Request(url=request_url, data = data, headers={'Content-Type': 'application/json'})

    f = urllib2.urlopen(req)
    message = f.read()
    if message:
        data = json.loads(message)

        if not id in  devices_map:
            logging.warning("Device %s is not in device map. Rescanning subnet..." % id)
            scan_subnet()
        try:
            devices_map[id].update(data)

        except KeyError:
            logging.error("Device %s is not detected" % id)
            raise KeyError("Device %s is not detected" % id)


def get_subnet_ip(device="wlan0"):
    try:
        ip = ifaddresses(device)[AF_INET][0]["addr"]
        return ".".join(ip.split(".")[0:3])
    except ValueError:
        raise ValueError("Device '%s' is not valid" % device)

@app.get('/favicon.ico')
def get_favicon():
    return server_static(STATIC_DIR+'/img/favicon.ico')

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root=STATIC_DIR)


@app.route('/')
def index():
    return static_file('index.html', root=STATIC_DIR)


#################################
# API to connect with SM/SD
#################################

@app.get('/devices')
def scan_subnet():
    subnet_ip = get_subnet_ip(SUBNET_DEVICE)
    logging.info("Scanning attached devices")
    urls_to_scan = ["http://%s.%i" % (subnet_ip,i)  for i in range(2,254)]
    pool = multiprocessing.Pool(len(urls_to_scan))
    devices_id_url_list = pool.map(scan_one_device, urls_to_scan)



    global devices_map
    devices_map = {}
    for id, ip in devices_id_url_list :
        if id is None:
            continue
        devices_map[id] = {"ip":ip}

    map(update_device_map, devices_map.keys())

    pool.terminate()
    logging.info("%i devices found:" % len(devices_map))

    for k,v in devices_map.items():
        logging.info("%s\t@\t%s" % (k,v["ip"]))
    return devices_map

@app.get('/devices_list')
def get_devices_list():
    global devices_map
    return devices_map


#Get the information of one Sleep Monitor
@app.get('/device/<id>/data')
def device(id):
    try:
        update_device_map(id,what="data")
        return devices_map[id]
    except Exception as e:
        return {'error':traceback.format_exc(e)}


@app.post('/device/<id>/controls/<type_of_req>')
def device(id, type_of_req):
    global acquisition
    try:
        post_data = request.body.read()
        update_device_map(id, "data")
        device_info = devices_map[id]

        if type_of_req == 'start':
            if device_info['status'] == 'stopped':
                update_device_map(id, "controls", type_of_req, data=post_data)
                acquisition[id] = Acquisition(devices_map[id])
                acquisition[id].start()
            else:
                raise Exception("Cannot start, device %s status is `%s`" %  (id, device_info['status']))

        elif type_of_req == 'stop':
            if device_info['status'] == 'running':
                update_device_map(id, "controls", type_of_req, data=post_data)
                acquisition[id].stop()
                acquisition[id].join()
            else:
                raise Exception("Cannot stop, device %s status is `%s`" %  (id, device_info['status']))

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error':traceback.format_exc(e)}

#Browse, delete and download files from node
@app.get('/browse/<folder:path>')
def browse(folder):
    try:
        if folder == 'null':
            directory = RESULTS_DIR
        else:
            directory = '/'+folder
        files = []
        dir =[]
        for (dirpath, dirnames, filenames) in walk(directory):
            for name in filenames:
                if dirpath==directory:
                    files.append(os.path.join(dirpath, name))
            for name in dirnames:
                if dirpath==directory:
                    dir.append(os.path.join(dirpath, name))

        return{'files': files, 'dir':dir}
    except Exception as e:
        return {'error': traceback.format_exc(e)}

def file_process(arg,dir,files):
    return files


@app.get('/list/<type>')
def redirection_to_home(type):
    return redirect('/#/list/'+type)
@app.get('/more')
def redirection_to_home():
    return redirect('/#/more/')
@app.get('/sm/<id>')
def redirection_to_home(id):
    return redirect('/#/sm/'+id)
@app.get('/device/<id>/ip')
def redirection_to_home(id):
    if len(devices_map) > 0:
        return devices_map[id]['ip']
    else:
        return "no devices"

@app.post('/device/<id>/log')
def get_log(id):
    try:

        data = request.body.read()
        data = json.loads(data)

        # url  = format_post_get_url(id,"static",type=data["file_path"])
        # req = urllib2.Request(url)
        #TO DISCUSS @luis static files url not understood
        req = urllib2.Request(url=devices_map[id]['ip']+':9000/static'+data["file_path"])

        f = urllib2.urlopen(req)
        result = {}
        for i, line in enumerate(f):
            result[i]=line

        return result

    except Exception as e:
        return {'error':traceback.format_exc(e)}


if __name__ == '__main__':
    # TODO where to save the files and the logs

    logging.getLogger().setLevel(logging.INFO)

    parser = optparse.OptionParser()
    parser.add_option("-d", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-p", "--port", dest="port", default=80,help="port")
    (options, args) = parser.parse_args()

    option_dict = vars(options)
    DEBUG = option_dict["debug"]
    PORT = option_dict["port"]

    if DEBUG:
        import getpass
        if getpass.getuser() == "quentin":
            SUBNET_DEVICE = b'enp3s0'
        if getpass.getuser() == "asterix":
            SUBNET_DEVICE = b'lo'
            RESULTS_DIR = "/tmp/"
    else:
        SUBNET_DEVICE = b'wlan0'
        RESULTS_DIR = "/results/"


    global devices_map
    devices_map = {}
    scan_subnet()

    acquisition = {}

    for k, device in devices_map.iteritems():
        if device['status'] == 'running':
            acquisition[k]= Acquisition(device)
            acquisition[k].start()
    try:

        run(app, host='0.0.0.0', port=PORT, debug=DEBUG)

    except KeyboardInterrupt:
        logging.info("Stopping server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc(e))
        logging.error("Port %i is probably not accessible for you. Maybe use another one e.g.`-p 8000`" % PORT)

    except Exception as e:
        logging.error(traceback.format_exc(e))

    finally:
        for a in acquisition.values():
            a.stop()
            a.join()
