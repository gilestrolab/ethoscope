from bottle import *

import subprocess
import socket
import json
import logging
import traceback
import urllib2
from optparse import OptionParser

import updater


app = Bottle()
STATIC_DIR = "./static"

######################
# Helpers
######################

class UnexpectedAction(Exception):
    pass
class NotNode(Exception):
    pass
def get_commit_version(commit):
    return {"id":str(commit),
            "date":datetime.datetime.utcfromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                    }
def assert_node():
    if not is_node:
        raise NotNode("This device is not a node.")

def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)

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

@app.get('/self_device/<action>')
def device(action):
    """
    Control update state/ get info about a node or device

    :param action: what to do
    :return:
    """
    try:
        if action == 'check-update':
            local_commit, origin_commit = ethoscope_updater.get_local_and_origin_commits()
            up_to_date = local_commit == origin_commit


            # @pepelisu you can get
            #data["local_commit"]["id"] -> a34fac...
            #data["local_commit"]["date"] -> 2015-01-24 12:23:00
            return {"up_to_date":up_to_date,
                    "local_commit":get_commit_version(local_commit),
                    "origin_commit":get_commit_version(origin_commit)
                    }
        if action == 'update':
            ethoscope_updater.update_active_branch()
            # daemon_port = 80 or 9000
            #todo send a signal to restart device (0.0.0.0:daemon_port)

        else:
            raise UnexpectedAction()

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}


@app.post('/self/change_branch/')
def change_branch(action):
    #todo
    data = request.json



###############################
## UPDATES API
# Node only functions
###############################


@app.get('/bare/<action>')
def bare(action):
    try:
        assert_node()
        if action == 'update':
            bare_repo.update_all_visible_branches()
        elif action == 'discover_branches':
            bare_repo.discover_branches()
        else:
            raise Exception("Unexpected action.")
        return {}

    except Exception as e:
        logging.error(traceback.format_exc(e))
        return {'error': traceback.format_exc(e)}

@app.get('/devices')
def scan_subnet(ip_range=(2,253)):
    try:
        assert_node()
        devices_map = make_device_map(ip_range,SUBNET_DEVICE)
        return devices_map
    except Exception as e:
        logging.error("Unexpected exception when scanning for devices:")
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
    parser.add_option("-l", "--local-repo", dest="local_repo", help="route to local repository to update")
    # when no bare repo path is declares. we are in a device else, we are on a node
    parser.add_option("-b", "--bare-repo", dest="bare_repo", default=None, help="route to bare repository")
    parser.add_option("-ip", "--node-ip", dest="node_ip", help="Ip of the node in the local network")
    parser.add_option("-p", "--port", dest="port", help="the port to run the server on")

    (options, args) = parser.parse_args()

    option_dict = vars(options)
    local_repo = option_dict["local_repo"]
    bare_repo = option_dict["bare_repo"]
    node_ip = option_dict["node_ip"]
    port = option_dict["port"]




    ethoscope_updater = updater.BaseUpdater(local_repo)

    if bare_repo is not None:
        bare_repo_updater = updater.BareRepoUpdater(bare_repo)
        is_node = True
    else:
        bare_repo_updater = None
        is_node = False



    try:
        run(app, host='0.0.0.0', port=port, debug=debug, server='cherrypy')

    except KeyboardInterrupt:
        logging.info("Stopping update server cleanly")
        pass

    except socket.error as e:
        logging.error(traceback.format_exc(e))
        logging.error("Port %i is probably not accessible for you. Maybe use another one e.g.`-p 8000`" % PORT)

    except Exception as e:
        logging.error(traceback.format_exc(e))
        close(1)
    finally:
        close()
