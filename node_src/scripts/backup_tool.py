from ethoscope_node.utils.configuration import EthoscopeConfiguration
from ethoscope_node.utils.backups_helpers import GenericBackupWrapper, BackupClass
from ethoscope_node.utils.device_scanner import EthoscopeScanner

import logging
import optparse
import traceback
import os

def backup_job(args):
    try:
        device_info, results_dir = args
        logging.info("Initiating backup for device  %s" % device_info["id"])

        backup_job = BackupClass(device_info, results_dir=results_dir)
        logging.info("Running backup for device  %s" % device_info["id"])
        backup_job.run()
        logging.info("Backup done for for device  %s" % device_info["id"])
    except Exception as e:
        logging.error("Unexpected error in backup. args are: %s" % str(args))
        logging.error(traceback.format_exc())



if __name__ == '__main__':
    
    CFG = EthoscopeConfiguration()
    
    logging.getLogger().setLevel(logging.INFO)
    try:
        parser = optparse.OptionParser()
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-e", "--results-dir", dest="results_dir", help="Where result files are stored")
        parser.add_option("-s", "--safe", dest="safe", default=False, help="Set Safe mode ON", action="store_true")
        parser.add_option("-f", "--ethoscope", dest="ethoscope", help="Force backup of given ethoscope number (eg: 007)")
        
        (options, args) = parser.parse_args()
        option_dict = vars(options)
        RESULTS_DIR = option_dict["results_dir"] or CFG.content['folders']['results']['path']
        SAFE_MODE = option_dict["safe"]
        ethoscope = int(option_dict["ethoscope"])

        if ethoscope:
            print ("Forcing backup for ethoscope %03d" % ethoscope)
            es = EthoscopeScanner(results_dir = RESULTS_DIR)
            es.start()
            
            all_devices = es.get_all_devices_info()
            
            bj = None
            for devID in all_devices:
                if all_devices[devID]['name'] == ("ETHOSCOPE_%03d" % ethoscope) and all_devices[devID]['status'] != "offline":
                    bj = backup_job((all_devices[devID], RESULTS_DIR))
            if bj == None: exit("ETHOSCOPE_%03d is not online or not detected" % ethoscope)

        else:
        
            gbw = GenericBackupWrapper(backup_job,
                                       RESULTS_DIR,
                                       SAFE_MODE)
            gbw.run()

    except Exception as e:
        logging.error(traceback.format_exc())
