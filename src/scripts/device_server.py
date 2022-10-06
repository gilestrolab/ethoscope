__author__ = 'luis'

import logging
import traceback
from optparse import OptionParser

from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.record import ControlThreadVideoRecording
from ethoscope.web_utils.helpers import *

import subprocess
import json
import os
import glob
import time

from threading import Thread 

#from bottle import Bottle, ServerAdapter, request, server_names
import bottle

import socket
from zeroconf import ServiceInfo, Zeroconf

from ethoclient import send_command, listenerIsAlive

try:
    from cheroot.wsgi import Server as WSGIServer
except ImportError:
    from cherrypy.wsgiserver import CherryPyWSGIServer as WSGIServer


api = bottle.Bottle()

tracking_json_data = {}
recording_json_data = {}
update_machine_json_data = {}

"""

/upload/<id>                            POST    upload files to the ethoscope (masks, videos, etc)
/data/listfiles/<category>/<id>         GET     provides a list of files in the ethoscope data folders, that were either uploaded or generated (masks, videos, etc).

/<id>                                   GET     returns ID of the machine
/make_index                             GET     create an index.html file with all the h264 files in the machine
/rm_static_file/                        POST    remove file
/dumpSQLdb/<id>                         POST    performs a SQL dump of the default database

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
    
    if id != _MACHINE_ID:
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

    save_path = os.path.join(_ETHOSCOPE_UPLOAD, "{category}".format(category=category))
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
    return {"id": _MACHINE_ID}

@api.get('/make_index')
@error_decorator
def make_index():
    index_file = os.path.join(_ETHOSCOPE_DIR, "index.html")
    all_video_files = [y for x in os.walk(_ETHOSCOPE_DIR) for y in glob.glob(os.path.join(x[0], '*.h264'))]
    with open(index_file, "w") as index:
        for f in all_video_files:
            index.write(f + "\n")
    return {}

@api.post('/rm_static_file/<id>')
@error_decorator
def rm_static_file(id):
    data = bottle.request.body.read()
    data = json.loads(data)
    file_to_del = data["file"]
    if id != _MACHINE_ID:
        raise WrongMachineID

    if file_in_dir_r( file_to_del, _ETHOSCOPE_DIR ):
        os.remove(file_to_del)
    else:
        msg = "Could not delete file %s. It is not allowed to remove files outside of %s" % ( file_to_del, _ETHOSCOPE_DIR )
        logging.error(msg)
        raise Exception(msg)
    return data


dumping_thread = {'thread': Thread() , 'time' : 0}

@api.get('/dumpSQLdb/<id>')
@error_decorator
def db_dump(id):
    '''
    Asks the helper to perform a SQL dump of the database
    If a dump was done recently under this session we do not attempt a new one
    '''
    gap_in_minutes = 30 #do not attempt a dump if last one was done these many minutes ago
    
    global dumping_thread
    
    if id != _MACHINE_ID:
        raise WrongMachineID
    
    now = int ( time.time() / 60 ) 
    gap = now - dumping_thread['time']
    
    if not dumping_thread['thread'].is_alive() and gap > gap_in_minutes:

        dumping_thread['time'] = now
        dumping_thread['thread'] = Thread( target = SQL_dump )
        dumping_thread['thread'].start()
       
        return { 'Status' : 'Started', 'Started': gap }
    
    elif dumping_thread['thread'].is_alive():
    
        return { 'Status' : 'Dumping', 'Started': gap }

    elif not dumping_thread['thread'].is_alive() and gap < gap_in_minutes:
        
        return { 'Status' : 'Finished', 'Started': gap }


        

@api.post('/update/<id>')
def update_machine_info(id):
    '''
    Updates the private machine informations
    '''
    haschanged = False
    
    if id != _MACHINE_ID:
        raise WrongMachineID
        
    data = bottle.request.json
    update_machine_json_data.update(data['machine_options']['arguments'])
    
    if 'node_ip' in update_machine_json_data and update_machine_json_data['node_ip'] != get_machine_info(id)['etc_node_ip']:
        set_etc_hostname(update_machine_json_data['node_ip'])
        haschanged = True
    
    if 'etho_number' in update_machine_json_data and int(update_machine_json_data['etho_number']) != int(get_machine_info(id)['machine-number']):
        set_machine_name(update_machine_json_data['etho_number'])
        set_machine_id(update_machine_json_data['etho_number'])

        if 'useSTATIC' in update_machine_json_data:
            set_WIFI(ssid=update_machine_json_data['ESSID'], wpakey=update_machine_json_data['Key'], useSTATIC=update_machine_json_data['useSTATIC'])
        
        haschanged = True
    
    if 'ESSID' in update_machine_json_data and 'Key' in update_machine_json_data and (update_machine_json_data['ESSID'] != get_machine_info(id)['WIFI_SSID'] or update_machine_json_data['Key'] != get_machine_info(id)['WIFI_PASSWORD']):
        set_WIFI(ssid=update_machine_json_data['ESSID'], wpakey=update_machine_json_data['Key'])
        haschanged = True

    if 'useSTATIC' in update_machine_json_data and update_machine_json_data['useSTATIC'] != get_machine_info(id)['useSTATIC']:
        set_WIFI(ssid=update_machine_json_data['ESSID'], wpakey=update_machine_json_data['Key'], useSTATIC=update_machine_json_data['useSTATIC'])
        haschanged = True

    if 'isexperimental' in update_machine_json_data and update_machine_json_data['isexperimental'] != isExperimental():
        isExperimental(update_machine_json_data['isexperimental'])
        haschanged = True
    
    #Time comes as number of milliseconds from timestamp
    if 'datetime' in update_machine_json_data and update_machine_json_data['datetime']:
        tn = datetime.datetime.fromtimestamp(update_machine_json_data['datetime'])
        set_datetime(tn)
        

    return {"haschanged": haschanged}

@api.post('/controls/<id>/<action>')
@error_decorator
def controls(id, action):
    if id != _MACHINE_ID:
        raise WrongMachineID

    if action == 'start':
        data = bottle.request.json
        tracking_json_data.update(data)
        send_command(action, tracking_json_data)
        return info(id)

    elif action in ['stop', 'close', 'poweroff', 'reboot', 'restart']:

        send_command('stop')

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
        send_command(action, recording_json_data)
        return info(id)
        
    elif action == 'convertvideos':
        logging.info("Converting h264 chunks to mp4")
        subprocess.call(['/opt/ethoscope-device/scripts/tools/process_all_h264.py','-p','/ethoscope_data'])
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
    
    filelist = {'filelist' : []}
    
    if id != _MACHINE_ID:
        raise WrongMachineID

    path = os.path.join (_ETHOSCOPE_UPLOAD, category)

    if os.path.exists(path):
        filelist = {'filelist' : [{'filename': i, 'fullpath' : os.path.abspath(os.path.join(path,i))} for i in os.listdir(path)]}

    if category == 'video':
        converted_mp4s = [f for f in [ x[0] for x in os.walk(_ETHOSCOPE_DIR) ] if glob.glob(os.path.join(f, "*.mp4"))]
        filelist['filelist'] = filelist['filelist'] + [{'filename': os.path.basename(i), 'fullpath' : i} for i in glob.glob(_ETHOSCOPE_DIR+'/**/*.mp4', recursive=True)]


    return filelist


@api.get('/machine/<id>')
@error_decorator
def get_machine_info(id):
    """
    This is information about the ethoscope that is not changing in time such as hardware specs and configuration parameters
    {"node_ip": "192.168.1.2", "etc_node_ip": "192.168.1.2", "knows_node_ip": true, "hostname": "ETHOSCOPE107", "machine-name": "ETHOSCOPE_107", "machine-number": 107, "machine-id": "10799c8f41b04562a60eab6dfd1745e1", "kernel": "5.4.79-1-ARCH", "pi_version": "Raspberry Pi 3 Model B Rev 1.2", "camera": "This is a new ethoscope. Run tracking once to detect the camera module", "WIFI_SSID": "ETHOSCOPE_WIFI", "WIFI_PASSWORD": "ETHOSCOPE_1234", "SD_CARD_AGE": 14851.871500253677, "partitions": [{"Filesystem": "/dev/root", "Type": "ext4", "Size": "9.2G", "Used": "3.4G", "Avail": "5.3G", "Use%": "40%", "Mounted": "/"}, {"Filesystem": "devtmpfs", "Type": "devtmpfs", "Size": "339M", "Used": "0", "Avail": "339M", "Use%": "0%", "Mounted": "/dev"}, {"Filesystem": "tmpfs", "Type": "tmpfs", "Size": "372M", "Used": "0", "Avail": "372M", "Use%": "0%", "Mounted": "/dev/shm"}, {"Filesystem": "tmpfs", "Type": "tmpfs", "Size": "149M", "Used": "440K", "Avail": "149M", "Use%": "1%", "Mounted": "/run"}, {"Filesystem": "tmpfs", "Type": "tmpfs", "Size": "4.0M", "Used": "0", "Avail": "4.0M", "Use%": "0%", "Mounted": "/sys/fs/cgroup"}, {"Filesystem": "tmpfs", "Type": "tmpfs", "Size": "372M", "Used": "0", "Avail": "372M", "Use%": "0%", "Mounted": "/tmp"}, {"Filesystem": "/dev/mmcblk0p1", "Type": "vfat", "Size": "120M", "Used": "38M", "Avail": "83M", "Use%": "32%", "Mounted": "/boot"}, {"Filesystem": "/dev/mmcblk0p3", "Type": "f2fs", "Size": "20G", "Used": "1.1G", "Avail": "19G", "Use%": "6%", "Mounted": "/var"}], "SD_CARD_NAME": "20201126_ethoscope_000.img"}
    """

    if id is not None and id != _MACHINE_ID:
        raise WrongMachineID

    machine_info = {}
    machine_info['node_ip'] = bottle.request.environ.get('HTTP_X_FORWARDED_FOR') or bottle.request.environ.get('REMOTE_ADDR')
    
    try:
        machine_info['etc_node_ip'] = get_etc_hostnames()[NODE]
    except:
        machine_info['etc_node_ip'] = "not set"

    machine_info['knows_node_ip'] = ( machine_info['node_ip'] == machine_info['etc_node_ip'] )
    machine_info['hostname'] = os.uname()[1]
    machine_info['isExperimental'] = isExperimental()
    
    machine_info['machine-name'] = _MACHINE_NAME
    
    try:
        machine_info['machine-number'] = int ( machine_info['machine-name'].split("_")[1] )
    except:
        machine_info['machine-number'] = 0
        
        
    machine_info['machine-id'] = _MACHINE_ID
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
    try:
        machine_info['useSTATIC'] = (get_WIFI()['IP'].strip().upper() == 'STATIC')
    except:
        machine_info['useSTATIC'] = False
        
    machine_info['SD_CARD_AGE'] = get_SD_CARD_AGE()
    machine_info['partitions'] = get_partition_infos()
    machine_info['SD_CARD_NAME'] = get_SD_CARD_NAME()
    
    return machine_info


@api.get('/data/<id>')
@error_decorator
def info(id):
    """
    This is information that is changing in time as the machine operates, such as FPS during tracking, CPU temperature etc
    
    {
     "status": "stopped", 
     "time": 1601748840.9973018, 
     "error": null, 
     "log_file": "/ethoscope_data/results/ethoscope.log", 
     "dbg_img": "/ethoscope_data/results/dbg_img.png", 
     "last_drawn_img": "/tmp/ethoscope_l99ys8nw/last_img.jpg", 
     "db_name": "ETHOSCOPE_107_db", 
     "monitor_info": {"last_positions": null, "last_time_stamp": 0, "fps": 0}, 
     "experimental_info": {}, 
     "CPU_temp": 46.2
     }

     "version": {"id": "4bdcc9c4a1ef06f7226856aaef5e078b1b164b1e", "date": "2020-11-23 18:50:31"}, 
     "id": "10799c8f41b04562a60eab6dfd1745e1", 
     "name": "ETHOSCOPE_107", 

    
    """
    
    if id != _MACHINE_ID:
        raise WrongMachineID

    runninginfo = send_command('info')
    runninginfo.update ( { "CPU_temp" : get_core_temperature(), 
                           "underpowered" : underPowered(),
                           "current_timestamp" : bottle.time.time() } )
        
    # except:
        # runninginfo = {
                        # "status": 'not available',
                        # "id" : _MACHINE_ID,
                        # "name" : _MACHINE_NAME,
                        # "version" : _GIT_VERSION,
                        # "time" : bottle.time.time()
                       # }
    
    return runninginfo

@api.get('/user_options/<id>')
@error_decorator
def user_options(id):
    '''
    Passing back options regarding what information can be changed on the the device. This populates the form on the node GUI
    '''
    if id != _MACHINE_ID:
        raise WrongMachineID

    return {
        "tracking":ControlThread.user_options(),
        "recording":ControlThreadVideoRecording.user_options(),
        "streaming": {},
        "update_machine": { "machine_options": [{"overview": "Machine information that can be set by the user",
                            "arguments": [
                                {"type": "number", "name":"etho_number", "description": "An ID number (5-250) unique to this ethoscope","default": get_machine_info(id)['machine-number'] },
                                {"type": "boolean", "name":"isexperimental", "description": "Specify if the ethoscope is to be treated as experimental", "default": isExperimental()}, 
                                {"type": "boolean", "name":"useSTATIC", "description": "Use a static IP address instead of obtaining one with DHCP. The last number in the IP address will be the current ethoscope number", "default" : get_machine_info(id)['useSTATIC']},
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
    os._exit(exit_status)

if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-p", "--port", dest="port", default=9000, help="port")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")

    (options, args) = parser.parse_args()
    option_dict = vars(options)

    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]

    if DEBUG:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    _MACHINE_ID = get_machine_id()
    _MACHINE_NAME = get_machine_name()
    _GIT_VERSION = get_git_version()
    
    _ETHOSCOPE_UPLOAD = '/ethoscope_data/upload'
    _ETHOSCOPE_DIR = '/ethoscope_data/results'

    if not listenerIsAlive():
        logging.error('An Ethoscope controlling service is not running on this machine! I will be starting one for you but this is not the way this should work. Update your SD card.')

        from device_listener import commandingThread
        
        ethoscope_info = { 'MACHINE_ID' : _MACHINE_ID,
                      'MACHINE_NAME' : _MACHINE_NAME,
                      'GIT_VERSION' : _GIT_VERSION,
                      'ETHOSCOPE_UPLOAD' : _ETHOSCOPE_UPLOAD,
                      'ETHOSCOPE_DIR' : _ETHOSCOPE_DIR,
                      'DATA' : ''
                    }

        ethoscope = commandingThread(ethoscope_info)
        ethoscope.start()

    try:
        # Register the ethoscope using zeroconf so that the node knows about it.
        hostname = socket.gethostname()
        uid = "%s-%s" % ( hostname, _MACHINE_ID )
        
        ip_attempts = 0
        ip_address = None
        logging.warning("Waiting for a network connection")
        
        
        #tries for one minute or until an IP ip_address is obtained
        while ip_address is None and ip_attempts < 60:

            try:
                ip_address = socket.gethostbyname(hostname)
            except:
                pass

            ip_attempts += 1
            time.sleep(1)
            
        logging.info("Registering device on zeroconf with IP: %s" % ip_address)
            
        serviceInfo = ServiceInfo("_ethoscope._tcp.local.",
                        uid + "._ethoscope._tcp.local.",
                        addresses = [socket.inet_aton(ip_address)],
                        port = PORT,
                        properties = {
                            'version': '0.2',
                            'id_page': '/id',
                            'id' : _MACHINE_ID
                        } )

        try:
            zeroconf = Zeroconf(zeroconf.IPVersion.V4Only)
        except:
            zeroconf = Zeroconf()
            
        zeroconf.register_service(serviceInfo)

        #the webserver on the ethoscope side is quite basic so we can safely run the original bottle version based on WSGIRefServer()
        bottle.run(api, host='0.0.0.0', port=PORT, debug=DEBUG)

    
    #this applies to any network error the will prevent zeroconf or the webserver from working
    except Exception as e:
        logging.error(traceback.format_exc())
        try:
            zeroconf.unregister_service(serviceInfo)
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
