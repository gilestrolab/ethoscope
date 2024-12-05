from ethoscope_node.utils.device_scanner import EthoscopeScanner
from ethoscope_node.utils.mysql_backup import MySQLdbToSQlite, DBNotReadyError
from ethoscope.utils.io import get_and_hash, list_local_video_files

import os
import logging
import time, datetime
import traceback
import urllib.request, urllib.error, urllib.parse
import json
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed

class BackupClass(object):
    '''
    The default backup class. Will connect to the ethoscope mysql and mirror its content into the local sqlite3
    Each ethoscope runs its own class
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

    def check_sync_status(self):
        """
        not yet implemented
        """
        return -1, -1

    def backup(self):
        """
        Performs a backup operation for the ethoscope MySQL database to a local SQLite database.
        Yields:
            str: A JSON-encoded string with the following keys:
                 - "status": The status of the operation ("info", "success", "warning", or "error").
                 - "message": A descriptive message of the operation's progress or error.
        """
        try:
            # Starting backup process
            yield json.dumps({"status": "info", "message": f"Backup initiated for device {self._device_info['id']}"})

            # Check if backup path is available
            if "backup_path" not in self._device_info:
                raise KeyError(f"Could not obtain device backup path for {self._device_info['id']}")

            if "backup_path" not in self._device_info or self._device_info["backup_path"] is None:
                raise ValueError(f"Backup path is either not existing or is None for device {self._device_info['id']}")

            backup_path = os.path.join(self._results_dir, self._device_info["backup_path"])
            db_name = f"{self._device_info['name']}_db"
            self._db_credentials["name"] = db_name

            yield json.dumps({
                "status": "info",
                "message": f"Preparing to back up database '{db_name}' for device {self._device_info['id']} to {backup_path}"
            })

            # Initialize the MySQL to SQLite mirroring process
            mirror = MySQLdbToSQlite(
                backup_path,
                self._db_credentials["name"],
                remote_host=self._database_ip,
                remote_user=self._db_credentials["user"],
                remote_pass=self._db_credentials["password"]
            )

            # Update ROI tables in the mirror
            yield json.dumps({"status": "info", "message": f"Updating ROI tables for device {self._device_info['id']}..."})
            mirror.update_roi_tables()

            # Compare databases to ensure successful mirroring
            comparison_status = mirror.compare_databases()

            yield json.dumps({
                "status": "info",
                "message": f"Database comparison completed for device {self._device_info['id']}. Match: {comparison_status * 100:.2f}%"
            })

            # Log success if the backup completed successfully
            yield json.dumps({
                "status": "success",
                "message": f"Backup completed for device {self._device_info['id']} with status {comparison_status * 100:.2f}% match"
            })

            return True

        except DBNotReadyError as e:
            # Handle case when the database is not ready
            warning_message = f"Database {self._db_credentials['name']} on IP {self._database_ip} not ready, will try later."
            logging.warning(f"{warning_message} Exception: {e}")
            yield json.dumps({"status": "warning", "message": warning_message})
            return False

        except Exception as e:
            # Handle unexpected errors
            error_message = f"Error during database backup for device {self._device_info['id']}: {str(e)}"
            logging.error(traceback.format_exc())
            yield json.dumps({"status": "error", "message": error_message})
            return False

class VideoBackupClass(object):
    '''
    The video backup class. Will connect to the ethoscope and mirror its video chunks in the node
    The class uses a wget wrapper to download the binary files from the ethoscope webserver on port 9000
    Each ethoscope runs its own class
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
        """
        Performs a backup operation for the device by downloading its videos and returning the status as a generator of JSON messages.

        The function orchestrates the process of downloading videos associated with a device, including:
            - Retrieving the list of videos.
            - Downloading each video using the `get_and_hash` method.
            - Removing the remote copy of the video after it has been successfully downloaded.
        The function provides periodic status updates in the form of JSON strings via a generator.

        Yields:
            str: A JSON-encoded string with the following keys:
                - "status": The status of the operation ("info", "warning", "success", or "error").
                - "message": A detailed message describing the progress, warning, success, or error.

        Status Updates:
            - "info": General updates during the backup process, such as starting the backup, initiating downloads, etc.
            - "warning": Situations like no videos being available for backup.
            - "success": Indicates the successful completion of the backup process.
            - "error": Reports any errors encountered during the operation.

        Process Workflow:
            1. Initiates the backup process with an informational message.
            2. Retrieves the list of videos using the `get_video_list` method.
            - If no videos are available, generates a warning message and exits.
            3. Iterates over the video list and attempts to:
                - Download each video using the `get_and_hash` method.
                - Remove the remote video using the `remove_remote_video` method after a successful download.
            - Reports progress and errors for each video.
            4. Upon successful completion, generates a success message for the backup task.

        Error Handling:
            - Errors during video download are logged and reported as "error" status.
            - Errors during the overall backup process are logged and reported with relevant details.

        Example Output (JSON string):
            {"status": "info", "message": "Backup initiated for device 123"}
            {"status": "warning", "message": "No videos to download for device 123"}
            {"status": "info", "message": "Starting download of video video1.mp4 (1/3)"}
            {"status": "error", "message": "Error downloading video video2.mp4: NetworkError"}
            {"status": "success", "message": "Backup done for device 123"}

        Note:
            - `_id`: The device identifier.
            - `_static_url` and `_results_dir`: Configuration properties used to determine download behavior.

        Raises:
            None: All errors are handled within the function and reported via the generator.
        """

        try:
            yield json.dumps({"status": "info", "message": f"Backup initiated for device {self._id}"})

            video_list = self.get_video_list_html()
            #video_list = self.get_video_list_json()

            if video_list is None:
                yield json.dumps({"status": "warning", "message": f"No videos to download for device{self._id}"})
                return

            total_videos = len(video_list)
            for count, v in enumerate(video_list, start=1):
                try:
                    yield json.dumps({"status": "info", "message": "Starting download of video %s (%d/%d)" % (v, count, total_videos)})
                    wget_output = get_and_hash(v, target_prefix=self._static_url, output_dir=self._results_dir)

                except Exception as e:
                    logging.warning(f"Error downloading video {v}: {e}")
                    yield json.dumps({"status": "error", "message": "Error downloading video %s: %s" % (v, str(e))})

            yield json.dumps({"status": "success", "message": "Backup done for device %s" % self._device_info["id"]})

        except Exception as e:
            logging.error(traceback.format_exc())
            yield json.dumps({"status": "error", "message": "Error during backup for device %s: %s" % (self._device_info["id"], str(e))})


    def get_video_list_json(self):
        """
        Returns a dictionary containing information about the video files on the device.
        The key is the full path and file name of each video chunk.
        The value is the md5sum of that file.
        """
        video_list_url = f"{self._device_url}/list_video_files"
        try:
            # Request the URL and read the response
            response = urllib.request.urlopen(video_list_url)
            # Parse the JSON response directly into a dictionary
            video_list = json.load(response)
        except urllib.error.HTTPError as e:
            logging.warning("No JSON list of video files could be found for device %s: %s" % (self._id, str(e)))
            video_list = None
        except json.JSONDecodeError as e:
            logging.warning("Error decoding JSON response for device %s: %s" % (self._id, str(e)))
            video_list = None
        except Exception as e:
            logging.error("An unexpected error occurred for device %s: %s" % (self._id, str(e)))
            video_list = None
        finally:
            return video_list

    def check_sync_status(self):
        """
        Compares the sync status between remote and local video files.
        
        For each video chunk on the remote machine, this function ensures that:
        1. The corresponding video file exists locally.
        2. The local file's MD5 hash matches the remote file's MD5 hash.

        Both remote and local dictionaries should have the following structure:
            
            { 
              'filename1': {'path': 'remote_or_local_path/file1', 'hash': 'md5_hash_string1'},
              'filename2': {'path': 'remote_or_local_path/file2', 'hash': 'md5_hash_string2'},
              ...
            }
        
        Returns:
            tuple: A tuple containing:
              - `number_of_matching_files` (int): The count of files whose hashes match between remote and local.
              - `number_of_total_files` (int): The total number of files listed in the remote dictionary.

        Raises:
            ValueError: If there are issues fetching the remote or local video file lists.
        """
        try:
            # Fetch both remote and local video lists
            hashed_remote_video_list = self.get_video_list_json()  # Remote dictionary
            hashed_local_video_list = list_local_video_files(self._results_dir)  # Local dictionary
        except Exception as e:
            raise ValueError(f"Error fetching video file lists: {e}")

        # Initialize counters
        try:
            number_of_matching_files = 0
            number_of_total_files = len(hashed_remote_video_list)
        except:
            return -1,-1

        # Compare each remote file with the local counterpart
        for filename, remote_info in hashed_remote_video_list.items():
            full_remote_path = remote_info['path']  # Remote file path
            remote_hash = remote_info['hash']  # Remote MD5 hash

            # Check if the filename exists locally
            if filename in hashed_local_video_list:
                local_info = hashed_local_video_list[filename]
                local_hash = local_info['hash']

                # Compare the MD5 hashes
                if remote_hash == local_hash:
                    number_of_matching_files += 1
                else:
                    print(f"Hash mismatch for file: {filename}")
                    print(f"  Remote hash: {remote_hash}")
                    print(f"  Local hash: {local_hash}")
            else:
                print(f"File missing locally: {filename}")
        
        #return {'matching' : number_of_matching_files, 'total' : number_of_total_files }
        return number_of_matching_files, number_of_total_files

    def get_video_list_html(self, index_file="ethoscope_data/results/index.html", generate_first=True):
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

        def _generate_remote_index_html():
            """
            Asks the remote ethoscope to generate an index file.
            """
            full_url = f"{self._device_url}/make_index"
            try:
                response = urllib.request.urlopen(full_url)
                return True
            except urllib.error.HTTPError as e:
                logging.warning(f"No index file could be created for device at {self._device_url}")
                return False

        if generate_first: _generate_remote_index_html()
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
        return False
        #print (target) #/ethoscope_data/results/1107eb4764d24741aa6b49c429db8022/ETHOSCOPE_110/2024-10-18_12-08-19/2024-10-18_12-08-19_1107eb4764d24741aa6b49c429db8022__1280x960@25fps-20q_00001.h264
        #print (self._results_dir) #/ethoscope_data/videos

        # request_url = f"{self._device_url}/rm_static_file/{self._id}"
        # data = {"file": target}
        # data =json.dumps(data)
        # req = urllib.request.Request(url=request_url, data=data, headers={'Content-Type': 'application/json'})
        # _ = urllib.request.urlopen(req, timeout=5)

