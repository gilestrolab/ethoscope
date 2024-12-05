import urllib.request, urllib.error, urllib.parse
import logging
import optparse
import traceback
import subprocess
import json
import sys
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.configuration import EthoscopeConfiguration

import bottle
import signal
app = bottle.Bottle()

@app.route('/')
def status():
    bottle.response.content_type = 'application/json'
    return json.dumps({'status': 'running', 'last_backup' : gbw.last_backup}, indent=2)

@app.route('/status')
def status():
    bottle.response.content_type = 'application/json'
    with gbw._lock:
        status_copy = gbw.backup_status.copy()
    return json.dumps(status_copy, indent=2)

if __name__ == '__main__':

    def signal_handler(sig, frame):
        logging.info("Received shutdown signal. Stopping backup thread...")
        gbw.stop()  # Signal the thread to stop
        gbw.join(timeout=10)  # Wait for the thread to finish
        logging.info("Shutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    CFG = EthoscopeConfiguration()

    logging.getLogger().setLevel(logging.INFO)
    try:
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-i", "--server", dest="server", default="localhost", help="The server on which the node is running will be interrogated first for the device list")        
        parser.add_option("-r", "--results-dir", dest="video_dir", help="Where video files are stored")
        parser.add_option("-s", "--safe", dest="safe", default=False,help="Set Safe mode ON", action="store_true")
        parser.add_option("-e", "--ethoscope", dest="ethoscope", help="Force backup of given ethoscope number (eg: 007)")


        (options, args) = parser.parse_args()
        option_dict = vars(options)
        VIDEO_DIR = option_dict["video_dir"] or CFG.content['folders']['video']['path']
        SAFE_MODE = option_dict["safe"]
        DEBUG = option_dict["debug"]

        ETHO_TO_BACKUP = option_dict["ethoscope"]
        NODE_ADDRESS = option_dict["server"]

        if DEBUG:
            logging.basicConfig()
            logging.getLogger().setLevel(logging.DEBUG)
            logging.info("Logging using DEBUG SETTINGS")

        # Start the backup wrapper
        gbw = GenericBackupWrapper( VIDEO_DIR, NODE_ADDRESS, video=True )

        if ETHO_TO_BACKUP:
            # We have provided an ethoscope or a comma separated list of ethoscopes to backup
            try:
                ETHO_TO_BACKUP_LIST = [int(ETHO_TO_BACKUP)]
            except:
                ETHO_TO_BACKUP_LIST = [int(e) for e in ETHO_TO_BACKUP.split(",")]
                
            for ethoscope in ETHO_TO_BACKUP_LIST:
                print ("Forcing video backup for ethoscope %03d" % ethoscope)
                
                bj = None
                for device in gbw.find_devices():
                    if device['name'] == ("ETHOSCOPE_%03d" % ethoscope):
                        bj = gbw.initiate_backup_job( device )

                if bj == None: exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)

        else:

            try:# We start in server mode
                gbw.start()
                bottle.run(app, host='0.0.0.0', port=8092)

            except KeyboardInterrupt:
                logging.info("Stopping server cleanly")
                gbw.stop()
                gbw.join(timeout=10)

    except Exception as e:
        logging.error(traceback.format_exc())
