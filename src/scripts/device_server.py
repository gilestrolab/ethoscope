__author__ = 'luis'

import logging
import traceback
from optparse import OptionParser
from bottle import *
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.helpers import get_machine_info, get_version, file_in_dir_r
from ethoscope.web_utils.record import ControlThreadVideoRecording
from subprocess import call
import json

api = Bottle()

tracking_json_data = {}
recording_json_data = {}
ETHOSCOPE_DIR = None


class WrongMachineID(Exception):
    pass


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

@api.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/")

@api.route('/download/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/", download=filepath)


@api.get('/id')
@error_decorator
def name():
    return {"id": control.info["id"]}



@api.post('/rm_static_file/<id>')
@error_decorator
def rm_static_file(id):
    global control
    global record

    data = request.body.read()
    data = json.loads(data)
    file_to_del = data["file"]
    if id != machine_id:
        raise WrongMachineID

    if file_in_dir_r(file_to_del, ETHOSCOPE_DIR ):
        os.remove(file_to_del)
    else:
        msg = "Could not delete file %s. It is not allowed to remove files outside of %s" % (file_to_del, ETHOSCOPE_DIR)
        logging.error(msg)
        raise Exception(msg)
    return data



@api.post('/controls/<id>/<action>')
@error_decorator
def controls(id, action):
    global control
    global record
    if id != machine_id:
        raise WrongMachineID

    if action == 'start':
        data = request.json
        tracking_json_data.update(data)
        control = None
        control = ControlThread(machine_id=machine_id,
                                name=machine_name,
                                version=version,
                                ethoscope_dir=ETHOSCOPE_DIR,
                                data=tracking_json_data)

        control.start()
        return info(id)

    elif action in ['stop', 'close', 'poweroff']:
        if control.info['status'] == 'running' or control.info['status'] == "recording" :
            # logging.info("Stopping monitor")
            logging.warning("Stopping monitor")
            control.stop()
            logging.warning("Joining monitor")
            control.join()
            logging.warning("Monitor joined")
            logging.warning("Monitor stopped")
            # logging.info("Monitor stopped")

        if action == 'close':
            close()

        if action == 'poweroff':
            logging.info("Stopping monitor due to poweroff request")
            logging.info("Powering off Device.")
            call('poweroff')

        return info(id)

    elif action == 'start_record':
        data = request.json
        #json_data.update(data)
        logging.warning("Recording video, data is %s" % str(data))
        data = request.json
        recording_json_data.update(data)
        control = None
        control = ControlThreadVideoRecording(machine_id=machine_id,
                                              name=machine_name,
                                              version=version,
                                              ethoscope_dir=ETHOSCOPE_DIR,
                                              data=recording_json_data)

        control.start()
        return info(id)
    else:
        raise Exception("No such action: %s" % action)


@api.get('/data/<id>')
@error_decorator
def info(id):

    if machine_id != id:
        raise WrongMachineID
    info = control.info
    info["current_timestamp"] = time.time()
    return info

@api.get('/user_options/<id>')
@error_decorator
def user_options(id):
    if machine_id != id:
        raise WrongMachineID
    return {
        "tracking":ControlThread.user_options(),
        "recording":ControlThreadVideoRecording.user_options()}

def close(exit_status=0):
    global control
    if control is not None and control.is_alive():
        control.stop()
        control.join()
        control=None
    else:
        control = None
    os._exit(exit_status)

if __name__ == '__main__':

    ETHOSCOPE_DIR = "/ethoscope_data/results"
    MACHINE_ID_FILE = '/etc/machine-id'
    MACHINE_NAME_FILE = '/etc/machine-name'

    parser = OptionParser()
    parser.add_option("-r", "--run", dest="run", default=False, help="Runs tracking directly", action="store_true")
    parser.add_option("-s", "--stop-after-run", dest="stop_after_run", default=False, help="When -r, stops immediately after. otherwise, server waits", action="store_true")
    parser.add_option("-v", "--record-video", dest="record_video", default=False, help="Records video instead of tracking", action="store_true")
    parser.add_option("-j", "--json", dest="json", default=None, help="A JSON config file")
    parser.add_option("-p", "--port", dest="port", default=9000,help="port")
    parser.add_option("-e", "--results-dir", dest="results_dir", default=ETHOSCOPE_DIR, help="Where temporary result files are stored")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")


    (options, args) = parser.parse_args()
    option_dict = vars(options)
    port = option_dict["port"]

    machine_id = get_machine_info(MACHINE_ID_FILE)
    machine_name = get_machine_info(MACHINE_NAME_FILE)

    version = get_version()


    if option_dict["json"]:
        with open(option_dict["json"]) as f:
            json_data= json.loads(f.read())
    else:
        data = None
        json_data = {}

    ETHOSCOPE_DIR = option_dict["results_dir"]

    if option_dict["record_video"]:
        recording_json_data = json_data
        control = ControlThreadVideoRecording(machine_id=machine_id,
                                              name=machine_name,
                                              version=version,
                                              ethoscope_dir=ETHOSCOPE_DIR,
                                              data=recording_json_data)

    else:
        tracking_json_data = json_data
        control = ControlThread(machine_id=machine_id,
                                name=machine_name,
                                version=version,
                                ethoscope_dir=ETHOSCOPE_DIR,
                                data=tracking_json_data)


    if option_dict["debug"]:
        logging.basicConfig(level=logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    if option_dict["stop_after_run"]:
         control.set_evanescent(True) # kill program after first run

    if option_dict["run"] or control.was_interrupted:
        control.start()

    try:
        run(api, host='0.0.0.0', port=port, server='cherrypy',debug=option_dict["debug"])
    except Exception as e:
        logging.error(e)
        close(1)
    finally:
        close()


#
