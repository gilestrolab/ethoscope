import db
from bottle import *

from os import path
import json

os.sys.path.append("..")
from pvg_headless import pvg_cli

app = Bottle()

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
    status = isTracking()
    
    st = os.statvfs("./")
    freespace = round(st.f_bfree * 1.0 / st.f_blocks)
    
    return template(path.join(basedir+"/views","index.tpl"), machineId=mid, status=status, freeSpace = freespace)

@app.route('/websocket')
def handle_websocket():
    data = readData()
    return(data)

       
@app.route('/pidiscover')
def pidiscover():
    name = checkMachineId()
    return(name)

@app.post('/ROI')
def new_roi():
    roiData = request.json
    db.save(roiData)

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
    
    global pysolo_headless
    
    try:
        data = request.json
        t = data['time']
        #set time, given in miliseconds from javascript, used in seconds for date
        setTime = call(['date', '-s', '@'+str(t)[:-3]])
    except:
        print ("no data")
        
    
    if isTracking():
        pysolo_headless.stopTracking()
        
    else:
        db.writeMask(data)
        
        #start a python thread and begins tracking
        print "tracking type", data['trackingType']
        pysolo_headless.setTracking(track_type=data['trackingType'], mask_file="mask.msk", output_file=outputfile)
        pysolo_headless.startTracking()
        
@app.get('/state')
def state():
    return str(isTracking())

@app.get('/refresh')
def refresh():
    pysolo_headless.saveSnapshot("static/img/0.jpg")
    redirect("/")


@app.route('/downloadData/<machineID>')
def downloadData(machineID):
    
    if machineID == checkMachineId():
        #TODO:Add a "last downloaded"
        return static_file(outputfile, root='/')
    else:
        redirect("/")
    
    
@app.delete('/deleteData/<machineID>')
def deleteData(machineID):

    if machineID == checkMachineId():
        if isTracking():
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
    return static_file(outputfile, root='')

@app.put('/poweroff/<machineID>')
def poweroff(machineID):
    
    if machineID == checkMachineId():
        print("powering off")
        if isTracking():
            startStop()
        off = call("poweroff")
        
"""helpers methods."""

def isTracking():
    if pysolo_headless:
        return pysolo_headless.isRunning()
    else:
        return False

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
        jsonData = None
        
    f.close()

    return jsonData


if __name__ == '__main__':
    

    basedir=path.dirname(os.path.realpath(__file__))
    outputfile = path.join(basedir,"output.txt")

    #Start the acquisition thread
    pysolo_headless = pvg_cli(1000, resolution=(640,480))

    run(app,host='0.0.0.0', port=8088, debug=True)




