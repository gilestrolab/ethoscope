from bottle import *

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
    assert_node(is_node)
    return server_static(STATIC_DIR+'/img/favicon.ico')

@app.route('/static/<filepath:path>')
def server_static(filepath):
    assert_node(is_node)
    return static_file(filepath, root=STATIC_DIR)

@app.route('/')
def index():
    assert_node(is_node)
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


@app.post('/device/<action>/<id>')
def change_branch(action, id):
    #todo
    try:
        data = request.json
        branch = data['new_branch']
        if action == 'change_branch':
            ethoscope_updater.change_branch(branch)

        return {"new_branch": branch}

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}
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



@app.get('/node_info')
def node_info():#, device):
    try:
        assert_node(is_node)
        return {'ip': "http://" + LOCAL_IP,
                'status': "NA",
                "id": "node"}

    except Exception as e:
        logging.error(e)
        return {'error': traceback.format_exc(e)}

@app.get('/devices')
def scan_subnet(ip_range=(6,253)):
    try:
        assert_node(is_node)
        devices_map = generate_new_device_map(LOCAL_IP, ip_range)
        return devices_map
    except Exception as e:
        logging.error("Unexpected exception when scanning for devices:")
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}



@app.post('/group/<what>')
def group(what):
    try:
        responses = []
        data = request.json
        if what == "update":
            for device in data["devices"]:
                response = updates_api_wrapper(device['ip'], device['id'], what='device/update')
                responses.append(response)
            for device in data["devices"]:
                response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
                responses.append(response)
        elif what == "swBranch":
            for device in data["devices"]:
                data_one_dev = {'new_branch': device['new_branch']}
                response = updates_api_wrapper(device['ip'], device['id'], what='device/change_branch',
                                               data=data_one_dev)
                responses.append(response)
            for device in data["devices"]:
                response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
                responses.append(response)
        elif what == "restart":
            for device in data["devices"]:
                response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
                responses.append(response)
        return {'response':responses}
    except Exception as e:
        logging.error("Unexpected exception when updating devices:")
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}

def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)


if __name__ == '__main__':

    logging.getLogger().setLevel(logging.INFO)
    parser = OptionParser()

    parser.add_option("-g", "--git-local-repo", dest="local_repo", help="route to local repository to update")
    # when no bare repo path is declares. we are in a device else, we are on a node
    parser.add_option("-b", "--bare-repo", dest="bare_repo", default=None, help="route to bare repository")
    #parser.add_option("-i", "--node-ip", dest="node_ip", help="Ip of the node in the local network")
    parser.add_option("-r", "--router-ip", dest="router_ip", default="192.169.123.254",
                      help="the ip of the router in your setup")
    parser.add_option("-p", "--port", default=8888, dest="port", help="the port to run the server on")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    local_repo = option_dict["local_repo"]
    if not local_repo:
        raise Exception("Where is the git wd to update?. use -g")

    bare_repo = option_dict["bare_repo"]
    port = option_dict["port"]

    MACHINE_ID_FILE = '/etc/machine-id'
    DEBUG = option_dict["debug"]


    ethoscope_updater = updater.DeviceUpdater(local_repo)

    if bare_repo is not None:
        bare_repo_updater = updater.BareRepoUpdater(bare_repo)
        is_node = True
        device_id = "Node"

    else:
        bare_repo_updater = None
        is_node = False
        device_id = get_machine_info(MACHINE_ID_FILE)

    LOCAL_IP = get_local_ip(option_dict["router_ip"], is_node=is_node)
    try:
        WWW_IP = get_internet_ip()
    except Exception as e:
        if is_node:
            logging.warning("Could not access internet!")
            logging.warning(traceback.format_exc(e))
        WWW_IP = None


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
