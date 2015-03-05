from bottle import *

import urllib2
import subprocess
import socket
import json
import multiprocessing
import logging
import traceback
from psvnode.utils.acquisition import Acquisition
from psvnode.utils.helpers import get_version
from netifaces import ifaddresses, AF_INET
from os import walk
import optparse
import zipfile
import datetime

app = Bottle()
STATIC_DIR = "../../static"


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

def scan_one_device(url, timeout=1, port=9000):
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

        if not which("fping"):
            raise Exception("fping not available")
        ping = os.system(" fping %s -t 50  > /dev/null 2>&1 " % os.path.basename(url))
    except Exception as e:
        ping = 0
        logging.error("Could not ping. Assuming 'alive'")
        logging.error(traceback.format_exc(e))


    if ping != 0:
        logging.info("url: %s, not responding. Skipping" % url )
        return None, None

    try:
        req = urllib2.Request(url="%s:%i/id" % (url, port))
        f = urllib2.urlopen(req, timeout=timeout)
        message = f.read()
        if not message:
            logging.error("URL error whist scanning url: %s. No message back." % url )
            return
        resp = json.loads(message)
        return (resp['id'],url)

    except urllib2.URLError:
        logging.error("URL error whist scanning url: %s. Server down?" % url )
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

        if not id in devices_map:
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

@app.route('/download/<filepath:path>')
def server_download(filepath):
    return static_file(filepath, root="/", download=filepath)

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
                acquisition[id] = Acquisition(devices_map[id], result_main_dir=RESULTS_DIR)
                acquisition[id].start()
            else:
                raise Exception("Cannot start, device %s status is `%s`" %  (id, device_info['status']))

        elif type_of_req == 'stop':
            if device_info['status'] == 'running':
                update_device_map(id, "controls", type_of_req, data=post_data)
                acquisition[id].stop()
                logging.info("Joining process")
                acquisition[id].join()
                logging.info("Joined OK")
            else:
                raise Exception("Cannot stop, device %s status is `%s`" %  (id, device_info['status']))

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error':traceback.format_exc(e)}



#################################
# NODE Functions
#################################
@app.get('/node/status')
def node_status():
    return {'is_updated': is_updated}

#Browse, delete and download files from node
@app.get('/browse/<folder:path>')
def browse(folder):
    try:
        if folder == 'null':
            directory = RESULTS_DIR
        else:
            directory = '/'+folder
        files = []
        file_id=0
        for (dirpath, dirnames, filenames) in walk(directory):
            for name in dirnames:
                if dirpath==directory:
                    files.append({'name':os.path.join(dirpath, name), 'is_dir':True, 'id':file_id})
                    file_id += 1
            for name in filenames:
                if dirpath==directory:
                    files.append({'name':os.path.join(dirpath, name), 'is_dir':False, 'id':file_id})
                    file_id += 1

        return {'files': files}

    except Exception as e:
        return {'error': traceback.format_exc(e)}

@app.post('/update')
def update_systems():
    devices_to_update = request.json
    try:
        restart_node = False
        for key, d in devices_to_update.iteritems():
            if d['name'] == 'Node':
                #update node
                node_update = subprocess.Popen(['git','pull'],cwd=GIT_WORKING_DIR,
                                                  stdout=subprocess.PIPE,
                                                  stderr=subprocess.PIPE)
                response_from_fetch, error_from_fetch = node_update.communicate()
                if response_from_fetch != '':
                    logging.info(response_from_fetch)
                if error_from_fetch != '':
                    logging.error(error_from_fetch)
                restart_node = True

            else:
                update_device_map(d['id'], what="update", data='update')

    except Exception as e:
        return {'error':traceback.format_exc(e)}

    if restart_node is True:
        try:
            # stop acquisition thread
            close()
            # last but not least restart the node server:
            logging.info("Reset Node")
            pid=subprocess.Popen([RESTART_FILE, str(os.getpid())],
                                 close_fds=True,
                                 env=os.environ.copy())
        except Exception as e:
            return {'error':traceback.format_exc(e)}

@app.get('/update/check')
def check_update():
    global devices_map
    update = {}
    try:
        #check internet connection
        try:
            response=urllib2.urlopen('http://google.com', timeout=1)
        except urllib2.URLError, e:
            update['error'] = traceback.format_exc(e)
        #check if there is a new version on the repo
        bare_update= subprocess.Popen(['git', 'fetch', '-v', 'origin', BRANCH+':'+BRANCH],
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE,
                                      cwd=GIT_BARE_REPO_DIR,
                                    )
        response_from_fetch, error_from_fetch = bare_update.communicate()
        if response_from_fetch != '':
            logging.info(response_from_fetch)
        if error_from_fetch != '':
            logging.error(error_from_fetch)
        #check version
        origin_version = get_version(GIT_BARE_REPO_DIR, BRANCH)
        node_version = get_version(GIT_WORKING_DIR, BRANCH)

        if node_version != origin_version:
            update['node'] = {'version':node_version, 'name':'Node', 'id':'Node'}

        #check connected devices
        devices_map = scan_subnet()
        for key, d in devices_map.iteritems():
            if d['version'] != origin_version:
                update[d['id']] = d

        return update

    except Exception as e:
        return {'error':traceback.format_exc(e)}

@app.post('/request_download/<what>')
def download(what):
    print what
    if what == 'files':
        try:
            # zip the files and provide a link to download it
            req_files = request.json
            t = datetime.datetime.now()
            #FIXME change the route for this? and old zips need to be erased
            zip_file_name = RESULTS_DIR+'/results_'+t.strftime("%y%m%d_%H%M%S")+'.zip'
            zf = zipfile.ZipFile(zip_file_name, mode='a')

            for f in req_files['files']:
                print f
                zf.write(f['name'])
            zf.close()
        except Exception as e:
            print e
            logging.error(e)

        return {'url':zip_file_name}

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


def close():
    logging.info("Joining acquisition processes")
    for a in acquisition.values():
        a.stop()
        logging.info("Joining process")
        a.join()
        logging.info("Joined OK")

    logging.info("Closing server")

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

    RESULTS_DIR = "/psv_results/"
    GIT_BARE_REPO_DIR = "/var/pySolo-Video.git"
    GIT_WORKING_DIR = "/home/node/pySolo-Video"
    BRANCH = 'psv-package'

    if DEBUG:
        import getpass
        if getpass.getuser() == "quentin":
            SUBNET_DEVICE = b'enp3s0'
            # SUBNET_DEVICE = b'eno1'
            GIT_BARE_REPO_DIR = GIT_WORKING_DIR  = "./"

        if getpass.getuser() == "asterix":
            SUBNET_DEVICE = b'lo'
            RESULTS_DIR = "/tmp/"
            GIT_BARE_REPO_DIR = "/data1/todel/pySolo-Video.git"
            GIT_WORKING_DIR = "/data1/todel/pySolo-video-node"
            BRANCH = 'psv-dev'

        RESTART_FILE = "./restart.sh"
    else:
        SUBNET_DEVICE = b'wlan0'
        RESTART_FILE = "./restart_production.sh"




    global devices_map
    devices_map = {}
    scan_subnet()

    acquisition = {}

    origin_version = get_version(GIT_BARE_REPO_DIR, BRANCH)
    node_version = get_version(GIT_WORKING_DIR, BRANCH)
    if origin_version != node_version:
        is_updated = False
    else:
        is_updated = True


    for k, device in devices_map.iteritems():
        if device['status'] == 'running':
            acquisition[k]= Acquisition(device, result_main_dir=RESULTS_DIR)
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
        close()
