import db
<<<<<<< HEAD
import zipfile
import glob
from subprocess import call
=======
>>>>>>> 2c18142d99048230a47ad507b4237c753bbd75ed
from bottle import *

from os import path
import json
<<<<<<< HEAD
import zipfile
import glob
=======
>>>>>>> 2c18142d99048230a47ad507b4237c753bbd75ed

os.sys.path.append("..")
from pvg_headless import pvg_cli

app = Bottle()

class RoiData():
    def __init__(self):
        name = ""
        rois = []
        trackingType = 0
        
<<<<<<< HEAD
@app.get('/favicon.ico')
=======
@get('/favicon.ico')
>>>>>>> 2c18142d99048230a47ad507b4237c753bbd75ed
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
    fs = str(round(st.f_bfree * 100.0 / st.f_blocks)) + "%"
    
    return template(path.join(basedir+"/views","index.tpl"), machineId=mid, status=status, freeSpace = fs)

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
<<<<<<< HEAD
        print ("tracking type", data['trackingType'])
=======
        print "tracking type", data['trackingType']
>>>>>>> 2c18142d99048230a47ad507b4237c753bbd75ed
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
<<<<<<< HEAD
		
@app.post('/update')
def do_update():
    
    if isTracking():
        startStop()
    #close sockets
    pysolo_headless.mon.cam.stopNetworkStream()
    
    data = request.files.data
    
    if data and data.file:
        filename = data.filename
        with open(filename,'wb') as open_file:
            open_file.write(data.file.read())
        with zipfile.ZipFile(data.filename, "r") as z:
            z.extractall()
        for hgx in glob.glob(data.filename):
            os.remove(hgx)
    
    #change this for a service restart:
    return call(["python3 restartScript.py"],shell=True)

=======
        
>>>>>>> 2c18142d99048230a47ad507b4237c753bbd75ed
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
    pysolo_headless = pvg_cli(1000, resolution=(800,600))

    run(app,host='0.0.0.0', port=8088, debug=True)




