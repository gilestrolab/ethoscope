from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper, receive_devices
from ethoscope_node.utils.device_scanner import EthoscopeScanner

import logging
import optparse
import traceback
import os

import json
import bottle
app = bottle.Bottle()


@app.route('/')
def index():
    '''
    '''
    return gbw.devices_to_backup


if __name__ == '__main__':
    
    CFG = EthoscopeConfiguration()
    
    logging.getLogger().setLevel(logging.INFO)

    parser = optparse.OptionParser()
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-r", "--results-dir", dest="results_dir", help="Where result files are stored")
    parser.add_option("-i", "--server", dest="NODE_ADDRESS", default="localhost", help="The server on which the node is running will be interrogated first for the device list")
    parser.add_option("-s", "--safe", dest="safe", default=False, help="Set Safe mode ON", action="store_true")
    parser.add_option("-e", "--ethoscope", dest="ethoscope", help="Force backup of given ethoscope number (eg: 007)")
    
    (options, args) = parser.parse_args()
    option_dict = vars(options)

    RESULTS_DIR = option_dict["results_dir"] or CFG.content['folders']['results']['path']
    SAFE_MODE = option_dict["safe"]
    DEBUG = option_dict["debug"]

    ethoscope = option_dict["ethoscope"]
    NODE_ADDRESS = option_dict["NODE_ADDRESS"]

    if DEBUG:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")


    
    if ethoscope:
        # We have provided a dash separated list of ethoscopes to backup
        
        all_devices = receive_devices(NODE_ADDRESS)

        try:
            ethoscopes = [int(ethoscope)]
        except:
            ethoscopes = [int(e) for e in ethoscope.split("-")]
            
        for ethoscope in ethoscopes:
            print ("Forcing backup for ethoscope %03d" % ethoscope)
            
            bj = None
            for devID in all_devices:
                try:
                    if 'name' in all_devices[devID] and all_devices[devID]['name'] == ("ETHOSCOPE_%03d" % ethoscope) and all_devices[devID]['status'] != "offline":
                        bj = backup_job((all_devices[devID], RESULTS_DIR))
                except:
                    pass
            if bj == None: exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)

    else:

        try:
        # We start in server mode

            gbw = GenericBackupWrapper( RESULTS_DIR, SAFE_MODE, NODE_ADDRESS)
            gbw.start()

            bottle.run(app, host='0.0.0.0', port=82)

        except KeyboardInterrupt:
            logging.info("Stopping server cleanly")
