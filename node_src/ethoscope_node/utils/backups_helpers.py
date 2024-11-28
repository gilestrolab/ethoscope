from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError

import os
import logging
import time
import traceback
import optparse
import subprocess
import urllib.request, urllib.error, urllib.parse
import json

import threading

class BackupClass(object):
    '''
    The default backup class. Will connect to the ethoscope mysql and mirror its content into the local sqlite3
    '''
    
    _db_credentials = {
            "name":"ethoscope_db",
            "user":"ethoscope",
            "password":"ethoscope"
        }
    
    def __init__(self, device_info, results_dir):

        self._device_info = device_info
        self._database_ip = os.path.basename(self._device_info["ip"])
        self._results_dir = results_dir


    def backup (self):
        try:
            if "backup_path" not in self._device_info:
                raise KeyError("Could not obtain device backup path for %s" % self._device_info["id"])

            if self._device_info["backup_path"] is None:
                raise ValueError("backup path is None for device %s" % self._device_info["id"])
            backup_path = os.path.join(self._results_dir, self._device_info["backup_path"])

            self._db_credentials["name"] = "%s_db" % self._device_info["name"]

            mirror = MySQLdbToSQlite(backup_path, self._db_credentials["name"],
                            remote_host=self._database_ip,
                            remote_pass=self._db_credentials["password"],
                            remote_user=self._db_credentials["user"])

            mirror.update_roi_tables()
            
            logging.info("Backup status for %s is %0.2f%%" %(self._device_info["id"], mirror.compare_databases() ))
            return True

        except DBNotReadyError as e:
            logging.warning(e)
            logging.warning("Database %s on IP %s not ready, will try later" % (self._db_credentials["name"], self._database_ip) )
            return False

        except Exception as e:
            logging.error(traceback.format_exc())
            return False

