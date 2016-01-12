__author__ = 'luis'

import logging
import traceback
from optparse import OptionParser
from bottle import *
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.helpers import get_machine_info, get_version
from ethoscope.web_utils.record import RecordVideo
from subprocess import call

api = Bottle()

json_data = {}
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

@api.post('/controls/<id>/<action>')
def controls(id, action):
    global control
    global record
    try:
        if id != machine_id:
            raise WrongMachineID

        if action == 'start':
            data = request.json
            json_data.update(data)
            control = ControlThread(machine_id=machine_id,
                    name=machine_name,
                    version=version,
                    ethoscope_dir=ETHOGRAM_DIR,
                    data=json_data)

            control.start()
            return info(id)

        elif action in ['stop', 'close', 'poweroff']:
            if control.info['status'] == 'running':
                logging.info("Stopping monitor")
                control.stop()
                control.join()
                logging.info("Monitor stopped")

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
            record = RecordVideo(data=data)
            record.start()
            control.info['status'] = 'recording'
            return info(id)

        elif action == 'stop_record':

            if record is not None:
                recording_file = record.stop()
                record.join()
                control.info['status'] = 'stopped'
                control.info['recording_file'] = recording_file
                return info(id)
            else:
                logging.warning("Can not stop video record. No video record started.")


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

    ETHOGRAM_DIR = option_dict["results_dir"]

    control = ControlThread(machine_id=machine_id,
                            name=machine_name,
                            version=version,
                            ethoscope_dir=ETHOGRAM_DIR,
                            data=json_data)

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
