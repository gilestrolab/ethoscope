from bottle import *

import urllib2
import subprocess
import socket
import json

import logging
import traceback
from psvnode.utils.acquisition import Acquisition
from psvnode.utils.helpers import get_version
from psvnode.utils.helpers import which

from netifaces import ifaddresses, AF_INET
from os import walk
import optparse
import zipfile
import datetime
import fnmatch


import concurrent.futures as futures
import concurrent

from psvnode.utils.helpers import scan_one_device



app = Bottle()
STATIC_DIR = "../../static"




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

    try:
        f = urllib2.urlopen(req)
        message = f.read()

        if message:
            data = json.loads(message)

            if not id in devices_map:
                logging.warning("Device %s is not in device map. Rescanning subnet..." % id)
                scan_subnet()
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
def scan_subnet(ip_range=(2,253)):
    global devices_map
    try:

        devices_map = {}


        subnet_ip = get_subnet_ip(SUBNET_DEVICE)
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
                fs[executor.submit(update_device_map,id)] = id

            for f in concurrent.futures.as_completed(fs):
                id = fs[f]
                try:
                    data = f.result()
                    devices_map[id].update(data)
                except Exception as e:
                    logging.error("Could not get data from device %s :" % id)
                    logging.error(traceback.format_exc(e))



        for k, device in devices_map.iteritems():
            # if the device is running AND acquisition is not handled yet, we make a new process for it
            if device['status'] == 'running':
                if k not in acquisition.keys():
                    acquisition[k]= Acquisition(device, result_main_dir=RESULTS_DIR)
                    acquisition[k].start()

        return devices_map
    except Exception as e:
        logging.error("Unexpected exception when scanning for devices:")
        logging.error(traceback.format_exc(e))


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
                stop_device(id,post_data)
            else:
                raise Exception("Cannot stop, device %s status is `%s`" %  (id, device_info['status']))
        elif type_of_req == 'poweroff':
            if device_info['status'] == 'running':
                stop_device(id,post_data)
            update_device_map(id, "controls", type_of_req, data=post_data)

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error':traceback.format_exc(e)}

def stop_device(id, post_data):
    update_device_map(id, "controls", 'stop', data=post_data)
    acquisition[id].stop()
    logging.info("Joining process")
    acquisition[id].join()
    logging.info("Removing device %s from acquisition map" % id)
    del acquisition[id]



#################################
# NODE Functions
#################################
@app.get('/node/status')
def node_status():
    return {'is_updated': is_updated}

#Browse, delete and download files from node

@app.get('/result_files/<type>')
def result_file(type):
    """
    :param type:'all', 'db' or 'txt'
    :return: a dict with a single key: "files" which maps a list of matching result files (absolute path)
    """

    try:
        type="txt"
        if type == "all":
            pattern =  '*'
        else:
            pattern =  '*.'+type

        matches = []
        for root, dirnames, filenames in os.walk(RESULTS_DIR):
            for f in fnmatch.filter(filenames, pattern):
                matches.append(os.path.join(root, f))
            return {"files":matches}

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error':traceback.format_exc(e)}


@app.get('/browse/<folder:path>')
def browse(folder):
    try:
        if folder == 'null':
            directory = RESULTS_DIR
        else:
            directory = '/'+folder
        files = []
        for (dirpath, dirnames, filenames) in walk(directory):
            for name in filenames:
                abs_path = os.path.join(dirpath,name)
                #rel_path = os.path.relpath(abs_path,directory)
                files.append({'abs_path':abs_path})

        return {'files': files}

    except Exception as e:
        return {'error': traceback.format_exc(e)}

@app.post('/update')
def update_systems():
    devices_to_update = request.json
    try:
        restart_node = False
        for d in devices_to_update:
            if d['name'] == 'Node':
                #update node
                node_update = subprocess.Popen(['git', 'pull'],
                                                cwd=GIT_WORKING_DIR,
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
            logging.info("Stopping server. Should be restarted automatically by systemd")
            close()
        except KeyboardInterrupt as k:
            raise k
        except Exception as e:
            return {'error':traceback.format_exc(e)}

@app.get('/update/check')
def check_update():
    global devices_map
    update = {}
    try:
        #check internet connection
        try:
            #fixme ping is simply not used here!
            if not which("fping"):
                raise Exception("fping not available")
            ping = os.system(" fping %s -t 50  > /dev/null 2>&1 " % '8.8.8.8')
        except Exception as e:
            ping = 0
            logging.error("Could not ping. Assuming 'alive'")
            logging.error(traceback.format_exc(e))
            update['error'] = 'No internet connection, check cable. Error: ', e

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
            update['error'] = error_from_fetch
        #check version
        origin_version = get_version(GIT_BARE_REPO_DIR, BRANCH)
        
        origin = {'version': origin_version, 'name': 'Origin'}
        devices_map = scan_subnet()
        update.update({'node': {'version': node_version, 'status': 'ON','name': 'Node', 'id':'Node'}})
        return {'update': update, 'attached_devices': devices_map, 'origin': origin}
    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'update':{'error':traceback.format_exc(e)}}



