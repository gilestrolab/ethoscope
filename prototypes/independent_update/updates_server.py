from bottle import *

import subprocess
import socket
import json
import logging
import traceback
import urllib2

import updater



app = Bottle()
STATIC_DIR = "../static"

@app.get('/favicon.ico')
def get_favicon():
    return server_static(STATIC_DIR+'/img/favicon.ico')

@app.route('/static/<filepath:path>')
def server_static(filepath):
    return static_file(filepath, root=STATIC_DIR)

@app.route('/')
def index():
    return static_file('index.html', root=STATIC_DIR)

###############
## UPDATES API
###############

@app.get('/bare/<action>')
def bare(action):
    try:
        if isNode:
            if action == 'update':
                bare_repo.update_all_visible_branches()
            if action == 'check_branches':
                bare_repo.discover_branches()
        else:
            logging.info("this is not a Node, invalid request")
    except Exception as e:
        logging.info(e)
        pass

@app.get('/device/<action>')
def device(action):
    if isNode == False:
        try:
            if action == 'check_updates':
                local_commit, origin_commit = local_repo.get_local_and_origin_commits()
                #TODO add if local != origin ....

        except Exception as e:
            logging.error(e)


@app.get('/node/<action>')
def node(action):
        if isNode == True:
            try:
                if action == 'check_updates':

            except Exception as e:
                logging.error(e)




def close(exit_status=0):
    logging.info("Closing server")
    os._exit(exit_status)


if __name__ == '__main__':

    parser = OptionParser()
    parser.add_option("-l", "--local_repo", dest="local_repo", default=False, help="route to local repository to update",
                      action="store_true")
    parser.add_option("-b", "--bare_repo", dest="bare_repo", default=False, help="route to bare repository",
                      action="store_true")
    parser.add_option("-ip", "--node_ip", dest="node_ip", default=False, help="Ip of the node in the local network",
                      action="store_true")
    (options, args) = parser.parse_args()

    option_dict = vars(options)
    local_repo = option_dict["local_repo"]
    bare_repo = option_dict["bare_repo"]
    node_ip = option_dict["node_ip"]

    #TODO node_ip should be mandatory add checking.

    if local_repo is not False:
        repo = updater.BaseUpdater(local_repo)

    if bare_repo is not False and os.path.exists(bare_repo):
        bare_repo = updater.BareRepoUpdater()
        isNode = True


    try:
        run(app, host='0.0.0.0', port=8888, debug=debug, server='cherrypy')

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
