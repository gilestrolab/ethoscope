__author__ = 'luis'

import logging
from bottle import *
from pysolovideo.web_utils.control_thread import ControlThread
from pysolovideo.web_utils.helpers import get_machine_id
from pysolovideo.utils.debug import PSVException

api = Bottle()

@api.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root="/")


@api.get('/id')
def name():
    return {"id" : machine_id, "type": "sm"}

@api.get('/controls/<id>/<action>')
def controls(id, action):
    global control

    if id == machine_id:

            try:
                if action == 'start':
                    # Sync clocks with the node or master
                    #data = request.json
                    #t = data['time']
                    # set time, given in milliseconds from javascript, used in seconds for date
                    #set_time = call(['date', '-s', '@' + str(t)[:-3]])
                    #FIXME should not draw unless for debug
                    control = ControlThread(machine_id, out_file=OUT_CSV_FILE, draw_results = True, max_duration=60*60)

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
            if control != None:
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
            else:
                return {"status": "stopped"}

        except Exception as e:
            return control.format_psv_error(e)
    else:
        return "Error on machine ID"


if __name__ == '__main__':

    machine_id = get_machine_id()

    #FIXME

    #OUT_CSV_FILE = zipfile.ZipFile("/tmp/out.zip","w",zipfile.ZIP_DEFLATED)
    #OUT_CSV_FILE =
    import gzip
    import sys
    OUT_CSV_FILE = gzip.open("/tmp/out.csv.gz","w")
    # OUT_CSV_FILE = sys.stdout

    #create object
    control = None #ControlThread(machine_id)

    # try:
    # TODO
    try:
        run(api, host='0.0.0.0', port=9000, debug=True)

    finally:
        control.stop()
        control.join()


