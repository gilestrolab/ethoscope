import bottle
import updater
import logging
import traceback
import os
import socket

from optparse import OptionParser
from helpers import get_machine_id, assert_node, WrongMachineID
from helpers import get_commit_version, generate_new_device_map, updates_api_wrapper, reload_node_daemon, reload_device_daemon


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
        logging.error(traceback.format_exc())
        return {'error': traceback.format_exc()}


@app.post('/device/<action>/<id>')
def change_branch(action, id):

    if id != device_id:
        raise WrongMachineID
    
    #todo
    try:
        data = bottle.request.json
        branch = data['new_branch']
        if action == 'change_branch':
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
                response = updates_api_wrapper(device['ip'], device['id'], what='device/change_branch', data=data_one_dev)
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
    parser.add_option("-r", "--router-ip", dest="router_ip", default="192.169.123.254", help="the ip of the router in your setup")
    parser.add_option("-p", "--port", default=8888, dest="port", help="The port to run the server on. Default 8888")
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    local_repo = option_dict["local_repo"]
    bare_repo = option_dict["bare_repo"]
    PORT = option_dict["port"]
    DEBUG = option_dict["debug"]

    if not local_repo:
        raise Exception("You must specify the location of the GIT repo to update using the -g or --git-local-repo flags.")


    ethoscope_updater = updater.DeviceUpdater(local_repo)

    #Here we decide if we are running on an ethoscope or a node
    if bare_repo is not None:
        bare_repo_updater = updater.BareRepoUpdater(bare_repo)
        is_node = True
        device_id = "node"

    else:
        bare_repo_updater = None
        is_node = False
        device_id = get_machine_id()

    try:
        ####### TO be remove when bottle changes to version 0.13
        server = "cherrypy"
        try:
            from cherrypy import wsgiserver
        except:
            # Trick bottle to think that cheroot is actulay cherrypy server adds the pacth to BOTTLE
            bottle.server_names["cherrypy"] = CherootServer(host='0.0.0.0', port=PORT)
            logging.warning("Cherrypy version is bigger than 9, we have to change to cheroot server")
            pass
        #########
        bottle.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, server='cherrypy')

    except KeyboardInterrupt:
        logging.info("Stopping update server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc())
        logging.error("Port %i is probably not accessible for you. Maybe use another one e.g.`-p 8000`" % port)

    except Exception as e:
        logging.error(traceback.format_exc())
        close(1)
 
    finally:
        close()
