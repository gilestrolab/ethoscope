__author__ = 'luis'

import logging
import traceback
from optparse import OptionParser
from bottle import *
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.helpers import get_machine_info, get_version
from ethoscope.web_utils.record import ControlThreadVideoRecording
from subprocess import call

api = Bottle()

tracking_json_data = {}
recording_json_data = {}
ETHOGRAM_DIR = None


class WrongMachineID(Exception):
    pass

@api.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/")

@api.route('/download/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/", download=filepath)


@api.get('/id')
def name():
    try:
        return {"id": control.info["id"]}
    except Exception as e:
        return {'error':traceback.format_exc(e)}


@api.post('/rm_static_file/<id>/<file>')
def rm_static_file(id, file):
    global control
    global record

    try:
        if id != machine_id:
            raise WrongMachineID
        #fixme here, we should check that files lives in static dir!
        os.remove(file)


    except Exception as e:
        return {'error':traceback.format_exc(e)}



@api.post('/controls/<id>/<action>')
def controls(id, action):
    global control
    global record
    print id, action
    try:
        if id != machine_id:
            raise WrongMachineID

        if action == 'start':
            data = request.json
            tracking_json_data.update(data)
            control = None
            control = ControlThread(machine_id=machine_id,
                    name=machine_name,
                    version=version,
                    ethoscope_dir=ETHOGRAM_DIR,
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
                    ethoscope_dir=ETHOGRAM_DIR,
                    data=recording_json_data)

            control.start()
            return info(id)
        else:
            raise Exception("No such action: %s" % action)

    except Exception as e:
        return {'error':traceback.format_exc(e)}



@api.get('/data/<id>')
def info(id):
    try:
        if machine_id != id:
            raise WrongMachineID
        return control.info
    except Exception as e:
        return {'error': "Error on machine ID"}

@api.get('/user_options/<id>')
def user_options(id):
    try:
        if machine_id != id:
            raise WrongMachineID
        return {
            "tracking":ControlThread.user_options(),
            "recording":ControlThreadVideoRecording.user_options()}

    except Exception as e:
        return {'error': "Error on machine ID"}



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

    ETHOGRAM_DIR = "/ethoscope_data/results"
    MACHINE_ID_FILE = '/etc/machine-id'
    MACHINE_NAME_FILE = '/etc/machine-name'

    parser = OptionParser()
    parser.add_option("-r", "--run", dest="run", default=False, help="Runs tracking directly", action="store_true")
    parser.add_option("-s", "--stop-after-run", dest="stop_after_run", default=False, help="When -r, stops immediately after. otherwise, server waits", action="store_true")
    parser.add_option("-v", "--record-video", dest="record_video", default=False, help="Records video instead of tracking", action="store_true")
    parser.add_option("-j", "--json", dest="json", default=None, help="A JSON config file")
    parser.add_option("-p", "--port", dest="port", default=9000,help="port")
    parser.add_option("-e", "--results-dir", dest="results_dir", default=ETHOGRAM_DIR,help="Where temporary result files are stored")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")


    (options, args) = parser.parse_args()
    option_dict = vars(options)
    port = option_dict["port"]

    machine_id = get_machine_info(MACHINE_ID_FILE)
    machine_name = get_machine_info(MACHINE_NAME_FILE)

    version = get_version()


    if option_dict["json"]:
        import json
        with open(option_dict["json"]) as f:
            json_data= json.loads(f.read())
    else:
        data = None
        json_data = {}

    ETHOGRAM_DIR = option_dict["results_dir"]

    if option_dict["record_video"]:
        recording_json_data = json_data
        control = ControlThreadVideoRecording(  machine_id=machine_id,
                                                name=machine_name,
                                                version=version,
                                                ethoscope_dir=ETHOGRAM_DIR,
                                                data=recording_json_data)

    else:
        tracking_json_data = json_data
        control = ControlThread(machine_id=machine_id,
                            name=machine_name,
                            version=version,
                            ethoscope_dir=ETHOGRAM_DIR,
                            data=tracking_json_data)


    if option_dict["debug"]:
        logging.basicConfig(level=logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    if option_dict["stop_after_run"]:
         control.set_evanescent(True) # kill program after first run

    if option_dict["run"]:
        control.start()

    try:
        run(api, host='0.0.0.0', port=port, server='cherrypy',debug=option_dict["debug"])
    except Exception as e:
        logging.error(e)
        close(1)
    finally:
        close()


#
