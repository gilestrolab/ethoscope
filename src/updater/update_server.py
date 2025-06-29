import bottle
import logging
import traceback
import os
import socket

from optparse import OptionParser
from helpers import assert_node, WrongMachineID
from helpers import get_commit_version, generate_new_device_map, updates_api_wrapper, reload_node_daemon, reload_device_daemon

import updater


class UnexpectedAction(Exception):
    """Exception raised when an unexpected action is requested"""
    pass


# Action constants
ACTION_UPDATE = "update"
ACTION_SWITCH_BRANCH = "swBranch" 
ACTION_RESTART = "restart"
ACTION_CHECK_UPDATE = "check_update"
ACTION_ACTIVE_BRANCH = "active_branch"
ACTION_AVAILABLE_BRANCHES = "available_branches"
ACTION_RESTART_DAEMON = "restart_daemon"
ACTION_CHANGE_BRANCH = "change_branch"


def handle_node_update():
    """Handle local node update operation"""
    try:
        old_commit = ethoscope_updater.get_current_commit()
        ethoscope_updater.update()
        new_commit = ethoscope_updater.get_current_commit()
        return {
            "status": "success",
            "device_id": "node",
            "old_commit": get_commit_version(old_commit),
            "new_commit": get_commit_version(new_commit)
        }
    except Exception as e:
        return {
            "status": "error", 
            "device_id": "node",
            "error": str(e)
        }


def handle_node_branch_change(new_branch):
    """Handle local node branch change operation"""
    try:
        ethoscope_updater.change_branch(new_branch)
        return {
            "status": "success",
            "device_id": "node",
            "new_branch": new_branch
        }
    except Exception as e:
        return {
            "status": "error",
            "device_id": "node",
            "error": str(e)
        }


def handle_node_daemon_restart():
    """Handle local node daemon restart operation"""
    try:
        reload_node_daemon()
        return {
            "status": "daemon_restarted",
            "device_id": "node"
        }
    except Exception as e:
        return {
            "status": "error",
            "device_id": "node",
            "error": str(e)
        }


app = bottle.Bottle()
STATIC_DIR = "./static"

##################
# Bottle framework
##################

@app.get('/favicon.ico')
def get_favicon():
    assert_node(is_node)
    return server_static('/img/favicon.ico')

@app.route('/static/<filepath:path>')
def server_static(filepath):
    assert_node(is_node)
    return bottle.static_file(filepath, root=STATIC_DIR)

@app.route('/')
def index():
    assert_node(is_node)
    return bottle.static_file('index.html', root=STATIC_DIR)


##########################
## UPDATE API
# All devices and node:
###########################

@app.get('/device/<action>/<id>')
def device(action, id):
    """
    Control update state / get info about a node or device

    :param action: what to do
    :return:
    """
    if id != device_id:
        raise WrongMachineID("Not the same ID")
    
    try:
        if action == ACTION_CHECK_UPDATE:
            local_commit, origin_commit = ethoscope_updater.get_local_and_origin_commits()
            up_to_date = local_commit == origin_commit
            # @pepelisu you can get
            #data["local_commit"]["id"] -> a34fac...
            #data["local_commit"]["date"] -> 2015-01-24 12:23:00
            return {"up_to_date":up_to_date,
                    "local_commit":get_commit_version(local_commit),
                    "origin_commit":get_commit_version(origin_commit)
                    }
        if action == ACTION_ACTIVE_BRANCH:
            return {"active_branch": str(ethoscope_updater.active_branch)}
            
        if action == ACTION_AVAILABLE_BRANCHES:
            return {"available_branches": str(ethoscope_updater.available_branches())}


        if action == ACTION_UPDATE:
            old_commit, _= ethoscope_updater.get_local_and_origin_commits()
            ethoscope_updater.update_active_branch()
            new_commit, _= ethoscope_updater.get_local_and_origin_commits()

            return {"old_commit":get_commit_version(old_commit),
                    "new_commit":get_commit_version(new_commit)
                    }
        if action == ACTION_RESTART_DAEMON:
            if is_node:
                reload_node_daemon()
            else:
                reload_device_daemon()
            return {"status": "daemon_restarted"}
        else:
            raise UnexpectedAction()

    except Exception as e:
        logging.error(traceback.format_exc())
        return {'error': traceback.format_exc()}


@app.post('/device/<action>/<id>')
def change_branch(action, id):

    if id != device_id:
        raise WrongMachineID("Not the same ID")
    
    try:
        data = bottle.request.json
        if not data or 'new_branch' not in data:
            return {'error': 'Missing required field: new_branch'}
        branch = data['new_branch']
        if action == ACTION_CHANGE_BRANCH:
            ethoscope_updater.change_branch(branch)

        return {"new_branch": branch}

    except Exception as e:
        logging.error(traceback.format_exc())
        return {'error': traceback.format_exc()}
        
@app.get('/id')
def name():
    try:
        return {"id": device_id}
    except Exception as e:
        return {'error':traceback.format_exc()}


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
            #out = bare_repo_updater.update_all_branches()
            return out
        elif action == 'discover_branches':
            out = bare_repo_updater.discover_branches()
            return out
        else:
            raise UnexpectedAction()

    except Exception as e:
        logging.error(traceback.format_exc())
        return {'error': traceback.format_exc()}



@app.get('/node_info')
def node_info():#, device):
    try:
        assert_node(is_node)
        host = bottle.request.get_header('host')
        return {'ip': "http://{}".format(host),
                'status': "NA",
                "id": "node"}

    except Exception as e:
        logging.error(e)
        return {'error': traceback.format_exc()}

