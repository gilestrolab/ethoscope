__author__ = 'luis'

import logging
import traceback
from optparse import OptionParser
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.helpers import *
from ethoscope.web_utils.record import ControlThreadVideoRecording
import subprocess
import json
import os
import glob

#from bottle import Bottle, ServerAdapter, request, server_names
import bottle

import socket
from zeroconf import ServiceInfo, Zeroconf

try:
    from cheroot.wsgi import Server as WSGIServer
except ImportError:
    from cherrypy.wsgiserver import CherryPyWSGIServer as WSGIServer


api = bottle.Bottle()

tracking_json_data = {}
recording_json_data = {}
update_machine_json_data = {}
ETHOSCOPE_DIR = None

"""
/upload/<id>                            POST    upload files to the ethoscope (masks, videos, etc)
/data/listfiles/<category>/<id>         GET     provides a list of files in the ethoscope data folders, that were either uploaded or generated (masks, videos, etc).

/<id>                                   GET     returns ID of the machine
/make_index                             GET     create an index.html file with all the h264 files in the machine
/rm_static_file/                        POST    remove file
/update/<id>                            POST    update machine parameters (number, name, nodeIP, WIFI credentials, time)
/controls/<id>/<action>                 POST    activate actions (tracking, recording, etc)
/machine/<id>                           GET     information about the ethoscope that is not changing in time such as hardware specs and configuration parameters
/data/<id>                              GET     get information regarding the current status of the machine (e.g. FPS, temperature, etc)
/user_options/<id>                      GET     Passing back options regarding what information can be changed on the the device. This populates the form on the node GUI
/data/log/<id>                          GET     fetch the journalctl log

"""

class WrongMachineID(Exception):
    pass


def error_decorator(func):
    """
    A simple decorator to return an error dict so we can display it the ui
    """
    def func_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            return {'error': traceback.format_exc()}
    return func_wrapper

@api.route('/upload/<id>', method='POST')
def do_upload(id):
    
    if id != machine_id:
        raise WrongMachineID
    
    upload = bottle.request.files.get('upload')
    name, ext = os.path.splitext(upload.filename)

    if ext in ('.mp4', '.avi'):
        category = 'video'
    elif ext in ('.jpg', '.png'):
        category = 'images'
    elif ext in ('.msk'):
        category = 'masks'
    else:
        return {'result' : 'fail', 'comment' : "File extension not allowed. You can upload only movies, images, or masks"}

    save_path = os.path.join(ETHOSCOPE_UPLOAD, "{category}".format(category=category))
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    file_path = "{path}/{file}".format(path=save_path, file=upload.filename)
    upload.save(file_path)
    return { 'result' : 'success', 'path' : file_path }

@api.route('/static/<filepath:path>')
def server_static(filepath):
    return bottle.static_file(filepath, root="/")

@api.route('/download/<filepath:path>')
def server_static(filepath):
    return bottle.static_file(filepath, root="/", download=filepath)

@api.get('/id')
@error_decorator
def name():
    return {"id": control.info["id"]}

@api.get('/make_index')
@error_decorator
def make_index():
    index_file = os.path.join(ETHOSCOPE_DIR, "index.html")
    all_video_files = [y for x in os.walk(ETHOSCOPE_DIR) for y in glob.glob(os.path.join(x[0], '*.h264'))]
    with open(index_file, "w") as index:
        for f in all_video_files:
            index.write(f + "\n")
    return {}

@api.post('/rm_static_file/<id>')
@error_decorator
def rm_static_file(id):
    global control
    global record

    data = bottle.request.body.read()
    data = json.loads(data)
    file_to_del = data["file"]
    if id != machine_id:
        raise WrongMachineID

    if file_in_dir_r(file_to_del, ETHOSCOPE_DIR ):
        os.remove(file_to_del)
    else:
        msg = "Could not delete file %s. It is not allowed to remove files outside of %s" % (file_to_del, ETHOSCOPE_DIR)
        logging.error(msg)
        raise Exception(msg)
    return data

