from bottle import *
import subprocess
import socket
import logging
import traceback
from ethoscope_node.utils.helpers import  get_local_ip, get_internet_ip
from ethoscope_node.utils.device_scanner import DeviceScanner
from os import walk
import optparse
import zipfile
import datetime
import fnmatch
import tempfile
import shutil

app = Bottle()
STATIC_DIR = "../static"

def error_decorator(func):
    """
    A simple decorator to return an error dict so we can display it the ui
    """
    def func_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc(e))
            return {'error': traceback.format_exc(e)}
    return func_wrapper

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root=STATIC_DIR)

@app.route('/tmp_static/<filepath:path>')
def server_tmp_static(filepath):
    return static_file(filepath, root=tmp_imgs_dir)

@app.route('/download/<filepath:path>')
def server_download(filepath):
    return static_file(filepath, root="/", download=filepath)

@app.route('/')
def index():
    return static_file('index.html', root=STATIC_DIR)


@app.hook('after_request')
def enable_cors():
    """
    You need to add some headers to each request.
    Don't use the wildcard '*' for Access-Control-Allow-Origin in production.
    """
    response.headers['Access-Control-Allow-Origin'] = 'http://localhost:8888'
    response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'


#################################
# API to connect with ethoscopes
#################################


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


@app.get('/device/<id>/user_options')
@error_decorator
def get_device_options(id):
    device = device_scanner.get_device(id)
    return device.user_options()


#Get the information of one Sleep Monitor
@app.get('/device/<id>/last_img')
@error_decorator
def get_device_last_img(id):
    device = device_scanner.get_device(id)
    if "status" not in device.info().keys() or device.info()["status"] == "not_in use":
        raise Exception("Device %s is not in use, no image" % id )
    file_like = device.last_image()
    if not file_like:
        raise Exception("No image for %s" % id)
    basename = os.path.join(tmp_imgs_dir, id + "_last_img.jpg")
    return cache_img(file_like, basename)



#Get the information of one Sleep Monitor
@app.get('/device/<id>/dbg_img')
@error_decorator
def get_device_dbg_img(id):

    device = device_scanner.get_device(id)
    file_like = device.dbg_img()
    basename = os.path.join(tmp_imgs_dir, id + "_debug.png")
    return cache_img(file_like, basename)



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
    post_data = request.body.read()
    device = device_scanner.get_device(id)
    device.send_instruction(instruction, post_data)
    return get_device_info(id)
@app.post('/device/<id>/log')
@error_decorator
def get_log(id):
    raise NotImplementedError()


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
    for (dirpath, dirnames, filenames) in walk(directory):
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

@app.get('/node/<req>')
@error_decorator
def node_info(req):#, device):
    if req == 'info':
        df = subprocess.Popen(['df', RESULTS_DIR, '-h'], stdout=subprocess.PIPE)
        disk_free = df.communicate()[0]
        disk_usage = RESULTS_DIR+" Not Found on disk"
        # ip = "No IP assigned, check cable"
        # MAC_addr = "Not detected"
        # local_ip = ""
        # try:
        #     disk_usage = disk_free.split("\n")[1].split()
        #     addrs = ifaddresses(INTERNET_DEVICE)
        #     MAC_addr = addrs[AF_LINK][0]["addr"]
        #
        #     ip = addrs[AF_INET][0]["addr"]
        #     local_addrs = ifaddresses(SUBNET_DEVICE)
        #     local_ip = local_addrs[AF_INET][0]["addr"]
        # except Exception as e:
        #     logging.error(e)
        #fixme
        MAC_addr = "TODO"
        return {'disk_usage': disk_usage, 'MAC_addr': MAC_addr, 'ip': WWW_IP,
                'local_ip':LOCAL_IP}
    if req == 'time':
        return {'time':datetime.datetime.now().isoformat()}
    if req == 'timestamp':
        return {'timestamp': time.time()}
    else:
        raise NotImplementedError()

@app.post('/node-actions')
@error_decorator
def node_actions():
    action = request.json
    if action['action'] == 'poweroff':
        logging.info('User request a poweroff, shutting down system. Bye bye.')

        close()
        #poweroff = subprocess.Popen(['poweroff'], stdout=subprocess.PIPE)
    elif action['action'] == 'close':
        close()
    else:
        raise NotImplementedError()

@app.post('/remove_files')
@error_decorator
def remove_files():
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

@app.get('/list/<type>')
def redirection_to_home(type):
    return redirect('/#/list/'+type)
@app.get('/more')
def redirection_to_home():
    return redirect('/#/more/')
@app.get('/ethoscope/<id>')
def redirection_to_home(id):
    return redirect('/#/ethoscope/'+id)

@app.get('/device/<id>/ip')
@error_decorator
def redirection_to_home(id):
    raise NotImplementedError
    #
    # dev_list = device_scanner.get_device_list()
    # for id, data  in dev_list.items():
    #     if id == id:
    #         return data["ip"]
    # return "None"


@app.get('/more/<action>')
def redirection_to_more(action):
    return redirect('/#/more/'+action)

def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)
    

#======================================================================================================================#

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    parser = optparse.OptionParser()
    parser.add_option("-D", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-p", "--port", dest="port", default=80,help="port")
    parser.add_option("-l", "--local", dest="local", default=False, help="Run on localhost (run a node and device on the same machine, for development)", action="store_true")
    parser.add_option("-e", "--results-dir", dest="results_dir", default="/ethoscope_results",help="Where temporary result files are stored")
    parser.add_option("-r", "--subnet-ip", dest="subnet_ip", default="192.169.123.0", help="the ip of the router in your setup")



    (options, args) = parser.parse_args()

    option_dict = vars(options)
    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]
    RESULTS_DIR = option_dict["results_dir"]
    max_address = 255 if DEBUG else 5
    LOCAL_IP = get_local_ip(option_dict["subnet_ip"], max_node_subnet_address=max_address, localhost=option_dict["local"])

    try:
        WWW_IP = get_internet_ip()
    except Exception as e:
        logging.warning("Could not access internet!")
        logging.warning(traceback.format_exc(e))
        WWW_IP = None

    tmp_imgs_dir = tempfile.mkdtemp(prefix="ethoscope_node_imgs")
    device_scanner = None
    try:
        device_scanner = DeviceScanner(LOCAL_IP, results_dir=RESULTS_DIR)
        #device_scanner = DeviceScanner( results_dir=RESULTS_DIR)
        device_scanner.start()
        run(app, host='0.0.0.0', port=PORT, debug=DEBUG, server='cherrypy')

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
        device_scanner.stop()
        shutil.rmtree(tmp_imgs_dir)
        close()