@app.post('/request_download/<what>')
def download(what):
    try:
        # zip the files and provide a link to download it
        if what == 'files':
            req_files = request.json
            t = datetime.datetime.now()
            #FIXME change the route for this? and old zips need to be erased
            zip_file_name = os.path.join(RESULTS_DIR,'results_'+t.strftime("%y%m%d_%H%M%S")+'.zip')
            zf = zipfile.ZipFile(zip_file_name, mode='a')
            logging.info("Saving files : %s in %s" % (str(req_files['files']), zip_file_name) )
            for f in req_files['files']:
                zf.write(f['url'])
            zf.close()

            return {'url':zip_file_name}

        else:
            raise NotImplementedError()

    except Exception as e:
        logging.error(e)
        return {'error':traceback.format_exc(e)}

@app.get('/node/<req>')
def node_actions(req):
    if req == 'info':
        df = subprocess.Popen(['df', RESULTS_DIR, '-h'], stdout = subprocess.PIPE)
        diskFree = df.communicate()[0]
        disk_usage =  diskFree.split("\n")[1].split()
        return {'disk_usage': disk_usage}
    else:
        raise NotImplementedError()
        return {'error':'Nothing here'}
@app.post('/node-actions')
def node_actions():
        action = request.json
        if action['action'] == 'poweroff':
            logging.info('User request a poweroff, shutting down system. Bye bye.')
            close()
        else:
            raise NotImplementedError()
@app.post('/remove_files')
def remove_files():
    try:
        req = request.json
        res = []
        for f in req['files']:
            rm = subprocess.Popen(['rm', f['url']],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
            out, err = rm.communicate()
            logging.info(out)
            logging.error(err)
            res.append(f['url'])
        return {'result': res}
    except Exception as e:
        logging.error(e)
        return {'error':e}


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


def close(exit_status=0):
    logging.info("Joining acquisition processes")
    for a in acquisition.values():
        a.stop()
        logging.info("Joining process")
        a.join()
        logging.info("Joined OK")

    logging.info("Closing server")
    os._exit(exit_status)
    

#======================================================================================================================#



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

    RESULTS_DIR = "/psv_results"
    GIT_BARE_REPO_DIR = "/var/pySolo-Video.git"
    GIT_WORKING_DIR = "/home/node/pySolo-Video"
    BRANCH = 'psv-package'
    SUBNET_DEVICE = b'wlan0'



    if DEBUG:
        import getpass
        if getpass.getuser() == "quentin":

            SUBNET_DEVICE = b'enp3s0'
            #SUBNET_DEVICE = b'eno1'
            GIT_BARE_REPO_DIR = GIT_WORKING_DIR = "./"

        if getpass.getuser() == "asterix":
            SUBNET_DEVICE = b'lo'
            RESULTS_DIR = "/data1/todel/psv_results"
            GIT_BARE_REPO_DIR = "/data1/todel/pySolo-Video.git"
            GIT_WORKING_DIR = "/data1/todel/pySolo-Node"
            BRANCH = 'psv-package'

    global devices_map
    global scanning_locked
    global acquisition


    scanning_locked = False
    devices_map = {}
    acquisition = {}


    scan_subnet()



    origin_version = get_version(GIT_BARE_REPO_DIR, BRANCH)
    node_version = get_version(GIT_WORKING_DIR, BRANCH)
    if origin_version != node_version:
        is_updated = False
    else:
        is_updated = True

    try:

        #run(app, host='0.0.0.0', port=PORT, debug=debug, server='cherrypy')
        run(app, host='0.0.0.0', port=PORT, debug=debug)


    except KeyboardInterrupt:
        logging.info("Stopping server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc(e))
        logging.error("Port %i is probably not accessible for you. Maybe use another one e.g.`-p 8000`" % PORT)

    except Exception as e:
        logging.error(traceback.format_exc(e))
        close(1)
    finally:
        close()