class GenericBackupWrapper(threading.Thread):
    def __init__(self, results_dir, node_address, video=False):
        '''
        '''
        self.last_backup = ""
        self._BACKUP_DT = 5 * 60  # 5min
        self._results_dir = results_dir
        self._node_address = node_address
        self.backup_status = {}
        self._is_instance_video = video
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._max_threads = 5
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
            

    def initiate_backup_job(self, device_info):
        ''' Start the backup process for the specified device '''
        try:
            dev_id = device_info["id"]
            logging.info("Initiating backup for device %s" % dev_id)

            if self._is_instance_video:
                backup_job = VideoBackupClass(device_info, results_dir=self._results_dir)
            else:
                backup_job = BackupClass(device_info, results_dir=self._results_dir)

            # Prepare backup status
            with self._lock:
                if dev_id not in self.backup_status:
                    self.backup_status[dev_id] = {'name': device_info["name"], 'started': 0, 'ended': 0, 'count': 0, 'progress': {}}
                self.backup_status[dev_id].update({'started': int(time.time()), 'ended': 0, 'processing': True, 'progress': {}})
                self.backup_status[dev_id]['count'] += 1

            # Perform the backup
            for message in backup_job.backup():
                # Update progress info
                with self._lock:
                    self.backup_status[dev_id]['progress'] = json.loads(message)

            # Check sync status and mark as completed
            with self._lock:
                matching, total = backup_job.check_sync_status()
                self.backup_status[dev_id]['synced'] = f"{matching}/{total}"    

                self.backup_status[dev_id]['processing'] = False
                self.backup_status[dev_id]['ended'] = int(time.time())

            return True

        except Exception as e:
            logging.error(traceback.format_exc())
            self.backup_status[dev_id]['processing'] = False
            self.backup_status[dev_id]['ended'] = -1
            self.backup_status[dev_id]['progress'] = {"status": "error", "message": str(e)}
            return False

    def run(self):
        threads = []
        while not self._stop_event.is_set():
            logging.info("Starting backup round")
            active_devices = self.find_devices()
            logging.info(f"Found {len(active_devices)} devices online: "
                        f"{', '.join([dev['id'] for dev in active_devices])}")
            for dev in active_devices:
                if dev['id'] not in self.backup_status:
                    with self._lock:
                        self.backup_status[dev['id']] = {'started': 0, 'ended': 0, 'count': 0, 'progress': {}}

                # Launch a separate thread for each backup job
                t = threading.Thread(target=self.initiate_backup_job, args=(dev,))
                t.daemon = True  # Ensure threads close with the main process
                threads.append(t)
                t.start()

            # Wait for threads to join with a timeout
            for t in threads:
                t.join(timeout=5)  # Set an optional timeout for each thread to avoid blocking indefinitely
            threads = []  # Clear threads list for the next run

            self.last_backup = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logging.info(f"Backup cycle finished at {self.last_backup}")
            self._stop_event.wait(self._BACKUP_DT)

    def update_backup_status(self, device_id, key, value):
        with self._lock:
            if device_id not in self.backup_status:
                self.backup_status[device_id] = {}
            self.backup_status[device_id][key] = value

    def get_backup_status(self):
        with self._lock:
            return json.dumps(self.backup_status, indent=2)

    def stop(self):
        self._stop_event.set()