class VideoBackupClass(object):
    '''
    The video backup class. Will connect to the ethoscope and mirror its video chunks in the node
    The class uses a wget wrapper to download the binary files from the ethoscope webserver on port 9000
    '''

    def __init__(self, device_info, results_dir, port=9000, static_dir="static"):

        self._device_info = device_info
        self._id = self._device_info["id"]
        self._ip = self._device_info["ip"]
        self._port = port
        self._database_ip = os.path.basename(self._ip)
        self._results_dir = results_dir

        self._device_url = f"http://{self._ip}:{self._port}"
        self._static_url = f"{self._device_url}/{static_dir}"

    def backup(self):

        try:
            yield json.dumps({"status": "info", "message": f"Backup initiated for device {self._id}"})

            video_list = self.get_video_list()

            if video_list is None:
                yield json.dumps({"status": "warning", "message": f"No videos to download for device{self._id}"})
                return

            total_videos = len(video_list)
            for count, v in enumerate(video_list, start=1):
                try:
                    yield json.dumps({"status": "info", "message": "Starting download of video %s (%d/%d)" % (v, count, total_videos)})
                    wget_output = self.wget_mirror_wrapper(v, target_prefix=self._static_url, output_dir=self._results_dir)
                    self.remove_remote_video(v)
                except Exception as e:
                    logging.warning(f"Error downloading video {v}: {e}")
                    yield json.dumps({"status": "error", "message": "Error downloading video %s: %s" % (v, str(e))})

            yield json.dumps({"status": "success", "message": "Backup done for device %s" % self._device_info["id"]})

        except Exception as e:
            logging.error(traceback.format_exc())
            yield json.dumps({"status": "error", "message": "Error during backup for device %s: %s" % (self._device_info["id"], str(e))})

    
    def wget_mirror_wrapper(self, target, target_prefix, output_dir, cut_dirs=3):
        """
        Downloads files from a specified target URL using wget.

        This function constructs a command to use the `wget` utility for mirroring files
        from a remote server. It builds the appropriate command-line arguments and executes
        the command, directing the output to a specified local directory. The function
        also allows for cutting specific levels from the directory structure of the downloaded files.

        Args:
            target (str): The target file or directory to download, relative to the target_prefix.
            target_prefix (str): The base URL prefix to prepend to the target.
            output_dir (str): The local directory where the files will be downloaded.
            cut_dirs (int, optional): The number of directory levels to cut from the input URL. 
                                    Defaults to 3.

        Returns:
            bool: True if the download was successful; False if no content was downloaded.

        Raises:
            Exception: If the wget command fails to execute successfully, an Exception
                        is raised with the return code and the output from wget.
        """

        target = target_prefix + target
        command_arg_list=  ["wget",
                            target,
                            "-nv",          # non verbose
                            "-c",           # resume incomplete downloads
                            "--mirror",     # mirror the file keeping timestamps and other metadata
                            "--cut-dirs=%i" % cut_dirs,
                            "-nH",          # The `-nH` option tells wget not to create a directory named after the hostname of the URL.
                            "--directory-prefix=%s" % output_dir
                            ]
        p = subprocess.Popen(command_arg_list,  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        stdout, stderr = p.communicate()
        if p.returncode != 0:
            raise Exception("Error %i: %s" % ( p.returncode,stdout))

        if stdout == "":
            return False             #no file downloaded

        return True

    def get_video_list(self, index_file="ethoscope_data/results/index.html"):
        """
        Retrieve a list of video file names from a specified index file on the server.

        This function constructs the URL to the index file containing a list of available video files
        located at the specified path. It attempts to fetch the contents of the index file from the server,
        decoding each line and returning a list of video file names. If the index file cannot be found,
        it logs a warning and returns None.

        Args:
            index_file (str): The relative path to the index file on the server. Defaults to 
                            "ethoscope_data/results/index.html".

        Returns:
            list or None: A list of video file names retrieved from the index file if successful; 
                        None if the index file cannot be accessed or found.

        Raises:
            urllib.error.HTTPError: If the index file URL is inaccessible due to an HTTP error.
        """
        video_list_url = f"{self._static_url}/{index_file}"
        try:
            response = urllib.request.urlopen(video_list_url)
            video_list = [r.decode('utf-8').rstrip() for r in response]
        except urllib.error.HTTPError as e:
            logging.warning("No index file could be found for device %s" % url)
            video_list = None
        finally:
            return video_list

    def remove_remote_video(self, target):
        print (target)
        # request_url = f"{self._device_url}/rm_static_file/{self._id}"
        # data = {"file": target}
        # data =json.dumps(data)
        # req = urllib.request.Request(url=request_url, data=data, headers={'Content-Type': 'application/json'})
        # _ = urllib.request.urlopen(req, timeout=5)


    def make_index(self, url, port=9000, page="make_index"):
        """
        Asks the remote ethoscope to generate an index file.

        This function constructs the full URL to access a specified page on the server
        and attempts to fetch the page. If the request is successful, it indicates that 
        the index has been generated successfully. If the page cannot be found, it logs 
        a warning and returns False.

        Args:
            url (str): The base URL of the device or server.
            port (int, optional): The port number on which the server is running. Defaults to 9000.
            page (str, optional): The specific page to access on the server. Defaults to "make_index".

        Returns:
            bool: True if the index page was successfully accessed; 
                False if the page could not be found or accessed.

        Raises:
            urllib.error.HTTPError: If the server returns an error status code (4xx or 5xx) when 
                                    trying to access the specified page.
        """

        full_url = "/".join(["%s:%i"%(url,port), page])
        try:
            response = urllib.request.urlopen(full_url)
            return True
        except urllib.error.HTTPError as e:
            logging.warning("No index file could be found for device %s" % url)
            return False

class GenericBackupWrapper(threading.Thread):
    def __init__(self, results_dir, node_address, video=False):
        '''
        '''
        self._TICK = 1.0  # s
        self._BACKUP_DT = 5 * 60  # 5min
        self._results_dir = results_dir
        self._node_address = node_address
        self.backup_status = {}
        self._is_instance_video = video

        super(GenericBackupWrapper, self).__init__()

    def find_devices(self, only_active=True):
        '''
        Interrogates the NODE on its current knowledge of devices
        '''
        url = "http://%s/devices" % self._node_address
        timeout = 10
        devices = {}
        
        try:
            req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})            
            f = urllib.request.urlopen(req, timeout=timeout)
            devices = json.load(f)

        except urllib.error.URLError as e:
            logging.error("The node ethoscope server %s is not running or cannot be reached. A list of available ethoscopes could not be found." % self._node_address)
            logging.info("Using Ethoscope Scanner to look for devices")

            _device_scanner = EthoscopeScanner()
            _device_scanner.start()
            time.sleep(timeout) #let's just wait a bit
            devices = _device_scanner.get_all_devices_info()
            del _device_scanner
                
        
        if only_active:
            return [ d for d in list( devices.values() ) if (d["status"] not in ["not_in_use", "offline"] and d["name"] != "ETHOSCOPE_000") ]
        
        return devices
            

    def _backup_job(self, device_info):
        ''' Start the backup process for the specified device '''
        try:
            dev_id = device_info["id"]
            logging.info("Initiating backup for device %s" % dev_id)

            if self._is_instance_video:
                backup_job = VideoBackupClass(device_info, results_dir=self._results_dir)
            else:
                backup_job = BackupClass(device_info, results_dir=self._results_dir)

            logging.info("Running backup for device %s" % dev_id)
            self.backup_status[dev_id] = {'started': int(time.time()), 'ended': 0, 'processing': True, 'progress': {}}

            # Execute the backup as a generator
            for message in backup_job.backup():
                # Load the JSON message
                message_json = json.loads(message)
                # Update backup_status with the progress message
                self.backup_status[dev_id]['progress'] = message_json

            self.backup_status[dev_id]['processing'] = False
            logging.info("Backup done for device %s" % dev_id)
            self.backup_status[dev_id]['ended'] = int(time.time())
            return True

        except Exception as e:
            logging.error(traceback.format_exc())
            self.backup_status[dev_id]['processing'] = False
            self.backup_status[dev_id]['ended'] = -1
            self.backup_status[dev_id]['progress'] = {"status": "error", "message": str(e)}
            return False
            
        except Exception as e:
            #logging.error("Unexpected error in backup. args are: %s" % str(args))
            logging.error(traceback.format_exc())
            return False

    def run (self):
        '''
        '''
        
        t0 = time.time()
        t1 = t0 + self._BACKUP_DT

        while True:
            if t1 - t0 < self._BACKUP_DT:
                t1 = time.time()
                time.sleep(self._TICK)
                continue

            logging.info("Starting backup round")
            active_devices = self.find_devices()

            logging.info("Found %s devices online: %s" % (
                              len(active_devices),
                              ', '.join( [dev['id'] for dev in active_devices] )
                              ) )
            
            for dev in active_devices:
                if dev['id'] not in self.backup_status:
                    self.backup_status[dev['id']] = { 'started' : 0, 'ended' : 0 }
                self._backup_job (dev)
                
            t0 = t1 = time.time()
            logging.info("Backup finished at t=%i" % t1)