@api.post('/update/<id>')
def update_machine_info(id):
    '''
    Updates the private machine informations
    '''
    haschanged = False
    
    if id != machine_id:
        raise WrongMachineID
        
    data = bottle.request.json
    update_machine_json_data.update(data['machine_options']['arguments'])
    
    if 'node_ip' in update_machine_json_data and update_machine_json_data['node_ip'] != get_machine_info(id)['etc_node_ip']:
        set_etc_hostname(update_machine_json_data['node_ip'])
        haschanged = True
    
    if 'etho_number' in update_machine_json_data and int(update_machine_json_data['etho_number']) != int(get_machine_info(id)['machine-number']):
        set_machine_name(update_machine_json_data['etho_number'])
        set_machine_id(update_machine_json_data['etho_number'])
        haschanged = True
    
    if 'ESSID' in update_machine_json_data and 'Key' in update_machine_json_data and (update_machine_json_data['ESSID'] != get_machine_info(id)['WIFI_SSID'] or update_machine_json_data['Key'] != get_machine_info(id)['WIFI_PASSWORD']):
        set_WIFI(ssid=update_machine_json_data['ESSID'], wpakey=update_machine_json_data['Key'])
        haschanged = True

    if 'isexperimental' in update_machine_json_data and update_machine_json_data['isexperimental'] != isExperimental():
        isExperimental(update_machine_json_data['isexperimental'])
        haschanged = True
    
    #Time comes as number of milliseconds from timestamp
    if 'datetime' in update_machine_json_data and update_machine_json_data['datetime']:
        tn = datetime.datetime.fromtimestamp(update_machine_json_data['datetime'])
        set_datetime(tn)
        

    return {"haschanged": haschanged}
    #return get_machine_info(id)

    

@api.post('/controls/<id>/<action>')
@error_decorator
def controls(id, action):
    global control
    global record
    if id != machine_id:
        raise WrongMachineID

    if action == 'start':
        data = bottle.request.json
        tracking_json_data.update(data)
        
        control = None
        control = ControlThread(machine_id=machine_id,
                                name=machine_name,
                                version=version,
                                ethoscope_dir=ETHOSCOPE_DIR,
                                data=tracking_json_data)

        control.start()
        return info(id)

    elif action in ['stop', 'close', 'poweroff', 'reboot', 'restart']:
        
        if control.info['status'] in ['running', 'recording', 'streaming'] :
            logging.info("Stopping monitor")
            control.stop()
            logging.info("Joining monitor")
            control.join()
            logging.info("Monitor joined")
            logging.info("Monitor stopped")

        if action == 'close':
            close()

        if action == 'poweroff':
            logging.info("Stopping monitor due to poweroff request")
            logging.info("Powering off Device.")
            subprocess.call('poweroff')

        if action == 'reboot':
            logging.info("Stopping monitor due to reboot request")
            logging.info("Powering off Device.")
            subprocess.call('reboot')

        if action == 'restart':
            logging.info("Restarting service")
            subprocess.call(['systemctl', 'restart', 'ethoscope_device'])


        return info(id)

    elif action in ['start_record', 'stream']:
        data = bottle.request.json
        recording_json_data.update(data)
        logging.warning("Recording or Streaming video, data is %s" % str(data))
        control = None
        control = ControlThreadVideoRecording(machine_id=machine_id,
                                              name=machine_name,
                                              version=version,
                                              ethoscope_dir=ETHOSCOPE_DIR,
                                              data=recording_json_data)

        control.start()
        return info(id)
        
    else:
        raise Exception("No such action: %s" % action)

@api.get('/data/listfiles/<category>/<id>')
@error_decorator
def list_data_files(category, id):
    '''
    provides a list of files in the ethoscope data folders, that were either uploaded or generated
    category is the name of the folder
    this is not meant to report db files or h264 files but it's supposed to be working for things like masks and other user generated files
    '''
    if id != machine_id:
        raise WrongMachineID

    path = os.path.join (ETHOSCOPE_UPLOAD, category)

    if os.path.exists(path):
        return {'filelist' : [{'filename': i, 'fullpath' : os.path.abspath(os.path.join(path,i))} for i in os.listdir(path)]}

    return {}


