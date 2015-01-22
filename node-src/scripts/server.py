from bottle import *
app = Bottle()
import subprocess, shlex
import urllib2
import Queue


global devices_list


@app.get('/favicon.ico')
def get_favicon():
    return server_static('static/img/favicon.ico')

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="static")


@app.route('/')
def index():
    return static_file('index.html', root='static')

@app.get('/ipAddress')
def ipAddress():
    host = request.get_header('host')
    ip = request.environ.get('REMOTE_ADDR').split('.')
    strs = subprocess.check_output(shlex.split('ip r l'))
    gateway = strs.split(b'default via')[-1].split()[0]
    gateway = gateway.decode("utf-8").split('.')
    Host_ip = strs.split(b'src')[-1].split()[0].split(b'.')
    print (gateway, ip)
    if str(gateway[0]) == ip[0] and str(gateway[1]) == ip[1] and str(gateway[2]) == ip[2]:
        sameNet = "True"
    else:
        sameNet = "False"
    return sameNet

#################################
## API For comunicate with SM/SD
#################################

@app.get('/devices')
def devices():
    global devices_list
    devices_list = {}
    strs = subprocess.check_output(shlex.split('ip r l'))
    host_ip = strs.split(b'src')[-1].split()[0]
    host_ip = host_ip.decode('utf-8').split('.')
    #devices = list(ipaddress.ip_network(host_ip[0]+'.'
                                        # +host_ip[1]+'.'
                                        #+host_ip[2]+'.'
                                        #+'0/24').hosts())
    thread =[]

    queue = Queue.Queue()
    for i in range(0,256):
            url = "http://"+host_ip[0]+'.'+host_ip[1]+'.' \
            +host_ip[2]+'.'+str(i)
            t=Discover(0.2, url, queue)
            thread.append(t)
            thread[i].start()
            print("thread-{} started".format(i))

    for i in range(0,256):
            thread[i].join()
            print("thread-{} stoped".format(i))

    print devices_list
    #TODO save devices to a json file
    return devices_list

##Get the information of one Sleep Monitor
@app.get('/sm/<id>')
def sm(id):
    pass

@app.get('/sm/<id>')
def sd(id):
    pass



#################
## HELP METHODS
#################
class Discover(threading.Thread):
    def __init__(self, scanInterval, url, queue):
        threading.Thread.__init__(self)
        self.url = url
        self.scanInterval = scanInterval
        self.queue = queue

    def run(self):
        global devices_list
        try:
            req = urllib2.Request(url=self.url+':8088/pidiscover')
            f = urllib2.urlopen(req,timeout = self.scanInterval)
            message = f.read()
            if (message):
                message = message.decode("utf-8")
                data = {'name':message,'ip':self.url}
                devices_list[message]=data
            else:
                pass
        except:
            pass



if __name__ == '__main__':
    run(app, host='0.0.0.0', port=8000, debug=True)




