__author__ = 'luis'

import logging

from bottle import *
from subprocess import call

from pysolovideo.web_utils.control_thread import ControlThread
from pysolovideo.web_utils.helpers import get_machine_id

api = Bottle()

@api.get('/id')
def name():
    return {"id" : machine_id, "type": "sm"}

@api.get('/controls/<id>/<action>')
def controls(id, action):
    global control
    
    if id == machine_id:
        if action == 'start':
            try:
                # Sync clocks with the node or master
                #data = request.json
                #t = data['time']
                # set time, given in milliseconds from javascript, used in seconds for date
                #set_time = call(['date', '-s', '@' + str(t)[:-3]])
                control = ControlThread(machine_id)
                control.start()
                return {'status': 'Started'}
            except Exception as e:
                return {'error':str(e)}
            #except:
            #    logging.error("Impossible to start")
            #    return {'status': 'Error'}

        if action == 'stop':
            try:
                control.stop()
                control.join()
                return {'status': 'Stopped'}
            except Exception as e:
                return {'error':str(e)}

    else:
        return "Error on machine ID"


@api.get('/data/<id>/<type_of_data>')
def data(id, type_of_data):
    if id == machine_id:
        if type_of_data == 'all':
            return {"last_frame": control.last_frame, "data_history": control.data_history}
        if type_of_data == 'last_frame':
            return control.last_frame
        if type_of_data == 'history':
            return control.data_history
    else:
        return "Error on machine ID"


if __name__ == '__main__':

    machine_id = get_machine_id()
    #create object
    control = None #ControlThread(machine_id)


    run(api, host='0.0.0.0', port=9000, debug=True)