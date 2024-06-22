from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper

import logging
import optparse
import traceback

import bottle
app = bottle.Bottle()


@app.route('/')
def index():
    return gbw.backup_status


if __name__ == '__main__':
    
    CFG = EthoscopeConfiguration()
    
    logging.getLogger().setLevel(logging.INFO)

    parser = optparse.OptionParser()
    parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
    parser.add_option("-r", "--results-dir", dest="results_dir", help="Where result files are stored")
    parser.add_option("-i", "--server", dest="NODE_ADDRESS", default="localhost", help="The server on which the node is running will be interrogated first for the device list")
    parser.add_option("-e", "--ethoscope", dest="ethoscope", help="Force backup of given ethoscope numbers (eg: 007,010,102)")
    
    (options, args) = parser.parse_args()
    option_dict = vars(options)

    RESULTS_DIR = option_dict["results_dir"] or CFG.content['folders']['results']['path']
    DEBUG = option_dict["debug"]

    ETHO_TO_BACKUP = option_dict["ethoscope"]
    NODE_ADDRESS = option_dict["NODE_ADDRESS"]

    if DEBUG:
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Logging using DEBUG SETTINGS")

    
    # Start the backup wrapper
    gbw = GenericBackupWrapper( RESULTS_DIR, NODE_ADDRESS )
    
    if ETHO_TO_BACKUP:
        # We have provided an ethoscope or a comma separated list of ethoscopes to backup
        try:
            ETHO_TO_BACKUP_LIST = [int(ETHO_TO_BACKUP)]
        except:
            ETHO_TO_BACKUP_LIST = [int(e) for e in ETHO_TO_BACKUP.split(",")]
            
        for ethoscope in ETHO_TO_BACKUP_LIST:
            print ("Forcing backup for ethoscope %03d" % ethoscope)
            
            bj = None
            for device in gbw.find_devices():
                if device['name'] == ("ETHOSCOPE_%03d" % ethoscope):
                    bj = gbw._backup_job( device )

            if bj == None: exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)

    else:
        try:
            # We start in server mode

            gbw.start()
            bottle.run(app, host='0.0.0.0', port=82)

        except KeyboardInterrupt:
            logging.info("Stopping server cleanly")
