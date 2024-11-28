import urllib.request, urllib.error, urllib.parse
import logging
import optparse
import traceback
import subprocess
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.configuration import EthoscopeConfiguration

class WGetERROR(Exception):
    pass

class SimpleWebServer(BaseHTTPRequestHandler):
    def do_GET(self):
        # Handle the /status endpoint
        if self.path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Output the content of gbw.backup_status
            response_data = json.dumps(gbw.backup_status, indent=2)
            self.wfile.write(response_data.encode("utf-8"))
        else:
            # Handle unknown endpoints
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")


if __name__ == '__main__':
    
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
                        bj = gbw._backup_job( device )

                if bj == None: exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)

        else:
            gbw.start()
            # Start a simple HTTP server on port 8090
            server_address = ('', 8090)
            httpd = HTTPServer(server_address, SimpleWebServer)
            logging.info("Starting web server on port 8090...")

            try:
                # Replace serve_forever() with an explicit request handling loop
                while True:
                    httpd.handle_request()
            except KeyboardInterrupt:
                logging.info("Shutting down the web server.")
            finally:
                httpd.server_close()

    except Exception as e:
        logging.error(traceback.format_exc())
