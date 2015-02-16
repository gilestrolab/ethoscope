from bottle import *
app = Bottle()
import shlex
import urllib2

import subprocess,json
import threading

from psvnode.utils.acquisition import Acquisition

devices_list ={}


STATIC_DIR = "../../static"

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
    global devices_list
    devices_list = {}
    strs = subprocess.check_output(shlex.split('ip r l'))
    host_ip = strs.split(b'src')[-1].split()[0]
    host_ip = host_ip.decode('utf-8').split('.')
    #host_ip = ['129','31','135','0']
    thread =[]

    for i in range(0,256):
            ip = "http://"+host_ip[0]+'.'+host_ip[1]+'.' \
            +host_ip[2]+'.'+str(i)
            t=Discover(0.5, ip)
            thread.append(t)
            thread[i].start()

    for i in range(0,256):
            thread[i].join()

    return devices_list

@app.get('/devices_list')
def get_devices_list():
    global devices_list
    return devices_list

@app.post('/devices_list')
def post_devices_list():
    global devices_list
    data = request.body.read()
    data = json.loads(data)
    device_id = data['device_id']
    status = data['status']
    devices_list[device_id]['status'] = status


#Get the information of one Sleep Monitor
@app.get('/device/<id>/data')
def device(id):
    try:
        url = devices_list[id]['ip']
        req = urllib2.Request(url=devices_list[id]['ip']+':9000/data/'+id)
        f = urllib2.urlopen(req)
        message = f.read()
        if message:
            data = json.loads(message)
            return data

    except Exception as e:
        return {'error':str(e)}
        
@app.get('/device/<id>/controls/<type_of_req>')
def device(id, type_of_req):
    try:
        url = devices_list[id]['ip']
        req = urllib2.Request(url=devices_list[id]['ip']+':9000/controls/'+id+'/'+type_of_req)
        f = urllib2.urlopen(req,{})
        message = f.read()
        if message:
            data = json.loads(message)
            return data

    except Exception as e:
        return {'error':str(e)}

@app.post('/device/<id>/controls/<type_of_req>')
def device(id, type_of_req):
    global acquisition

    try:
        data = request.body.read()
        url = devices_list[id]['ip']
        req = urllib2.Request(url=devices_list[id]['ip']+':9000/controls/'+id+'/'+type_of_req,
                              data=data,
                              headers={'Content-Type': 'application/json'})
        f = urllib2.urlopen(req)
        message = f.read()
        if message:
            data = json.loads(message)
            #start acquisition thread
            try:
                if type_of_req == 'start' and data['status'] == 'started':
                    acquisition[id] = Acquisition(devices_list[id]['ip'],id)
                    acquisition[id].start()
                if type_of_req == 'stop' and data['status'] == 'stopped' and acquisition is not None:
                    acquisition[id].stop()
                    acquisition[id].join()
            except Exception as e:
                data['error'] = e
                print e

            return data

    except Exception as e:
        return {'error':str(e)}

@app.get('/list/<type>')
def redirection_to_home(type):
    return redirect('/#/list/'+type)

@app.get('/sm/<id>')
def redirection_to_home(id):
    return redirect('/#/sm/'+id)

@app.get('/device/<id>/ip')
def redirection_to_home(id):
    if len(devices_list) > 0:
        return devices_list[id]['ip']
    else:
        return "no devices"

@app.post('/device/<id>/log')
def get_log(id):
    try:
        data = request.body.read()
        data = json.loads(data)
        file_path = data["file_path"]
        print(file_path)
        url = devices_list[id]['ip']
        req = urllib2.Request(url=devices_list[id]['ip']+':9000/static/'+file_path)
        f = urllib2.urlopen(req)
        result = {}
        i=0
        for line in f:
            result[i]=line
            i=i+1
        return result

    except Exception as e:
        return {'error':str(e)}

#################
# HELP METHODS
#################
class Discover(threading.Thread):
    def __init__(self, scanInterval, url):
        threading.Thread.__init__(self)
        self.url = url
        self.scanInterval = scanInterval

    def run(self):
        global devices_list
        try:
            req = urllib2.Request(url=self.url+':9000/id')
            f = urllib2.urlopen(req,timeout = self.scanInterval)
            message = f.read()
            if message:
                data = json.loads(message)
                data['ip'] = self.url
                devices_list[data['machine_id']]=data
        except Exception as e:
            print e



if __name__ == '__main__':

    acquisition = {}
    devices_list = devices()
    for k,device in devices_list.iteritems():
        if device['status'] == 'running':
            acquisition[k]= Acquisition(device['ip'],k)
            acquisition[k].start()
    try:
        #get the connected devices that are doing tracking and start acquisitions threads.

        # @luis TODO => I am not quite sure about debug here.
        run(app, host='0.0.0.0', port=8000, debug=debug)

    except Exception as e:
        print e
    finally:
        for a in acquisition.values():
            a.stop()
            a.join()


