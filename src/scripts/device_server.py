__author__ = 'luis'

import logging

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


#fixme all this info should be in control.info
@api.get('/id')
def name():
    global control
    try:
        return control.info
    except Exception as e:
        return {'error':e}

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
                    # FIXME This is needed on PI
                    #set_time = call(['date', '-s', '@' + str(t)])
                    date = datetime.fromtimestamp(t)
                    # date_time = date.isoformat()

                    control = ControlThread(machine_id=machine_id, name='SM15-001', video_file=INPUT_VIDEO,
                            psv_dir=PSV_DIR, draw_results = DRAW_RESULTS, max_duration=DURATION)
                    control.start()
                    return {'status': 'started'}

                elif action == 'stop' or action == 'poweroff':
                    control.stop()
                    control.join()
                    logging.info("Stopping monitor")

                    if action == 'poweroff':
                        logging.info("Stopping monitor due to poweroff request")
                        logging.info("Powering off Device.")
                        # fixme, this is non blocking, is it ? maybe we should do something else
                        call('poweroff')
                    return {'status': 'stopped'}


            except Exception as e:
                return {'error': "Error setting up control thread"+str(e)}

    else:
        return {'error': "Error on machine ID"}


@api.get('/data/<id>')
def data(id):
    if id == machine_id:
        return control.info
    else:
        return {'error': "Error on machine ID"}


if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-d", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-p", "--port", dest="port", default=9000,help="port")
    (options, args) = parser.parse_args()
    option_dict = vars(options)
    debug = option_dict["debug"]
    port = option_dict["port"]

    machine_id = get_machine_id()

    if debug:
        import getpass
        DURATION = 60*60 * 100
        if getpass.getuser() == "quentin":
            INPUT_VIDEO = '/data/pysolo_video_samples/sleep_monitor_100h_no_heat.avi'
        elif getpass.getuser() == "asterix":
            INPUT_VIDEO = '/data1/sleepMonitor_5days.avi'
        else:
            raise Exception("where is your debugging video?")
        DRAW_RESULTS = True

    else:
        INPUT_VIDEO = None
        DURATION = None
        DRAW_RESULTS =False
        # fixme => we should have mounted /dev/sda/ onto a custom location instead @luis @ quentin


    PSV_DIR = "/psv_data"

    # fixme => the name should be hardcoded in a encrypted file? file.
    control = ControlThread(machine_id=machine_id, name='SM15-001', video_file=INPUT_VIDEO,
                            psv_dir=PSV_DIR, draw_results = DRAW_RESULTS, max_duration=DURATION)

    try:
        run(api, host='0.0.0.0', port=port, debug=debug)
    finally:
        if control is not None:
            control.stop()
            control.join()



