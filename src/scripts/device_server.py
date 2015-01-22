__author__ = 'luis'

from bottle import *
from pysolovideo.web_utils.control_thread import ControlThread
from pysolovideo.web_utils.helpers import get_machine_id


api = Bottle()
control = ControlThread()
machine_id = get_machine_id()


@api.get('/name')
def name():
    return machine_id

@api.post('/controls/<id>/<action>')
def controls(id, action):
    if id == machine_id:
        if action == 'start':
            control.start()
            return "threadstarted"
        if action == 'stop':
            control.stop()
            return "stopped"
    else:
        return "Error on machine ID"


@api.get('/data/<id>/<type_of_data>')
def data(id, type_of_data):
    if id == machine_id:
        if type_of_data == 'last_frame':
            return control.last_frame
        if type_of_data == 'history':
            return control.data_history
    else:
        return "Error on machine ID"