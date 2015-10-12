from bottle import *

import subprocess
import socket
import json
import logging
import traceback
import urllib2
from optparse import OptionParser

import updater
from helpers import *


app = Bottle()
STATIC_DIR = "./static"



##################
# Bottle framework
##################

@app.get('/favicon.ico')
def get_favicon():
    return server_static(STATIC_DIR+'/img/favicon.ico')

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root=STATIC_DIR)

@app.route('/')
def index():
    return static_file('index.html', root=STATIC_DIR)


##########################
## UPDATE API
# All devices and node:
###########################

@app.get('/device/<action>/<id>')
def device(action,id):
    """
    Control update state/ get info about a node or device

    :param action: what to do
    :return:
    """
    try:
        if action == 'check_update':
            local_commit, origin_commit = ethoscope_updater.get_local_and_origin_commits()
            up_to_date = local_commit == origin_commit


            # @pepelisu you can get
            #data["local_commit"]["id"] -> a34fac...
            #data["local_commit"]["date"] -> 2015-01-24 12:23:00
            return {"up_to_date":up_to_date,
                    "local_commit":get_commit_version(local_commit),
                    "origin_commit":get_commit_version(origin_commit)
                    }
        if action == 'active_branch':
            return {"active_branch": str(ethoscope_updater.active_branch())}
        if action == 'available_branches':
            return {"available_branches": str(ethoscope_updater.available_branches())}


        if action == 'update':
            old_commit, _= ethoscope_updater.get_local_and_origin_commits()
            ethoscope_updater.update_active_branch()
            new_commit, _= ethoscope_updater.get_local_and_origin_commits()

            return {"old_commit":get_commit_version(old_commit),
                    "new_commit":get_commit_version(new_commit)
                    }
        if action == "restart_daemon":
            if is_node:
                reload_node_daemon()
            else:
                reload_device_daemon()
        else:
            raise UnexpectedAction()

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}


@app.post('/self/change_branch/')
def change_branch(action):
    #todo
    data = request.json

@app.get('/id')
def name():
    try:
        return {"id": device_id}
    except Exception as e:
        return {'error':traceback.format_exc(e)}


###############################
## UPDATES API
# Node only functions
###############################


@app.get('/bare/<action>')
def bare(action):
    try:
        assert_node(is_node)
        if action == 'update':
            #out format looks like  {branch:up_to_date}. e.g. out["dev"]=True
            out = bare_repo_updater.update_all_visible_branches()
            return out
        elif action == 'discover_branches':
            out = bare_repo_updater.discover_branches()
            return out
        else:
            raise UnexpectedAction()
        
    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}

@app.get('/devices')
def scan_subnet(ip_range=(2,253)):
    try:
        assert_node(is_node)
        devices_map = generate_new_device_map(ip_range,SUBNET_DEVICE)
        return devices_map
    except Exception as e:
        logging.error("Unexpected exception when scanning for devices:")
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}


@app.post('/update_list')
def update_list():
    try:
        responses = []
        data = request.json
        for device in data["devices_to_update"]:
            response = updates_api_wrapper(device['ip'], device['id'], what='device/update')
            responses.append(response)
        for device in data["devices_to_update"]:
            response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
            responses.append(response)
        return {'response':responses}
    except Exception as e:
        logging.error("Unexpected exception when updating devices:")
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}



#
# @app.get('/node/<action>')
# def node(action):
#         try:
#             if action == 'check_updates':
#
#         except Exception as e:
#             logging.error(e)





if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-g", "--git-local-repo", dest="local_repo", help="route to local repository to update")
    # when no bare repo path is declares. we are in a device else, we are on a node
    parser.add_option("-b", "--bare-repo", dest="bare_repo", default=None, help="route to bare repository")
    parser.add_option("-i", "--node-ip", dest="node_ip", help="Ip of the node in the local network")
    parser.add_option("-p", "--port", default=8888, dest="port", help="the port to run the server on")

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    local_repo = option_dict["local_repo"]
    if not local_repo:
        raise Exception("Where is the git wd to update?. use -g")

    bare_repo = option_dict["bare_repo"]
    node_ip = option_dict["node_ip"]
    port = option_dict["port"]


    MACHINE_ID_FILE = '/etc/machine-id'
    MACHINE_NAME_FILE = '/etc/machine-name'

    p1 = subprocess.Popen(["ip", "link", "show"], stdout=subprocess.PIPE)
    network_devices, err = p1.communicate()

    wireless = re.search(r'[0-9]: (wl.*):', network_devices)
    if wireless is not None:
        SUBNET_DEVICE = wireless.group(1)

    else:
        logging.error("Not Wireless adapter has been detected. It is necessary to connect to Devices.")

    ethoscope_updater = updater.DeviceUpdater(local_repo)

    if bare_repo is not None:
        bare_repo_updater = updater.BareRepoUpdater(bare_repo)
        is_node = True
        device_id = "Node"

    else:
        bare_repo_updater = None
        is_node = False
        device_id = get_machine_info(MACHINE_ID_FILE)

    try:
        run(app, host='0.0.0.0', port=port, debug=debug, server='cherrypy')

    except KeyboardInterrupt:
        logging.info("Stopping update server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc(e))
        logging.error("Port %i is probably not accessible for you. Maybe use another one e.g.`-p 8000`" % port)

    except Exception as e:
        logging.error(traceback.format_exc(e))
        close(1)
    finally:
        close()
