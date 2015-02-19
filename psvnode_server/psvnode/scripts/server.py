from bottle import *
import shlex
import urllib2
import subprocess
import socket
import json
import multiprocessing
import logging
import traceback
from psvnode.utils.acquisition import Acquisition
from netifaces import interfaces, ifaddresses, AF_INET
import optparse

app = Bottle()
STATIC_DIR = "../../static"


def get_data_from_url(url, timeout=0.5, port=9000):
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

def get_data_from_id(id):
    url = format_post_get_url(id,"data")
    req = urllib2.Request(url=url)
    f = urllib2.urlopen(req)
    message = f.read()
    if message:
        data = json.loads(message)
        return data
    else:
        raise urllib2.URLError("No data at this url `%s`" % url)

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
def devices():
    subnet_ip = get_subnet_ip(SUBNET_DEVICE)
    logging.info("Scanning attached devices")
    urls_to_scan = ["http://%s.%i" % (subnet_ip,i)  for i in range(256)]
    pool = multiprocessing.Pool(256)
    devices_list = pool.map(get_data_from_url, urls_to_scan)
    pool.terminate()

    global devices_map
    devices_map = {}
    for d in devices_list:
        if d is None:
            continue
        print d
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
    #TODO just update here ;)
    data = request.body.read()
    data = json.loads(data)
    device_id = data['device_id']
    status = data['status']
    devices_map[device_id]['status'] = status

#Get the information of one Sleep Monitor
@app.get('/device/<id>/data')
def device(id):
    try:
        data = get_data_from_id(id)

        devices_map[id].update(data)
        return data

    except urllib2.URLError as e:
        del devices_map[id]
        return {'error':traceback.format_exc(e)}
    except Exception as e:
        return {'error':traceback.format_exc(e)}

# @LUIS do we use that ?
# FIXME
# @app.get('/device/<id>/controls/<type_of_req>')
# def device(id, type_of_req):
#     try:
#         url = format_post_get_url(id,"controls", type=type_of_req)
#         req = urllib2.Request(url=url)
#         f = urllib2.urlopen(req,{})
#         message = f.read()
#         if message:
#             data = json.loads(message)
#             devices_map[id].delete te(data)
#             print "updating device map for", id
#             return data
#
#     except Exception as e:
#         logging.error(traceback.format_exc(e))
#         return {'error':traceback.format_exc(e)}

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

        # Just updating the device map
        device_info = get_data_from_id(id)
        devices_map[id].update(device_info)
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
        SUBNET_DEVICE = b'enp3s0'
    else:
        SUBNET_DEVICE = b'wlan0'


    global devices_map
    devices_map = {}
    devices_map = devices()

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


