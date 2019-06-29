import bottle
import subprocess
import socket
import logging
import traceback
from ethoscope_node.utils.device_scanner import DeviceScanner
import os
import optparse
import zipfile
import datetime
import fnmatch
import tempfile
import shutil
import netifaces
import json

app = bottle.Bottle()
STATIC_DIR = "../static"

#names of the backup services
BACKUP_DAEMONS = {"ethoscope_node": {'description' : 'The main Ethoscope node server interface. It is used to control the ethoscopes.'}, 
                  "ethoscope_backup" : {'description' : 'The service that collects data from the ethoscopes and syncs them with the node.'}, 
                  "ethoscope_video_backup" : {'description' : 'The service that collects VIDEOs from the ethoscopes and syncs them with the node'}, 
                  "ethoscope_update_node" : {'description' : 'The service used to update the nodes and the ethoscopes.'}
                  }


def error_decorator(func):
    """
    A simple decorator to return an error dict so we can display it in the webUI
    """
    def func_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {'error': traceback.format_exc()}
    return func_wrapper

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return bottle.static_file(filepath, root=STATIC_DIR)

@app.route('/tmp_static/<filepath:path>')
def server_tmp_static(filepath):
    return bottle.bottle.static_file(filepath, root=tmp_imgs_dir)

@app.route('/download/<filepath:path>')
def server_download(filepath):
    return bottle.static_file(filepath, root="/", download=filepath)

@app.route('/')
def index():
    return bottle.static_file('index.html', root=STATIC_DIR)


@app.hook('after_request')
def enable_cors():
    """
    You need to add some headers to each request.
    Don't use the wildcard '*' for Access-Control-Allow-Origin in production.
    """
    bottle.response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8888'
    bottle.response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    bottle.response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'


#################################
# API to connect with ethoscopes
#################################

"""
/devices                                GET     returns info about devices
/device/<id>/data                       GET
/device/<id>/machineinfo                GET, POST
/device/<id>/user_options               GET
/device/<id>/videofiles                 GET
/device/<id>/last_img                   GET
/device/<id>/dbg_img                    GET
/device/<id>/stream                     GET
/device/<id>/controls/<instruction>     POST
/device/<id>/log                        GET


/results_file
/browse/<folder:path>
/request-download
/node/<req>
/node-actions
/remove_files
/list/<type>
/more
/ethoscope/<id>
/device/<id>/ip
/more/<action>
"""

@app.get('/favicon.ico')
def get_favicon():
    return server_static(STATIC_DIR+'/img/favicon.ico')


@app.get('/devices')
@error_decorator
def devices():
    return device_scanner.get_all_devices_info()


@app.get('/devices_list')
def get_devices_list():
    devices()

#Get the information of one device
@app.get('/device/<id>/data')
@error_decorator
def get_device_info(id):
    device = device_scanner.get_device(id)
    # if we fail to access directly the device, we have the old info map
    if not device:
        return device_scanner.get_all_devices_info()[id]

    return device.info()

#Get the private machine information of one device
@app.get('/device/<id>/machineinfo')
@error_decorator
def get_device_machine_info(id):
    device = device_scanner.get_device(id)
    # if we fail to access directly the device, we have the old info map
    if not device:
        return device_scanner.get_all_devices_info()[id]

    return device.machine_info()

@app.post('/device/<id>/machineinfo')
@error_decorator
def set_device_machine_info(id):

    post_data = bottle.request.body.read()
    device = device_scanner.get_device(id)
    device.send_settings(post_data)

    return device.machine_info()

@app.get('/device/<id>/user_options')
@error_decorator
def get_device_options(id):
    device = device_scanner.get_device(id)
    return device.user_options()

@app.get('/device/<id>/videofiles')
@error_decorator
def get_device_videofiles(id):
    device = device_scanner.get_device(id)
    return device.videofiles()


#Get the information of one Sleep Monitor
@app.get('/device/<id>/last_img')
@error_decorator
def get_device_last_img(id):
    device = device_scanner.get_device(id)
    if "status" not in list(device.info().keys()) or device.info()["status"] == "not_in use":
        raise Exception("Device %s is not in use, no image" % id )
    file_like = device.last_image()
    if not file_like:
        raise Exception("No image for %s" % id)
    basename = os.path.join(tmp_imgs_dir, id + "_last_img.jpg")
    return cache_img(file_like, basename)

@app.get('/device/<id>/dbg_img')
@error_decorator
def get_device_dbg_img(id):

    device = device_scanner.get_device(id)
    file_like = device.dbg_img()
    basename = os.path.join(tmp_imgs_dir, id + "_debug.png")
    return cache_img(file_like, basename)


