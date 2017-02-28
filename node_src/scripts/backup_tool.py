__author__ = 'quentin'

from ethoscope_node.utils.backups_helpers import GenericBackupWrapper
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError
import logging
import optparse
import  traceback
import os
from ethoscope_node.utils.helpers import  get_local_ip

class BackupClass(object):
    _db_credentials = {
            "name":"ethoscope_db",
            "user":"ethoscope",
            "password":"ethoscope"
        }
    def __init__(self, device_info, results_dir):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])
        self._results_dir = results_dir


    def run(self):
        try:
            if "backup_path" not in self._device_info:
                raise KeyError("Could not obtain device backup path for %s" % self._device_info["id"])

            if self._device_info["backup_path"] is None:
                raise ValueError("backup path is None for device %s" % self._device_info["id"])
            backup_path = os.path.join(self._results_dir, self._device_info["backup_path"])

            mirror= MySQLdbToSQlite(backup_path, self._db_credentials["name"],
                            remote_host=self._database_ip,
                            remote_pass=self._db_credentials["password"],
                            remote_user=self._db_credentials["user"])

            mirror.update_roi_tables()

        except DBNotReadyError as e:
            logging.warning(e)
            logging.warning("Database not ready, will try later")
            pass

        except Exception as e:
            logging.error(traceback.format_exc(e))

def backup_job(args):
    try:
        device_info, results_dir = args
        logging.info("Initiating backup for device  %s" % device_info["id"])

        backup_job = BackupClass(device_info, results_dir= results_dir)
        logging.info("Running backup for device  %s" % device_info["id"])
        backup_job.run()
        logging.info("Backup done for for device  %s" % device_info["id"])
    except Exception as e:
        logging.error("Unexpected error in backup. args are: %s" % str(args))
        logging.error(traceback.format_exc(e))



if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    try:
        parser = optparse.OptionParser()
        parser = optparse.OptionParser()
        parser.add_option("-D", "--debug", dest="debug", default=False, help="Set DEBUG mode ON", action="store_true")
        parser.add_option("-e", "--results-dir", dest="results_dir", default="/ethoscope_results",
                          help="Where temporary result files are stored")
        parser.add_option("-r", "--subnet-ip", dest="subnet_ip", default="192.169.123.0",
                          help="the ip of the router in your setup")
        parser.add_option("-s", "--safe", dest="safe", default=False,help="Set Safe mode ON", action="store_true")
        parser.add_option("-l", "--local", dest="local", default=False,
                          help="Run on localhost (run a node and device on the same machine, for development)",
                          action="store_true")
        (options, args) = parser.parse_args()
        option_dict = vars(options)

        local_ip = get_local_ip(option_dict["subnet_ip"], localhost=option_dict["local"])


        gbw = GenericBackupWrapper(backup_job,
                                   option_dict["results_dir"],
                                   option_dict["safe"], local_ip
                                   )
        gbw.run()

    except Exception as e:
        logging.error(traceback.format_exc(e))
