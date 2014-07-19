from bottle import *

import db
from subprocess import Popen, PIPE, call
from os import path, kill
from signal import SIGTERM
import json

basedir=path.dirname(os.path.realpath(__file__))

app = Bottle()

outputfile = path.join(basedir,"output.txt")


class RoiData():
    def __init__(self):
        name = ""
        rois = []
        trackingType = 0
        
@get('/favicon.ico')
def get_favicon():
    return server_static(path.join(basedir,'static/img/favicon.ico'))

        
@app.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root=path.join(basedir,"static"))

@app.route('/')
def index():
    mid= checkMachineId()
    _,status = checkPid()
    df = subprocess.Popen(["df", "./"], stdout=subprocess.PIPE)
    output = df.communicate()[0]
    device, size, used, available, percent, mountpoint = \
                                                   output.split(b"\n")[1].split()
    return template(path.join(basedir+"/views","index.tpl"), machineId=mid, status=status, freeSpace = percent)

@app.route('/websocket')
def handle_websocket():
    #try:
    data = readData()
    return(data)
    #except:
        #print("error")
       
@app.route('/pidiscover')
def pidiscover():
    name = checkMachineId()
    return(name)

@app.post('/ROI')
def new_roi():
    roiData = request.json
    db.save(roiData)
    #load saved rois and then add the new one
#    try:
#        roiList = db.load()
#        roiList[len(roiList)]=roiData
#        db.save(roiList)
#    except:
#        """file does not exits yet"""
#        roiList = [0]
#        roiList[0]=roiData
#        db.save(roiData)

@app.get('/ROI')
def list_roi():
    response.content_type = 'application/json'
    roisSaved = db.load()
    dataToSend = {}
    dataToSend['name']="Rois Saved in SM"
    dataToSend['data'] = roisSaved
    d = json.dumps(dataToSend)
    return (d)

@app.post('/changeMachineId')
def changeMachineId():
    try:
        name = request.json
        changeMId(name['newName'])
        return(name['newName'])
    except:
        print ("no data")
    #redirect("/")

    
@app.put('/started')
def starStop():
    try:
        data = request.json
        t = data['time']
        #set time, given in miliseconds from javascript, used in seconds for date
        setTime = call(['date', '-s', '@'+str(t)[:-3]])
    except:
        print ("no data")
    pid, isAlreadyRunning = checkPid()
    
    if isAlreadyRunning:
        kill(pid,SIGTERM)
    else:
        db.writeMask(data)
        #f = open('mask.msk','wb')
        #pickle.dump(data['roi'], f)
        #f.close()
        pySolo = Popen(["python2",path.join(basedir,"pvg_standalone.py"), 
                        "-c", path.join(basedir,"pysolo_video.cfg"),
                        "-i","0",
                        "-k", "mask.msk",
                        "-t", str(data['trackingType']),
                        "-o", outputfile,
                        "--showmask",#useful?
                        "--trackonly"])
        
        #pySolo = Popen(["python2", "pvg.py"])# -c pysolo_video.cfg -i 0 -k mask.msk -t 0 -o output.txt", shell=True)
        
@app.get('/state')
def state():
    _, isRunning = checkPid()
    return str(isRunning)

@app.get('/refresh')
def refresh():
    pid, isAlreadyRunning = checkPid()
    if isAlreadyRunning:
        #add a call to a function to update snapshot when trackingType
        #for now, do nothing
        pass 
    else:
        pySolo = call(["python2",path.join(basedir,"pvg_standalone.py"), 
                        "-c", path.join(basedir,"pysolo_video.cfg"),
                        "-i","0",
                        "--snapshot",])
    redirect("/")
    #_,status = checkPid()
    #return template('index', machineId=mid, status=status)


@app.route('/downloadData/<machineID>')
def downloadData(machineID):
    pid, isAlreadyRunning = checkPid()
    mid = checkMachineId()
    if mid == machineID:
        #TODO:Add a "last downloaded"
        return static_file(outputfile, root='/')
    else:
        redirect("/")
    
    
@app.delete('/deleteData/<machineID>')
def deleteData(machineID):
    pid, isAlreadyRunning = checkPid()
    mid = checkMachineId()
    if mid == machineID:
        if isAlreadyRunning:
            #save the last 10 lines
            f = open(outputfile, 'rb')
            f.seek(-1000,2)
            data = f.readlines()
            f.close()
            f = open(outputfile, 'w')
            for line in data[1:]:
                l = line.decode('utf-8')
                f.write(l)
        else:
            #erease everything.
            print(outputfile)
            f=open(outputfile, 'w')
            f.close()
    redirect("/")
     

@app.get('/visualizeData')
def visualizeData():
    pid, isAlreadyRunning = checkPid()   
    return static_file(outputfile, root='')

@app.put('/poweroff/<machineID>')
def poweroff(machineID):
    pid, isAlreadyRunning = checkPid()
    mid = checkMachineId()
    if mid == machineID:
        print("powering off")
        if isAlreadyRunning:
            startStop()
        off = call("poweroff")
        
"""helpers methods."""

def checkPid():
    proc = Popen(["pgrep", "-f", 
                  "python2 "+path.join(basedir,"pvg_standalone.py")]
                 , stdout=PIPE)
    try:
        pid=int(proc.stdout.readline())
        started=True
    except:
        started=False
        pid = None
    proc.stdout.close()
    return pid, started

def changeMId(name):
    f = open(path.join(basedir,'machineId'),'w')
    piId = f.write(name)
    f.close()
    return True

def checkMachineId():
    f = open(path.join(basedir,'machineId'),'r')
    piId = f.read().rstrip()
    f.close()
    return piId
 
def readData():
    f = open(outputfile,'rb')
    try:
        f.seek(-1000,2)
        lines = f.readlines()
        line = lines[-1].decode('utf8').split('\t')
        jsonData = json.dumps(line)
    except:
        print("no data in outpufile")
        
        pass
    f.close()

    return jsonData
    
"""The main program"""    
roiList={}

run(app,host='0.0.0.0', port=8088, debug=True)

#from gevent.pywsgi import WSGIServer
#from geventwebsocket.handler import WebSocketHandler
#server = WSGIServer(("0.0.0.0", 8088), app,
#                    handler_class=WebSocketHandler)
#server.serve_forever()