@app.get('/devices')
def scan_subnet():
    try:
        assert_node(is_node)
        devices_map = generate_new_device_map()
        return devices_map
        
    except Exception as e:
        logging.error("Unexpected exception when scanning for devices:")
        logging.error(traceback.format_exc())
        return {'error': traceback.format_exc()}



@app.post('/group/<what>')
def group(what):
    try:
        responses = []
        data = bottle.request.json
        if not data or 'devices' not in data:
            return {'error': 'Missing required field: devices'}
        if what == ACTION_UPDATE:
            for device in data["devices"]:
                # Handle node updates locally, device updates via API
                if device['id'] == 'node':
                    # Update node locally
                    response = handle_node_update()
                    responses.append(response)
                    
                    # Handle node daemon restart locally
                    response = handle_node_daemon_restart()
                    responses.append(response)
                else:
                    # Update devices via API
                    response = updates_api_wrapper(device['ip'], device['id'], what='device/update')
                    responses.append(response)
                    # Restart daemon via API
                    response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
                    responses.append(response)
        elif what == ACTION_SWITCH_BRANCH:
            for device in data["devices"]:
                if device['id'] == 'node':
                    # Handle node branch switching locally
                    if 'new_branch' not in device:
                        responses.append({'error': 'Missing new_branch for node device', 'device_id': 'node'})
                        continue
                    response = handle_node_branch_change(device['new_branch'])
                    responses.append(response)
                    
                    # Handle node daemon restart locally
                    response = handle_node_daemon_restart()
                    responses.append(response)
                else:
                    data_one_dev = {'new_branch': device['new_branch']}
                    response = updates_api_wrapper(device['ip'], device['id'], what='device/change_branch', data=data_one_dev)
                    responses.append(response)
                    # Restart daemon via API
                    response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
                    responses.append(response)
        elif what == ACTION_RESTART:
            for device in data["devices"]:
                if device['id'] == 'node':
                    response = handle_node_daemon_restart()
                else:
                    response = updates_api_wrapper(device['ip'], device['id'], what='device/restart_daemon')
                responses.append(response)
        return {'response':responses}

    except Exception as e:
        logging.error("Unexpected exception when updating devices:")
        logging.error(traceback.format_exc())
        return {'error': traceback.format_exc()}

def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)

#======================================================================================================================#
#############
### CLASSS TO BE REMOVED IF BOTTLE CHANGES TO 0.13
############
class CherootServer(bottle.ServerAdapter):
    def run(self, handler): # pragma: no cover
        from cheroot import wsgi
        from cheroot.ssl import builtin
        self.options['bind_addr'] = (self.host, self.port)
        self.options['wsgi_app'] = handler
        certfile = self.options.pop('certfile', None)
        keyfile = self.options.pop('keyfile', None)
        chainfile = self.options.pop('chainfile', None)
        server = wsgi.Server(**self.options)
        if certfile and keyfile:
            server.ssl_adapter = builtin.BuiltinSSLAdapter(
                    certfile, keyfile, chainfile)
        try:
            server.start()
        finally:
            server.stop()
#############

if __name__ == '__main__':
    """
    The same server runs on both the ethoscope and the node.
    If no -b flag is passed specifying the location of the bare repo, then
    we assume that we are on an ethoscope, otherwise we assume we run on the node
    
    URLs available on the node are:
    /
    /bare/<action>
    /node_info
    /devices
    /group/<what>
    
    URLs available on the ethoscope are:
    /device/<action>/<id> (POST and GET)
    /id
    
    """

    logging.getLogger().setLevel(logging.INFO)
    parser = OptionParser()

    parser.add_option("-g", "--git-local-repo", dest="local_repo", help="Route to local repository to update")
    parser.add_option("-b", "--bare-repo", dest="bare_repo", default=None, help="Route to bare repository")
    parser.add_option("-p", "--port", default=8888, dest="port", help="The port to run the server on. Default 8888")
    parser.add_option("-D", "--debug", dest="DEBUG", default=False, help="Set DEBUG mode ON", action="store_true")

    (options, args) = parser.parse_args()

    if not options.local_repo:
        raise Exception("You must specify the location of the GIT repo to update using the -g or --git-local-repo flags.")


    ethoscope_updater = updater.DeviceUpdater(options.local_repo)

    if options.bare_repo is not None:
        is_node = True
        bare_repo_updater = updater.BareRepoUpdater(options.bare_repo)
        device_id = "node"

    else:
        is_node = False
        from ethoscope.web_utils.helpers import get_machine_id
        bare_repo_updater = None
        device_id = get_machine_id()

    try:
        # Use cheroot server (modern replacement for cherrypy)
        try:
            from cherrypy import wsgiserver
            server = "cherrypy"
        except ImportError:
            # Use cheroot server when cherrypy wsgiserver is not available
            bottle.server_names["cherrypy"] = CherootServer(host='0.0.0.0', port=options.port)
            server = "cherrypy"
            
        bottle.run(app, host='0.0.0.0', port=options.port, debug=options.DEBUG, server=server)

    except KeyboardInterrupt:
        logging.info("Stopping update server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc())
        logging.error(f"Port {options.port} is probably not accessible for you. Maybe use another one e.g.`-p 8000`")

    except Exception as e:
        logging.error(traceback.format_exc())
        close(1)
 
    finally:
        close()