@api.get('/machine/<id>')
@error_decorator
def get_machine_info(id):
    """
    This is information about the ethoscope that is not changing in time such as hardware specs and configuration parameters
    """

    if id is not None and id != machine_id:
        raise WrongMachineID

    machine_info = {}
    machine_info['node_ip'] = bottle.request.environ.get('HTTP_X_FORWARDED_FOR') or bottle.request.environ.get('REMOTE_ADDR')
    
    try:
        machine_info['etc_node_ip'] = get_etc_hostnames()[NODE]
    except:
        machine_info['etc_node_ip'] = "not set"

    machine_info['knows_node_ip'] = ( machine_info['node_ip'] == machine_info['etc_node_ip'] )
    machine_info['hostname'] = os.uname()[1]
    
    machine_info['machine-name'] = get_machine_name()
    
    try:
        machine_info['machine-number'] = int ( machine_info['machine-name'].split("_")[1] )
    except:
        machine_info['machine-number'] = 0
        
        
    machine_info['machine-id'] = get_machine_id()
    machine_info['kernel'] = os.uname()[2]
    machine_info['pi_version'] = pi_version()
    machine_info['camera'] = getPiCameraVersion()
    
    try:
        machine_info['WIFI_SSID'] = get_WIFI()['ESSID']
    except: 
        machine_info['WIFI_SSID'] = "not set"
    try:    
        machine_info['WIFI_PASSWORD'] = get_WIFI()['Key']
    except:
        machine_info['WIFI_PASSWORD'] = "not set"
    
    machine_info['SD_CARD_AGE'] = get_SD_CARD_AGE()
    machine_info['partitions'] = get_partition_infos()
    
    return machine_info


@api.get('/data/<id>')
@error_decorator
def info(id):
    """
    This is information that is changing in time as the machine operates, such as FPS during tracking, CPU temperature etc
    """
    
    info = {}
    if machine_id != id:
        raise WrongMachineID
    
    if control is not None: 
        info = control.info
        
    info["current_timestamp"] = bottle.time.time()
    info["CPU_temp"] = get_core_temperature()
    return info

@api.get('/user_options/<id>')
@error_decorator
def user_options(id):
    '''
    Passing back options regarding what information can be changed on the the device. This populates the form on the node GUI
    '''
    if machine_id != id:
        raise WrongMachineID
    
    
        
    return {
        "tracking":ControlThread.user_options(),
        "recording":ControlThreadVideoRecording.user_options(),
        "streaming": {},
        "update_machine": { "machine_options": [{"overview": "Machine information that can be set by the user",
                            "arguments": [
                                {"type": "number", "name":"etho_number", "description": "An ID number (1-999) unique to this ethoscope","default": get_machine_info(id)['machine-number'] },
                                {"type": "boolean", "name":"isexperimental", "description": "Specify if the ethoscope is to be treated as experimental", "default": isExperimental()}, 
                                {"type": "str", "name":"node_ip", "description": "The IP address that you want to record as the node (do not change this value unless you know what you are doing!)","default": get_machine_info(id)['node_ip']},
                                {"type": "str", "name":"ESSID", "description": "The name of the WIFI SSID","default": get_machine_info(id)['WIFI_SSID'] },
                                {"type": "str", "name":"Key", "description": "The WPA password for the WIFI SSID","default": get_machine_info(id)['WIFI_PASSWORD'] }],
                            "name" : "Ethoscope Options"}],

                               } }

@api.get('/data/log/<id>')
@error_decorator
def get_log(id):
    '''
    returns the journalctl log
    '''
    output = "No log available"
    try:
        with os.popen('journalctl -u ethoscope_device.service -rb') as p:
            output = p.read()

    except Exception as e:
        logging.error(traceback.format_exc())

    return {'message' : output}


