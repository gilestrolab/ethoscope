__author__ = 'luis'

import logging
import gzip
import datetime
from optparse import OptionParser
from bottle import *
from pysolovideo.web_utils.control_thread import ControlThread
from pysolovideo.web_utils.helpers import get_machine_id
from subprocess import call

api = Bottle()

@api.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/")


@api.get('/id')
def name():
    status = "stopped"
    if control is not None:
        status = "started"

    return {"id": machine_id, "type": "sm", "name": "SM15-001", "status": status}

@api.post('/controls/<id>/<action>')
def controls(id, action):
    global control

    if id == machine_id:
            try:
                if action == 'start':

                    # Sync clocks with the node or master
                    data = request.json
                    t = float(data['time'])
                    #set time, given in seconds from javascript, used in seconds for date
                    #set_time = call(['date', '-s', '@' + str(t)[:-3]])
                    date = datetime.fromtimestamp(t)
                    date_time = date.isoformat()
                    control = ControlThread(machine_id=machine_id, date_time=date_time, video_file=INPUT_VIDEO, psv_dir=PSV_DIR, draw_results = DRAW_RESULTS, max_duration=DURATION)

                    control.start()
                    logging.info("Starting monitor")
                    return {'status': 'started'}
                if action == 'stop':
                    control.stop()
                    control.join()
                    control = None
                    logging.info("Stopping monitor")
                    return {'status': 'stopped'}

            except Exception as e:
                print e
                try:
                    return control.format_psv_error(e)
                except:
                    return {type(e).__name__:str(e)}
    else:
        return "Error on machine ID"


@api.get('/data/<id>/<type_of_data>')
def data(id, type_of_data):
    if id == machine_id:
        try:
            if control is not None:
                if type_of_data == 'all':
                    return {"status": "started", "last_drawn_img": control.last_drawn_img, "last_positions": control.last_positions}
                if type_of_data == 'last_drawn_img':
                    return {"last_drawn_img": control.last_drawn_img}
                if type_of_data == 'last_positions':
                    return {"last_positions": control.last_positions}
                if type_of_data == 'log_file_path':
                    return {"log_file_path": control.log_file_path}
                if type_of_data == 'data_history':
                    return {"data_history": control.data_history}
                if type_of_data == 'result_files':
                    return {"result_files": control.result_files()}
            else:
                return {"status": "stopped"}

        except Exception as e:
            return control.format_psv_error(e)
    else:
        return "Error on machine ID"


if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-d", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    (options, args) = parser.parse_args()
    option_dict = vars(options)
    debug = option_dict["debug"]

    machine_id = get_machine_id()




    if debug:
        import getpass
        DURATION = 60*60*4
        if getpass.getuser() == "quentin":
            INPUT_VIDEO = '/data/pysolo_video_samples/sleepMonitor_5days.avi'
        elif getpass.getuser() == "asterix":
            INPUT_VIDEO = '/data1/sleepMonitor_5days.avi'
        DRAW_RESULTS = True
        PSV_DIR = '/tmp/psv'
    else:
        INPUT_VIDEO = None
        DURATION = None
        DRAW_RESULTS =False
        # fixme => we should have mounted /dev/sda/ onto a costum location instead @luis @ quentin
        PSV_DIR = '/tmp/psv'



    control = None

    try:
        # @luis TODO => I am not quite sure about debug here.
        run(api, host='0.0.0.0', port=9000, debug=debug)
    finally:
        control.stop()
        control.join()


