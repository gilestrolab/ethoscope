from bottle import *
import shlex
import urllib2
import subprocess
import json
import multiprocessing
import logging
import traceback
from psvnode.utils.acquisition import Acquisition

app = Bottle()
STATIC_DIR = "../../static"


def scan_url(url, timeout=0.5, port=9000):
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
        data = json.loads(message)
        data['ip'] = url
        return data
    except urllib2.URLError:
        return
    except Exception as e:
        logging.error("Unexpected error whilst scanning url: %s" % url )
        raise e
def format_post_get_url(id, what,type=None, port=9000):
    """
    Just a routine to format our GET urls. This improves readability whilst allowing us to change convention (e.g. port) without rewriting everything.

    :param id: machine unique identifier
    :param what: e.g. /data, /control
    :param type: the type of request for POST
    :param port:
    :return:
    """

    ip = devices_map[id]["ip"]

    url = "{ip}:{port}/{what}/{id}".format(ip=ip,port=port,what=what,id=id)
    if type is not None:
        return url + "/" + type
    return url

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
def devices():

    strs = subprocess.check_output(shlex.split('ip r l'))
    host_ip = strs.split(b'wlan0')[0].split()[-2]
    host_ip = host_ip.decode('utf-8').split('.')

    subnet_ip = ".".join(host_ip[0:3])

    logging.info("Scanning attached devices")
    urls_to_scan = ["http://%s.%i" % (subnet_ip,i)  for i in range(256)]
    pool = multiprocessing.Pool(256)
    devices_list = pool.map(scan_url, urls_to_scan)
    pool.terminate()

    global devices_map
    devices_map = {}
    for d in devices_list:
        if d is None:
            continue
        devices_map[d["machine_id"]] = d

    logging.info("%i devices found:" % len(devices_map))

    for k,v in devices_map.items():
        logging.info("%s\t@\t%s" % (k,v["ip"]))

    return devices_map

@app.get('/devices_list')
def get_devices_list():
    global devices_map
    return devices_map

@app.post('/devices_list')
def post_devices_list():
    # @Luis I don't get this, is is meant to update device status on request?
    # When is that used?  I presume it should be updated at every refresh right?
    global devices_map
    data = request.body.read()
    data = json.loads(data)
    device_id = data['device_id']
    status = data['status']
    devices_map[device_id]['status'] = status

#Get the information of one Sleep Monitor
@app.get('/device/<id>/data')
def device(id):
    try:
        url = format_post_get_url(id,"data")
        req = urllib2.Request(url=url)
        f = urllib2.urlopen(req)
        message = f.read()
        if message:
            data = json.loads(message)
            return data
    except Exception as e:
        return {'error':traceback.format_exc(e)}
        
@app.get('/device/<id>/controls/<type_of_req>')
def device(id, type_of_req):
    try:
        url = format_post_get_url(id,"controls", type=type_of_req)
        req = urllib2.Request(url=url)
        f = urllib2.urlopen(req,{})
        message = f.read()
        if message:
            data = json.loads(message)
            return data

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error':traceback.format_exc(e)}

@app.post('/device/<id>/controls/<type_of_req>')
def device(id, type_of_req):
    global acquisition

    try:
        data = request.body.read()
        url = format_post_get_url(id,"controls", type=type_of_req)
        req = urllib2.Request(url, data=data, headers={'Content-Type': 'application/json'})
        f = urllib2.urlopen(req)
        message = f.read()
        if not message:
            return

        data = json.loads(message)
        #start acquisition thread
        try:
            if type_of_req == 'start' and data['status'] == 'started':
                acquisition[id] = Acquisition(devices_map[id])
                acquisition[id].start()
            if type_of_req == 'stop' and data['status'] == 'stopped' and acquisition is not None:
                acquisition[id].stop()
                acquisition[id].join()
        except Exception as e:
            data['error'] = e
            logging.error(traceback.format_exc(e))
            return data

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error':traceback.format_exc(e)}

@app.get('/list/<type>')
def redirection_to_home(type):
    return redirect('/#/list/'+type)

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
        req = urllib2.Request(url=devices_map[id]['ip']+':9000/static/'+data["file_path"])

        f = urllib2.urlopen(req)
        result = {}
        for i, line in enumerate(f):
            result[i]=line

        return result

    except Exception as e:
        return {'error':traceback.format_exc(e)}


if __name__ == '__main__':

    global devices_map
    devices_map = {}
    devices_map = devices()

    acquisition = {}


    logging.getLogger().setLevel(logging.INFO)
    for k, device in devices_map.iteritems():
        if device['status'] == 'running':
            acquisition[k]= Acquisition(device)
            acquisition[k].start()
    try:
        #get the connected devices that are doing tracking and start acquisitions threads.
        # @luis TODO => I am not quite sure about debug here.
        run(app, host='0.0.0.0', port=8000, debug=debug)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.error(traceback.format_exc(e))

    finally:
        for a in acquisition.values():
            a.stop()
            a.join()