@app.get('/device/<id>/stream')
@error_decorator
def get_device_stream(id):
  
    device = device_scanner.get_device(id)
    bottle.response.set_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
    return device.relay_stream()


def cache_img(file_like, basename):
    if not file_like:
        #todo return link to "broken img"
        return ""
    local_file = os.path.join(tmp_imgs_dir, basename)
    tmp_file = tempfile.mktemp(prefix="ethoscope_", suffix=".jpg")
    with open(tmp_file , "wb") as lf:
        lf.write(file_like.read())
    shutil.move(tmp_file, local_file)
    return server_tmp_static(os.path.basename(local_file))


@app.post('/device/<id>/controls/<instruction>')
@error_decorator
def post_device_instructions(id, instruction):
    post_data = bottle.request.body.read()
    device = device_scanner.get_device(id)
    device.send_instruction(instruction, post_data)
    return get_device_info(id)

@app.post('/device/<id>/log')
@error_decorator
def get_log(id):
    device = device_scanner.get_device(id)
    return device.get_log()


#################################
# NODE Functions
#################################


#Browse, delete and download files from node

@app.get('/result_files/<type>')
@error_decorator
def result_file(type):
    """
    :param type:'all', 'db' or 'txt'
    :return: a dict with a single key: "files" which maps a list of matching result files (absolute path)
    """
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


@app.get('/browse/<folder:path>')
@error_decorator
def browse(folder):
    if folder == 'null':
        directory = RESULTS_DIR
    else:
        directory = '/'+folder
    files = []
    for (dirpath, dirnames, filenames) in os.walk(directory):
        for name in filenames:
            abs_path = os.path.join(dirpath,name)
            size = os.path.getsize(abs_path)
            #rel_path = os.path.relpath(abs_path,directory)
            files.append({'abs_path':abs_path, 'size':size})
    return {'files': files}


@app.post('/request_download/<what>')
@error_decorator
def download(what):
    # zip the files and provide a link to download it
    if what == 'files':
        req_files = bottle.request.json
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

@app.get('/node/<req>')
@error_decorator
def node_info(req):#, device):
    if req == 'info':
       
        with os.popen('df %s -h' % RESULTS_DIR) as df:
            disk_free = df.read()
        
        disk_usage = RESULTS_DIR+" Not Found on disk"

        CARDS = {}
        GIT_BRANCH = "Not detected"
        NEEDS_UPDATE = False

        try:
            disk_usage = disk_free.split("\n")[1].split()

            #the following returns something like this: [['eno1', 'ec:b1:d7:66:2e:3a', '192.168.1.1'], ['enp0s20u12', '74:da:38:49:f8:2a', '155.198.232.206']]
            adapters_list = [ [i, netifaces.ifaddresses(i)[17][0]['addr'], netifaces.ifaddresses(i)[2][0]['addr']] for i in netifaces.interfaces() if 17 in netifaces.ifaddresses(i) and 2 in netifaces.ifaddresses(i) and netifaces.ifaddresses(i)[17][0]['addr'] != '00:00:00:00:00:00' ]
            for ad in adapters_list:
                CARDS [ ad[0] ] = {'MAC' : ad[1], 'IP' : ad[2]}
            
           
            with os.popen('git rev-parse --abbrev-ref HEAD') as df:
                GIT_BRANCH = df.read()
            #df = subprocess.Popen(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], stdout=subprocess.PIPE)
            #GIT_BRANCH = df.communicate()[0].decode('utf-8')
            
            with os.popen('git status -s -uno') as df:
                NEEDS_UPDATE = df.read() != ""

            #df = subprocess.Popen(['git', 'status', '-s', '-uno'], stdout=subprocess.PIPE)
            #NEEDS_UPDATE = df.communicate()[0].decode('utf-8') != ""

        except Exception as e:
            logging.error(e)

        return {'disk_usage': disk_usage, 'CARDS': CARDS, 'GIT_BRANCH': GIT_BRANCH, 'NEEDS_UPDATE': NEEDS_UPDATE}
                
    elif req == 'time':
        return {'time':datetime.datetime.now().isoformat()}
        
    elif req == 'timestamp':
        return {'timestamp': time.time()}
    
    elif req == 'log':
        with os.popen("journalctl -u ethoscope_node -rb") as log:
            l = log.read()
        return {'log': l}
    
    elif req == 'daemons':
        #returns active or inactive
        for daemon_name in BACKUP_DAEMONS.keys():
        
            with os.popen("systemctl is-active %s" % daemon_name) as df:
                BACKUP_DAEMONS[daemon_name]['active'] = df.read().strip()
            
            #cmdline = "systemctl show --no-page %s | jq --slurp --raw-input 'split(\"\n\") | map(select(. != \"\") | split(\"=\") | {\"key\": .[0], \"value\": (.[1:] | join(\"=\"))}) | from_entries'"
            cmdline = "systemctl status %s --output=json --plain"
            
            with os.popen(cmdline % daemon_name) as df:
                a = df.read()

            json_component = a[a.find("{"):]
            BACKUP_DAEMONS[daemon_name]['exec'] = json.loads(json_component.split("\n")[0])['_CMDLINE']
            
        
        return BACKUP_DAEMONS
        
    else:
        raise NotImplementedError()

