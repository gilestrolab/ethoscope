__author__ = 'luis'

import logging
import traceback
from optparse import OptionParser
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.helpers import get_machine_id, get_machine_name, get_git_version, file_in_dir_r, get_etc_hostnames, pi_version, set_machine_name, set_machine_id, set_etc_hostname, get_WIFI, set_WIFI
from ethoscope.web_utils.record import ControlThreadVideoRecording
from subprocess import call
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
    if id != machine_id:
        raise WrongMachineID
        
    data = bottle.request.json
    update_machine_json_data.update(data['machine_options']['arguments'])
    
    set_etc_hostname(update_machine_json_data['node_ip'])
    set_machine_name(update_machine_json_data['etho_number'])
    set_machine_id(update_machine_json_data['etho_number'])
    set_WIFI(ssid=update_machine_json_data['ESSID'], wpakey=update_machine_json_data['Key'])

    return get_machine_info(id)
    

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

    elif action in ['stop', 'close', 'poweroff', 'reboot']:
        if control.info['status'] == 'running' or control.info['status'] == "recording" or control.info['status'] == "streaming" :
            # logging.info("Stopping monitor")
            logging.warning("Stopping monitor")
            control.stop()
            logging.warning("Joining monitor")
            control.join()
            logging.warning("Monitor joined")
            logging.warning("Monitor stopped")
            # logging.info("Monitor stopped")

        if action == 'close':
            close()

        if action == 'poweroff':
            logging.info("Stopping monitor due to poweroff request")
            logging.info("Powering off Device.")
            call('poweroff')

        if action == 'reboot':
            logging.info("Stopping monitor due to reboot request")
            logging.info("Powering off Device.")
            call('reboot')


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

    if machine_id != id:
        raise WrongMachineID

    machine_info = {}
    machine_info['node_ip'] = bottle.request.environ.get('HTTP_X_FORWARDED_FOR') or bottle.request.environ.get('REMOTE_ADDR')
    machine_info['etc_node_ip'] = get_etc_hostnames()['node']

    machine_info['knows_node_ip'] = ( machine_info['node_ip'] == machine_info['etc_node_ip'] )
    machine_info['hostname'] = os.uname()[1]
    machine_info['machine-name'] = get_machine_name()
    machine_info['machine-id'] = get_machine_id()
    machine_info['kernel'] = os.uname()[2]
    machine_info['pi_version'] = pi_version()
    machine_info['WIFI_SSID'] = get_WIFI()['ESSID']
    machine_info['WIFI_PASSWORD'] = get_WIFI()['Key']
    
    return machine_info


@api.get('/data/<id>')
@error_decorator
def info(id):

    if machine_id != id:
        raise WrongMachineID
        
    info = control.info
    info["current_timestamp"] = bottle.time.time()
    
    return info

@api.get('/user_options/<id>')
@error_decorator
def user_options(id):
    '''
    Passing back options regarding the capabilities of the device
    '''
    if machine_id != id:
        raise WrongMachineID
    return {
        "tracking":ControlThread.user_options(),
        "recording":ControlThreadVideoRecording.user_options(),
        "streaming": {},
        "update_machine": { "machine_options": [{"overview": "Machine information that can be set by the user",
                            "arguments": [
                                {"type": "number", "name":"etho_number", "description": "An ID number (1-999) unique to this ethoscope","default": int(info(id)['name'].split("_")[1]) },
                                {"type": "str", "name":"node_ip", "description": "The IP address that you want to record as node","default": get_machine_info(id)['node_ip']},
                                {"type": "str", "name":"ESSID", "description": "The name of the WIFI SSID","default":"ETHOSCOPE_WIFI"},
                                {"type": "str", "name":"Key", "description": "The WPA password for the WIFI SSID","default":"ETHOSCOPE_1234"}],
                            "name" : "Ethoscope Options"}],

                               } }

@api.get('/data/log/<id>')
@error_decorator
def get_log(id):
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
    parser.add_option("-e", "--results-dir", dest="results_dir", default=ETHOSCOPE_DIR, help="Where temporary result files are stored")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")


    (options, args) = parser.parse_args()
    option_dict = vars(options)

    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]

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
        logging.basicConfig(level=logging.DEBUG)
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
        hostname=socket.gethostname()
        address=socket.gethostbyname(hostname+".local")
        serviceInfo = ServiceInfo("_ethoscope._tcp.local.",
                        hostname+"._ethoscope._tcp.local.",
                        address=socket.inet_aton(address),
                        port=PORT,
                        properties={
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
