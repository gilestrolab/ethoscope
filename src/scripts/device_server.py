__author__ = 'luis'

import logging
import datetime
from optparse import OptionParser
from bottle import *
from ethoscope.web_utils.control_thread import ControlThread
from ethoscope.web_utils.helpers import get_machine_info, get_version
from ethoscope.web_utils.record import RecordVideo
from subprocess import call

api = Bottle()



VIDEO_FILE = None
ETHOGRAM_DIR = None
DRAW_RESULTS = None
VIDEO_OUT = None
DURATION = None


@api.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/")

@api.route('/download/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/", download=filepath)


# fixme all this info should be in control.info
@api.get('/id')
def name():
    global control
    try:
        return {"id": control.info["id"]}

    except Exception as e:
        return {'error':e}

@api.post('/controls/<id>/<action>')
def controls(id, action):
    global control
    global record
    if id == machine_id:
            try:
                if action == 'start':

                    # getting the requested type of tracking
                    data = request.json
                    #TODO clean this, no needed now, node provices NTP service
                    #t = float(data['time'])
                    #set time, given in seconds from javascript, used in seconds for date
                    # FIXME This is needed on PI
                    #set_time = call(['date', '-s', '@' + str(t)])
                    #date = datetime.fromtimestamp(t)
                    # date_time = date.isoformat()

                    control = ControlThread(machine_id=machine_id, name=machine_name, version=version, video_file=VIDEO_FILE,
                            ethoscope_dir=ETHOGRAM_DIR, draw_results = DRAW_RESULTS, max_duration=DURATION, data=data)
                    control.start()
                    return info(id)

                elif action == 'stop' or action == 'poweroff':
                    if control.info['status'] == 'running':
                        control.stop()
                        control.join()
                        logging.info("Stopping monitor")

                    if action == 'poweroff':
                        logging.info("Stopping monitor due to poweroff request")
                        logging.info("Powering off Device.")
                        # fixme, this is non blocking, is it ? maybe we should do something else
                        call('poweroff')
                    return info(id)

                elif action == 'start_record':
                    try:
                        record = RecordVideo()
                        record.start()
                        control.info['status'] = 'recording'
                        return info(id)
                    except Exception as e:
                        return {"error":e}
                elif action == 'stop_record':
                    try:
                        if record is not None:
                            recording_file = record.stop()
                            record.join()
                            control.info['status'] = 'stopped'
                            control.info['recording_file'] = recording_file
                            return info(id)
                        else:
                            logging.info("Can not stop video record. No video record started.")
                    except Exception as e:
                        logging.error("Exception on stopping record", e)

            except Exception as e:
                return {'error': "Error setting up control thread"+str(e)}

    else:
        return {'error': "Error on machine ID"}


@api.get('/data/<id>')
def info(id):
    if id == machine_id:
        return control.info
    else:
        return {'error': "Error on machine ID"}

@api.post('/update/<id>')
def update_system(id):
    if id == machine_id and control.info['status'] == 'stopped':
        try:
            device_update = subprocess.Popen(['git', 'pull'],
                                             cwd=GIT_WORKING_DIR,
                                             stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE)
            stdout, stderr = device_update.communicate()
            if stderr != '':
                logging.error("Error on update:"+stderr)
            if stdout != '':
                logging.info("Update result:"+stdout)
            logging.info("Restarting script now. Systemd should restart script")
            close()

        except Exception as e:
            return {'error':e, 'updated':False}
    else:
        return {'error': 'Error on machine ID or not Stopped'}


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
    GIT_WORKING_DIR = '/home/ethoscope/ethoscope-git'

    MACHINE_ID_FILE = '/etc/machine-id'
    MACHINE_NAME_FILE = '/etc/machine-name'


    parser = OptionParser()
    #parser.add_option("-d", "--debug", dest="debug", default=False,help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-r", "--run", dest="run", default=False, help="Runs tracking directly", action="store_true")
    parser.add_option("-d", "--draw", dest="draw", default=False, help="Draws real time tracking results on XOrg", action="store_true")
    parser.add_option("-i", "--input", dest="input", default=None, help="A video file to use as an input (alternative to real time camera)")
    parser.add_option("-o", "--video-out", dest="video_out", default=None, help="A video file to save an annotated video at")
    parser.add_option("-j", "--json", dest="json", default=None, help="A JSON config file")
    parser.add_option("-p", "--port", dest="port", default=9000,help="port")
    parser.add_option("-b", "--branch", dest="branch", default="psv-package",help="the branch to work from")
    parser.add_option("-e", "--results-dir", dest="results_dir", default=ETHOGRAM_DIR,help="Where temporary result files are stored")
    parser.add_option("-g", "--git-dir", dest="git_dir", default=GIT_WORKING_DIR,help="Where is the target git located(for software update)")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Shows all logging messages", action="store_true")


    (options, args) = parser.parse_args()
    option_dict = vars(options)

    port = option_dict["port"]
    branch = option_dict["branch"]


    machine_id = get_machine_info(MACHINE_ID_FILE)
    machine_name = get_machine_info(MACHINE_NAME_FILE)

    version = get_version(option_dict["git_dir"], branch)

    if option_dict["json"]:
        import json
        with open(option_dict["json"]) as f:
            data = json.loads(f.read())
    else:
        data = None


    VIDEO_FILE = option_dict["input"]
    ETHOGRAM_DIR = option_dict["results_dir"]

    control = ControlThread(machine_id=machine_id,
                            name=machine_name,
                            version=version,
                            ethoscope_dir=option_dict["results_dir"],
                            data=data)

    if option_dict["debug"]:
        #fixme
        logging.basicConfig(level=logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")



    if option_dict["run"]:
        control.start()


    try:
        run(api, host='0.0.0.0', port=port, server='cherrypy',debug=option_dict["debug"])



    except Exception as e:

        logging.error(e)
        close(1)
    finally:
        close()




