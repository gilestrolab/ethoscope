import json
import logging
import optparse
import traceback
import sys
import signal
from http.server import BaseHTTPRequestHandler, HTTPServer
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.configuration import EthoscopeConfiguration

gbw = None  # This will be initialized later

class RequestHandler(BaseHTTPRequestHandler):
    def _send_response(self, content):
        """Helper function to send a JSON response"""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(content).encode('utf-8'))

    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/':
            self._send_response({'status': 'running', 'last_backup': gbw.last_backup})
        elif self.path == '/status':
            with gbw._lock:
                status_copy = gbw.backup_status.copy()
            self._send_response(status_copy)
        else:
            self.send_error(404, "File not found")

def signal_handler(sig, frame):
    logging.info("Received shutdown signal. Stopping backup thread...")
    gbw.stop()  # Signal the thread to stop
    gbw.join(timeout=10)  # Wait for the thread to finish
    logging.info("Shutdown complete.")
    sys.exit(0)

def main():
    global gbw

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    CFG = EthoscopeConfiguration()
    logging.getLogger().setLevel(logging.INFO)

    try:
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-i", "--server", dest="server", default="localhost", help="The server on which the node is running will be interrogated first for the device list")
        parser.add_option("-r", "--results-dir", dest="video_dir", help="Where video files are stored")
        parser.add_option("-s", "--safe", dest="safe", default=False, help="Set Safe mode ON", action="store_true")
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
        gbw = GenericBackupWrapper(VIDEO_DIR, NODE_ADDRESS, video=True)

        if ETHO_TO_BACKUP:
            # We have provided an ethoscope or a comma separated list of ethoscopes to backup
            try:
                ETHO_TO_BACKUP_LIST = [int(ETHO_TO_BACKUP)]
            except ValueError:
                ETHO_TO_BACKUP_LIST = [int(e) for e in ETHO_TO_BACKUP.split(",")]

            for ethoscope in ETHO_TO_BACKUP_LIST:
                print("Forcing video backup for ethoscope %03d" % ethoscope)

                bj = None
                for device in gbw.find_devices():
                    if device['name'] == ("ETHOSCOPE_%03d" % ethoscope):
                        bj = gbw.initiate_backup_job(device)
                if bj is None:
                    exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)
        else:
            # Start the HTTP server
            server_address = ('', 8092)  # Serve on all interfaces at port 8092
            httpd = HTTPServer(server_address, RequestHandler)

            try:
                logging.info("Starting HTTP server on port 8092...")
                gbw.start()
                httpd.serve_forever()
            except KeyboardInterrupt:
                logging.info("Stopping server cleanly")
                gbw.stop()
                gbw.join(timeout=10)

    except Exception as e:
        logging.error(traceback.format_exc())

if __name__ == '__main__':
    main()