@app.post('/node-actions')
@error_decorator
def node_actions():
    action = bottle.request.json
    
    if action['action'] == 'poweroff':
        logging.info('User request a poweroff, shutting down system. Bye bye.')
        close()
        #poweroff = subprocess.Popen(['poweroff'], stdout=subprocess.PIPE)
    
    elif action['action'] == 'close':
        close()
    
    elif action['action'] == 'toggledaemon':

        if action['status'] == True:
            cmd = "systemctl start %s" % action['daemon_name']
            logging.info ("Starting daemon %s" % action['daemon_name'])
            
        elif  action['status'] == False:
            cmd = "systemctl stop %s" % action['daemon_name']
            logging.info ("Stopping daemon %s" % action['daemon_name'])
            
        with os.popen(cmd) as po:
            r = po.read()
           
        return r
    
    else:
        raise NotImplementedError()

@app.post('/remove_files')
@error_decorator
def remove_files():
    req = bottle.request.json
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

@app.get('/list/<type>')
def redirection_to_home(type):
    return bottle.redirect('/#/list/'+type)

@app.get('/more')
def redirection_to_home():
    return bottle.redirect('/#/more/')
    
@app.get('/ethoscope/<id>')
def redirection_to_home(id):
    return bottle.redirect('/#/ethoscope/'+id)

@app.get('/more/<action>')
def redirection_to_more(action):
    return bottle.redirect('/#/more/'+action)

def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)


#======================================================================================================================#
#############
### CLASSS TO BE REMOVED IF BOTTLE CHANGES TO 0.13
############
class CherootServer(bottle.ServerAdapter):
    def run(self, handler): # pragma: no cover
        from cheroot import wsgi
        from cheroot.ssl import builtin
        self.options['bind_addr'] = (self.host, self.port)
        self.options['wsgi_app'] = handler
        certfile = self.options.pop('certfile', None)
        keyfile = self.options.pop('keyfile', None)
        chainfile = self.options.pop('chainfile', None)
        server = wsgi.Server(**self.options)
        if certfile and keyfile:
            server.ssl_adapter = builtin.BuiltinSSLAdapter(
                    certfile, keyfile, chainfile)
        try:
            server.start()
        finally:
            server.stop()
#############

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    parser = optparse.OptionParser()
    parser.add_option("-D", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-p", "--port", dest="port", default=80,help="port")
    parser.add_option("-l", "--local", dest="local", default=False, help="Run on localhost (run a node and device on the same machine, for development)", action="store_true")
    parser.add_option("-e", "--results-dir", dest="results_dir", default="/ethoscope_results",help="Where temporary result files are stored")

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]
    RESULTS_DIR = option_dict["results_dir"]

    tmp_imgs_dir = tempfile.mkdtemp(prefix="ethoscope_node_imgs")
    device_scanner = None
    try:
        device_scanner = DeviceScanner(results_dir=RESULTS_DIR)
        device_scanner.start()
        #######TO be remove when bottle changes to version 0.13
        server = "cherrypy"
        try:
            from bottle.cherrypy import wsgiserver
        except:
            #Trick bottle to think that cheroot is actulay cherrypy server adds the pacth to BOTTLE
            bottle.server_names["cherrypy"]=CherootServer(host='0.0.0.0', port=PORT)
            logging.warning("Cherrypy version is bigger than 9, we have to change to cheroot server")
            pass
        #########
        bottle.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, server='cherrypy')

    except KeyboardInterrupt:
        logging.info("Stopping server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc())
        logging.error("Port %i is probably not accessible for you. Maybe use another one e.g.`-p 8000`" % PORT)

    except Exception as e:
        logging.error(traceback.format_exc())
        close(1)
    finally:
        device_scanner.stop()
        shutil.rmtree(tmp_imgs_dir)
        close()
