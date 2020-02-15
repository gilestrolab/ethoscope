import bottle
import subprocess
import socket
import logging
import traceback
import os
import optparse
import zipfile
import datetime
import fnmatch
import tempfile
import shutil
import netifaces
import json

from ethoscope_node.utils.device_scanner import EthoscopeScanner, SensorScanner
from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper, BackupClass

from ethoscope_node.utils.etho_db import ExperimentalDB

app = bottle.Bottle()
STATIC_DIR = "../static"

#names of the backup services
SYSTEM_DAEMONS = {"ethoscope_node": {'description' : 'The main Ethoscope node server interface. It is used to control the ethoscopes.'}, 
                  "ethoscope_backup" : {'description' : 'The service that collects data from the ethoscopes and syncs them with the node.'}, 
                  "ethoscope_video_backup" : {'description' : 'The service that collects VIDEOs from the ethoscopes and syncs them with the node'}, 
                  "ethoscope_update_node" : {'description' : 'The service used to update the nodes and the ethoscopes.'},
                  "git-daemon.socket" : {'description' : 'The GIT server that handles git updates for the node and ethoscopes.'},
                  "ntpd" : {'description': 'The NTPd service is syncing time with the ethoscopes.'},
                  "sshd" : {'description': 'The SSH daemon allows power users to access the node terminal from remote.'}
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

def warning_decorator(func):
    """
    A simple decorator to return an error dict so we can display it in the webUI
    Less verbose than error
    """
    def func_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {'error': str(e)}
    return func_wrapper

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return bottle.static_file(filepath, root=STATIC_DIR)

@app.route('/tmp_static/<filepath:path>')
def server_tmp_static(filepath):
    return bottle.static_file(filepath, root=tmp_imgs_dir)

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
    #bottle.response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8888'
    bottle.response.headers['Access-Control-Allow-Origin'] = '*' # Allowing CORS in development
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


# RESOURCES ON NODE
/results_file
/browse/<folder:path>
/request-download
/node/<req>
/node-actions
/remove_files
/list/<type>
/more
/experiments
/ethoscope/<id>
/device/<id>/ip
/more/<action>
"""

@app.get('/favicon.ico')
def get_favicon():
    return server_static(STATIC_DIR+'/img/favicon.ico')


@app.get('/runs_list')
@error_decorator
def runs_list():
    #bottle.response.content_type = 'application/json'
    return json.dumps( edb.getRun('all', asdict=True) )

@app.get('/experiments_list')
@error_decorator
def experiments_list():
    #response.content_type = 'application/json'
    return json.dumps( edb.getExperiment('all', asdict=True) )

@app.get('/devices')
@error_decorator
def devices():
    return device_scanner.get_all_devices_info()

@app.get('/devices_list')
def get_devices_list():
    devices()

@app.get('/sensors')
@error_decorator
def sensors():
    return sensor_scanner.get_all_devices_info()


#Get the information of one device
@app.get('/device/<id>/data')
@warning_decorator
def get_device_info(id):
    device = device_scanner.get_device(id)
    
    # if we fail to access directly the device, we try the old info map
    if not device:
        try:
            return device_scanner.get_all_devices_info()[id]
        except:
            raise Exception("A device with ID %s is unknown to the system" % id)

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
    try:
        device = device_scanner.get_device(id)
        return device.user_options()
    except:
        return

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

@app.post('/device/<id>/backup')
@error_decorator
def force_device_backup(id):
    '''
    Forces backup on device with specified id
    '''
    results_dir = CFG.content['folders']['results']['path']
    device_info = get_device_info(id)
    
    try:
        logging.info("Initiating backup for device  %s" % device_info["id"])
        backup_job = BackupClass(device_info, results_dir=results_dir)
        logging.info("Running backup for device  %s" % device_info["id"])
        backup_job.run()
        logging.info("Backup done for for device  %s" % device_info["id"])
    except Exception as e:
        logging.error("Unexpected error in backup. args are: %s" % str(args))
        logging.error(traceback.format_exc())


@app.get('/device/<id>/retire')
@error_decorator
def retire_device(id):
    '''
    Changes the status of the device to inactive in the device database
    '''
    return device_scanner.retire_device(id)




def cache_img(file_like, basename):
    if not file_like:
        #TODO return link to "broken img"
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
        return {"files": matches}


@app.get('/browse/<folder:path>')
@error_decorator
def browse(folder):
    if folder == 'null':
        directory = RESULTS_DIR
    else:
        directory = '/'+folder
    files = {}
    for (dirpath, dirnames, filenames) in os.walk(directory):
        for name in filenames:
            abs_path = os.path.join(dirpath,name)
            size = os.path.getsize(abs_path)
            mtime = os.path.getmtime(abs_path)
            #rel_path = os.path.relpath(abs_path,directory)
            files[name] = {'abs_path':abs_path, 'size':size, 'mtime': mtime}
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
        IPs = []

        CFG.load()

        try:
            disk_usage = disk_free.split("\n")[1].split()

            #the following returns something like this: [['eno1', 'ec:b1:d7:66:2e:3a', '192.168.1.1'], ['enp0s20u12', '74:da:38:49:f8:2a', '155.198.232.206']]
            adapters_list = [ [i, netifaces.ifaddresses(i)[17][0]['addr'], netifaces.ifaddresses(i)[2][0]['addr']] for i in netifaces.interfaces() if 17 in netifaces.ifaddresses(i) and 2 in netifaces.ifaddresses(i) and netifaces.ifaddresses(i)[17][0]['addr'] != '00:00:00:00:00:00' ]
            for ad in adapters_list:
                CARDS [ ad[0] ] = {'MAC' : ad[1], 'IP' : ad[2]}
                IPs.append (ad[2])
            
           
            with os.popen('git rev-parse --abbrev-ref HEAD') as df:
                GIT_BRANCH = df.read() or "Not detected"
            #df = subprocess.Popen(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], stdout=subprocess.PIPE)
            #GIT_BRANCH = df.communicate()[0].decode('utf-8')
            
            with os.popen('git status -s -uno') as df:
                NEEDS_UPDATE = df.read() != ""

            #df = subprocess.Popen(['git', 'status', '-s', '-uno'], stdout=subprocess.PIPE)
            #NEEDS_UPDATE = df.communicate()[0].decode('utf-8') != ""
            
            with os.popen('systemctl status ethoscope_node.service') as df:
                try:
                    ACTIVE_SINCE = df.read().split("\n")[2] 
                except:
                    ACTIVE_SINCE = "Not running through systemd"

        except Exception as e:
            logging.error(e)

        return {'active_since': ACTIVE_SINCE, 'disk_usage': disk_usage, 'IPs' : IPs , 'CARDS': CARDS, 'GIT_BRANCH': GIT_BRANCH, 'NEEDS_UPDATE': NEEDS_UPDATE}
                
    elif req == 'time':
        return {'time':datetime.datetime.now().isoformat()}
        
    elif req == 'timestamp':
        return {'timestamp': datetime.datetime.now().timestamp() }
    
    elif req == 'log':
        with os.popen("journalctl -u ethoscope_node -rb") as log:
            l = log.read()
        return {'log': l}
    
    elif req == 'daemons':
        #returns active or inactive
        for daemon_name in SYSTEM_DAEMONS.keys():
        
            with os.popen("systemctl is-active %s" % daemon_name) as df:
                SYSTEM_DAEMONS[daemon_name]['active'] = df.read().strip()
        return SYSTEM_DAEMONS

    elif req == 'folders':
        return CFG.content['folders']

    elif req == 'users':
        return CFG.content['users']

    elif req == 'incubators':
        return CFG.content['incubators']
        
    elif req == 'sensors':
        return sensor_scanner.get_all_devices_info()

    else:
        raise NotImplementedError()

@app.post('/node-actions')
@error_decorator
def node_actions():
    action = bottle.request.json
    
    if action['action'] == 'restart':
        logging.info('User requested a service restart.')
        with os.popen("sleep 1; systemctl restart ethoscope_node.service") as po:
            r = po.read()
        
        return r
            
    elif action['action'] == 'close':
        close()
    
    elif action['action'] == 'adduser':
        return CFG.addUser(action['userdata'])

    elif action['action'] == 'addincubator':
        return CFG.addIncubator(action['incubatordata'])
    
    elif action['action'] == 'addsensor':
        return CFG.addSensor(action['sensordata'])
    
    elif action['action'] == 'updatefolders':
        for folder in action['folders'].keys():
            if os.path.exists(action['folders'][folder]['path']): 
                CFG.content['folders'][folder]['path'] = action['folders'][folder]['path']
                CFG.save()
                
        return CFG.content['folders']
        
    
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
def redirection_to_list(type):
    return bottle.redirect('/#/list/'+type)

#@app.get('/more')
#def redirection_to_more():
#    return bottle.redirect('/#/more/')
    
@app.get('/ethoscope/<id>')
def redirection_to_ethoscope(id):
    return bottle.redirect('/#/ethoscope/'+id)

@app.get('/more/<action>')
def redirection_to_more(action):
    return bottle.redirect('/#/more/'+action)

@app.get('/experiments')
def redirection_to_experiments():
    return bottle.redirect('/#/experiments')

@app.get('/resources')
def redirection_to_resources():
    return bottle.redirect('/#/resources')


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

    CFG = EthoscopeConfiguration()

    logging.getLogger().setLevel(logging.INFO)
    parser = optparse.OptionParser()
    parser.add_option("-D", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-p", "--port", dest="port", default=80, help="port")
    parser.add_option("-e", "--temporary-results-dir", dest="temp_results_dir", help="Where temporary result files are stored")

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]
    RESULTS_DIR = option_dict["temp_results_dir"] or CFG.content['folders']['temporary']['path']

    tmp_imgs_dir = tempfile.mkdtemp(prefix="ethoscope_node_imgs")
    device_scanner = None
    try:
        device_scanner = EthoscopeScanner(results_dir=RESULTS_DIR)
        device_scanner.start()
        
        sensor_scanner = SensorScanner()
        sensor_scanner.start()
        
        edb = ExperimentalDB()
        
#        #manually adds the sensors saved in the configuration file
#        for sensor in CFG.content['sensors']:
#            if CFG.content['sensors'][sensor]['active']:
#                sensor_scanner.add(CFG.content['sensors'][sensor]['name'], CFG.content['sensors'][sensor]['URL'])
        
        #######TO be remove when bottle changes to version 0.13
        server = "cherrypy"
        try:
            from bottle.cherrypy import wsgiserver
        except:
            #Trick bottle into thinking that cheroot is cherrypy
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
        sensor_scanner.stop()
        shutil.rmtree(tmp_imgs_dir)
        close()