def close(exit_status=0):
    global control
    if control is not None and control.is_alive():
        control.stop()
        control.join()
        control=None
    else:
        control = None
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

    ETHOSCOPE_DIR = "/ethoscope_data/results"
    ETHOSCOPE_UPLOAD = "/ethoscope_data/upload"

    parser = OptionParser()
    parser.add_option("-r", "--run", dest="run", default=False, help="Runs tracking directly", action="store_true")
    parser.add_option("-s", "--stop-after-run", dest="stop_after_run", default=False, help="When -r, stops immediately after. otherwise, server waits", action="store_true")
    parser.add_option("-v", "--record-video", dest="record_video", default=False, help="Records video instead of tracking", action="store_true")
    parser.add_option("-j", "--json", dest="json", default=None, help="A JSON config file")
    parser.add_option("-p", "--port", dest="port", default=9000, help="port")
    parser.add_option("-n", "--node", dest="node", default="node", help="The hostname of the computer running the node")
    parser.add_option("-e", "--results-dir", dest="results_dir", default=ETHOSCOPE_DIR, help="Where temporary result files are stored")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")


    (options, args) = parser.parse_args()
    option_dict = vars(options)

    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]
    NODE = option_dict["node"]

    machine_id = get_machine_id()
    machine_name = get_machine_name()
    version = get_git_version()


    if option_dict["json"]:
        with open(option_dict["json"]) as f:
            json_data= json.loads(f.read())
    else:
        data = None
        json_data = {}

    ETHOSCOPE_DIR = option_dict["results_dir"]

    if option_dict["record_video"]:
        recording_json_data = json_data
        control = ControlThreadVideoRecording(machine_id=machine_id,
                                              name=machine_name,
                                              version=version,
                                              ethoscope_dir=ETHOSCOPE_DIR,
                                              data=recording_json_data)

    else:
        tracking_json_data = json_data
        control = ControlThread(machine_id=machine_id,
                                name=machine_name,
                                version=version,
                                ethoscope_dir=ETHOSCOPE_DIR,
                                data=tracking_json_data)


    if DEBUG:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    if option_dict["stop_after_run"]:
         control.set_evanescent(True) # kill program after first run

    if option_dict["run"] or control.was_interrupted:
        control.start()

#    try:
#        run(api, host='0.0.0.0', port=port, server='cherrypy',debug=option_dict["debug"])

    try:
        # Register the ethoscope using zeroconf so that the node knows about it.
        # I need an address to register the service, but I don't understand which one (different
        # interfaces will have different addresses). The python module zeroconf fails if I don't
        # provide one, and the way it gets supplied doesn't appear to be IPv6 compatible. I'll put
        # in whatever I get from "gethostbyname" but not trust that in the code on the node side.

        
        # we include the machine-id together with the hostname to make sure each device is really unique
        # moreover, we will burn the ETHOSCOPE_000 img with a non existing /etc/machine-id file
        # to make sure each burned image will get a unique machine-id at the first boot
        
        hostname = socket.gethostname()
        uid = "%s-%s" % ( hostname, get_machine_id() )
        
        address = False
        logging.warning("Waiting for a network connection")
        
        while address is False:
            try:
                address = socket.gethostbyname(hostname+".local")
                #this returns something like '192.168.1.4' - when both connected, ethernet IP has priority over wifi IP
            except:
                pass
                #address = socket.gethostbyname(hostname)
                #this returns '127.0.1.1' and it is useless
            
            
        serviceInfo = ServiceInfo("_ethoscope._tcp.local.",
                        uid + "._ethoscope._tcp.local.",
                        address = socket.inet_aton(address),
                        port = PORT,
                        properties = {
                            'version': '0.0.1',
                            'id_page': '/id',
                            'user_options_page': '/user_options',
                            'static_page': '/static',
                            'controls_page': '/controls',
                            'user_options_page': '/user_options'
                        } )
        zeroconf = Zeroconf()
        zeroconf.register_service(serviceInfo)

        ####### THIS IS A BIG MESS AND NEEDS TO BE FIXED. To be remove when bottle changes to version 0.13

        SERVER = "cheroot"
        try:
            #This checks if the patch has to be applied or not. We check if bottle has declared cherootserver
            #we assume that we are using cherrypy > 9
            from bottle import CherootServer
        except:
            #Trick bottle to think that cheroot is actulay cherrypy server, modifies the server_names allowed in bottle
            #so we use cheroot in background.
            SERVER="cherrypy"
            bottle.server_names["cherrypy"]=CherootServer(host='0.0.0.0', port=PORT)
            logging.warning("Cherrypy version is bigger than 9, we have to change to cheroot server")
            pass
        #########

        bottle.run(api, host='0.0.0.0', port=PORT, debug=DEBUG, server=SERVER)

    except Exception as e:
        logging.error(traceback.format_exc())
        try:
            zeroconf.unregister_service(serviceInfo)
            zeroconf.close()
        except:
            pass
        close(1)
        
    finally:
        try:
            zeroconf.unregister_service(serviceInfo)
            zeroconf.close()
        except:
            pass
        close()
