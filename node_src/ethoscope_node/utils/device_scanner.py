from threading import Thread
import urllib.request, urllib.error, urllib.parse
import os
import datetime
import json
import time
import logging
import traceback
from functools import wraps
import socket
from zeroconf import ServiceBrowser, Zeroconf, IPVersion

from ethoscope_node.utils.etho_db import ExperimentalDB
from ethoscope_node.utils.mysql_backup import db_diff

STREAMING_PORT = 8887
ETHOSCOPE_PORT = 9000

class ScanException(Exception):
    pass


def retry(ExceptionToCheck, tries=4, delay=3, backoff=2, logger=None):
    """Retry calling the decorated function using an exponential backoff.

    http://www.saltycrane.com/blog/2009/11/trying-out-retry-decorator-python/
    original from: http://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    """
    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return f_retry
    return deco_retry


class Device(Thread):

    @retry(ScanException, tries=3, delay=1, backoff=1)
    def _get_json(self, url, timeout=10, post_data=None):

        try:
            req = urllib.request.Request(url, data=post_data, headers={'Content-Type': 'application/json'})
            f = urllib.request.urlopen(req, timeout=timeout)
            message = f.read()
            
            if not message:
                # logging.error("URL error whist scanning url: %s. No message back." % self._id_url)
                raise ScanException("No message back")
                
            try:
                resp = json.loads(message)
                return resp
                
            except ValueError:
                # logging.error("Could not parse response from %s as JSON object" % self._id_url)
                raise ScanException("Could not parse Json object")
    
        except urllib.error.HTTPError as e:
           raise ScanException("Error" + str(e.code))
            #return e
        
        except urllib.error.URLError as e:
           raise ScanException("Error" + str(e.reason))
            #return e
        
        except Exception as e:
           raise ScanException("Unexpected error" + str(e))


class Sensor(Device):
    """
    """
    def __init__(self, ip, port = 80, refresh_period = 5, results_dir = ""):
        self._ip = ip
        self._port = port
        
        self._data_url = "http://%s:%i/" % (ip, port)
        self._id_url = "http://%s:%i/id" % (ip, port)
        self._post_url = "http://%s:%i/set" % (ip, port)

        self._info = {"status": "offline"}
        self._id = ""
        self._reset_info()

        self._is_online = True
        self._skip_scanning = False
        self._refresh_period = refresh_period
        self._update_info()
        super(Sensor,self).__init__()


    def run(self):
        '''
        while the device is active (i.e. online and communicating)
        interrogates periodically on the status and info
        '''
        
        last_refresh = 0
        while self._is_online:
            time.sleep(.2)
            if time.time() - last_refresh > self._refresh_period:

                if not self._skip_scanning:
                    self._update_info()
                else:
                    self._reset_info()
                last_refresh = time.time()

    def _update_id(self):
        """
        """
        if self._skip_scanning:
            raise ScanException("Not scanning this ip (%s)." % self._ip)

        old_id = self._id
        resp = self._get_json(self._id_url)
        self._id = resp['id']
        if self._id != old_id:
            if old_id:
                logging.warning("Device id changed at %s. %s ===> %s" % (self._ip, old_id, self._id))
            self._reset_info()

        self._info["ip"] = self._ip
        self._id = resp['id']

    def set(self, post_data, usejson=False):
        """
        Set remote variables 
        data is a dict e.g. {"location" : "Incubator_1A", "sensor_name" : "etho_sensor1A"} 
        set key to value
        Value can be char[20]
        """
        
        if usejson:
            
            #converts the dictionary to proper json
            args = json.dumps(post_data)
            out = self._get_json( url = self._post_url, timeout = 10, post_data = args)

        else:

            args = urllib.parse.urlencode(post_data).encode("utf-8")
            # converts the dictionary to something like the following
            # b'location=Incubator_1A&sensor_name=etho_sensor1A'
            
            # use a normal POST routine
            req = urllib.request.Request( url = self._post_url, data=args )
            out = urllib.request.urlopen(req, timeout=3)
        
        self._update_info()
        
        return out
        

    def _reset_info(self):
        '''
        This is called whenever the device goes offline
        '''
        self._info['status'] = "offline"
        self._info['ip'] = "offline"

    def _update_info(self):
        '''
        '''
        try:
            self._update_id()
        except ScanException:
            self._reset_info()
            return
        
        try:
            resp = self._get_json(self._data_url)
            self._info.update(resp)
            self._info['status'] = 'online'
        except ScanException:
            pass

    def ip(self):
        return self._ip
        
    def id(self):
        return self._id
        
    def info(self):
        return self._info

class Ethoscope(Device):
    _ethoscope_db_credentials = {"user": "ethoscope",
                                "passwd": "ethoscope",
                                "db":"ethoscope_db"}

    _remote_pages = {
            'id' : "id",
            'videofiles' :  "data/listfiles/video",
            'stream' : "stream.mjpg",
            'user_options' : "user_options",
            'log' : "data/log",
            'static' : "static",
            'controls' : "controls",
            'machine_info' : "machine",
            'update' : "update",
            'dumpdb' : "dumpSQLdb"
            }
    
    # instruction : ['when it is allowed']
    _allowed_instructions_status = { "stream": ["stopped"],
                                     "start": ["stopped"],
                                     "start_record": ["stopped"],
                                     "stop": ["streaming", "running", "recording"],
                                     "poweroff": ["stopped"],
                                     "reboot" : ["stopped"],
                                     "restart" : ["stopped"],
                                     "dumpdb" : ["stopped"],
                                     "offline": [],
                                     "convertvideos" : ["stopped"]
                                     }

    def __init__(self, ip, port = ETHOSCOPE_PORT, refresh_period = 5, results_dir = "/ethoscope_data/results"):
        '''
        Initialises the info gathering and controlling activity of a Device by the node
        The server will interrogate the status of the device with frequency of refresh_period
        '''
        
        self._results_dir = results_dir
        self._ip = ip
        self._port = port
        self._id_url = "http://%s:%i/%s" % (ip, port, self._remote_pages['id'])
        self._is_online = True
        self._skip_scanning = False
        self._refresh_period = refresh_period

        self._info = {"status": "offline"}
        self._id = ""
        self._reset_info()
        self._info['ping'] = 0
        
        self._edb = ExperimentalDB()
        self._last_db_info = time.time()

        super(Ethoscope,self).__init__()
        


    def run(self):
        '''
        while the device is active (i.e. online and communicating)
        interrogates periodically on the status and info
        '''
        
        last_refresh = 0
        while self._is_online:
            time.sleep(.2)
            if time.time() - last_refresh > self._refresh_period:

                if not self._skip_scanning:
                    self._update_info()
                else:
                    self._reset_info()
                last_refresh = time.time()

    def dumpSQLdb(self):
        
        post_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['dumpdb'], self._id)
        
        return self._get_json(post_url, 3)
        

    def send_instruction(self, instruction, post_data):
        
        post_url = "http://%s:%i/%s/%s/%s" % (self._ip, self._port, self._remote_pages['controls'], self._id, instruction)
        self._check_instructions_status(instruction)

        # we do not expect any data back when device is powered off.
        if instruction in ["poweroff", "reboot", "restart"]:
            try:
                self._get_json(post_url, 3, post_data)
            except ScanException:
                pass

        else:
            self._get_json(post_url, 3, post_data)
            
        self._update_info()
        
    def send_settings(self, post_data):
        post_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['update'], self._id)
        haschanged = self._get_json(post_url, 3, post_data)
        self._update_info()
        return haschanged

    def _check_instructions_status(self, instruction):
        self._update_info()
        status = self._info["status"]

        try:
            allowed_inst = self._allowed_instructions_status[instruction]
        except KeyError:
            raise KeyError("Instruction %s is not allowed" % instruction)

        if status not in allowed_inst:
            raise Exception("You cannot send the instruction '%s' to a device in status %s" % (instruction, status))

    def ip(self):
        return self._ip
        
    def id(self):
        return self._id
        
    def info(self):
        return self._info

    def machine_info(self):
        '''
        Retrieves private machine info from the ethoscope
        This is used to check if the ethoscope is a new installation
        URL http://<ip>:<port>/machine/<id>
        '''
        if self._id:
            machine_info_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['machine_info'], self._id)
            out = self._get_json(machine_info_url)
            return out
        else:
            return {}
        

    def skip_scanning(self, value):
        self._skip_scanning = value

    def videofiles(self):
        '''
        Return a list of file videos available on the ethoscope or virtuascope
        '''
        videofiles_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['videofiles'], self._id)
        out = self._get_json(videofiles_url)
        return out


    def relay_stream(self):
        '''
        The node uses this function to relay the stream of images from the device to the node client
        '''
        
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((self._ip, STREAMING_PORT))

        client_socket.settimeout(5)
        client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        
        rfile = client_socket.makefile('rb')

        stream_bytes = b' '

        while True:
            
            stream_bytes += rfile.read(1024)
            
            if len(stream_bytes) == 0:
                break

            first = stream_bytes.find(b'\xff\xd8')
            last = stream_bytes.find(b'\xff\xd9')
            
            if first != -1 and last != -1:

                jpg = stream_bytes[first:last+2]
                stream_bytes = stream_bytes[last+2:]

                yield b'--frame\r\n'
                yield b'X-Timestamp: %s\r\n' % str(time.time()).encode()
                yield b'Content-Length: %s\r\n' % str(len(jpg)).encode()
                yield b'Content-Type: image/jpeg\r\n\r\n' 
                yield jpg
                yield b'\r\n'

        rfile.close()
        client_socket.close()

    def user_options(self):
        """
        """
        user_options_url= "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['user_options'], self._id)
        try:
            out = self._get_json(user_options_url)
            return out
        except:
            return

    def get_log(self):
        log_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['log'], self._id)
        out = self._get_json(log_url)
        return out

    def last_image(self):
        """
        Collects the last drawn image fromt the device
        TODO: on the device side, this should not rely on an actuale image file but be fished from memory
        """
        # we return none if the device is not in a stoppable status (e.g. running, recording)
        if self._info["status"] not in self._allowed_instructions_status["stop"]:
            return None
        try:
            img_path = self._info["last_drawn_img"]
        except KeyError:
            raise KeyError("Cannot find last image for device %s" % self._id)

        img_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['static'], img_path)
        try:
            return urllib.request.urlopen(img_url,timeout=5)
        except  urllib.error.HTTPError:
            logging.error("Could not get image for ip = %s (id = %s)" % (self._ip, self._id))
            raise Exception("Could not get image for ip = %s (id = %s)" % (self._ip, self._id))

    def dbg_img(self):
        try:
            img_path = self._info["dbg_img"]
        except KeyError:
            raise KeyError("Cannot find dbg img path for device %s" % self._id)

        img_url = "http://%s:%i/%s/%s" % (self._ip, self._port, self._remote_pages['static'], img_path)

        try:
            file_like = urllib.request.urlopen(img_url)
            return file_like

        except Exception as e:
            logging.warning(traceback.format_exc())

    def _update_id(self):
        """
        """
        if self._skip_scanning:
            raise ScanException("Not scanning this ip (%s)." % self._ip)

        old_id = self._id
        resp = self._get_json(self._id_url)
        if not resp:
            # Ethoscope is not reachable
            return 0
        self._id = resp['id']
        
        if self._id != old_id and old_id != "":
            logging.warning("Device id changed at %s. %s ===> %s" % (self._ip, old_id, self._id))
            self._reset_info()

        self._info["ip"] = self._ip
        self._id = resp['id']


    def _reset_info(self):
        '''
        This is called whenever the device goes offline or when it is first added
        '''
        self._info['status'] = "offline"
        

    def _update_info(self):
        '''
        '''

        previous_status = self._info['status']

        self._info['ping'] += 1

        try:
            if not self._id:
                self._update_id()
            
            data_url = "http://%s:%i/data/%s" % (self._ip, self._port, self._id)
            new_info = self._get_json(data_url)

            new_status = new_info['status']
            self._info.update(new_info)

            backup_path = self._make_backup_path()
            self._info.update(backup_path)

        except ScanException as e:
            logging.warning(f"error while scanning: {e}")
            logging.warning(f"ethoscope not reachable, previous state {previous_status}")

            # first check if the problem is that we don't know what the ID is.
            # self._update_id()
            new_status = 'unreached'

            if 'run_id' in self._info['experimental_info']:
                run_id = self._info['experimental_info']['run_id']
                self._edb.flagProblem( run_id = run_id, message = "unreached" ) #ethoscope went offline while running
                if previous_status == 'running'      and new_status == 'unreached': self._edb.updateEthoscopes(ethoscope_id = self._id, status="unreached")
            else:
                if previous_status == 'stopped'      and new_status == 'unreached': self._edb.updateEthoscopes(ethoscope_id = self._id, status="offline")

            self._reset_info()
            return


        # Appearing online 
        if previous_status == "offline" and new_status != "offline" and "ETHOSCOPE_OOO" not in self._info['name'].upper():

            mi = self.machine_info()

            if 'kernel' in mi.keys():
                machine_info = "%s on pi%s" % (mi['kernel'], mi['pi_version'])
            else:
                machine_info = ""

            # #We add the device to the database or update its record but only if it is not a 000 device
            self._edb.updateEthoscopes(ethoscope_id = self._id, ethoscope_name = self._info['name'], last_ip = self._ip, machineinfo = machine_info)
        


        #if ethoscope is online and returning data

        if 'name' in self._info['experimental_info']:
            user_name = self._info['experimental_info']['name']
            location = self._info['experimental_info']['location']
            
        else:
            user_name = ""
            location = ""

        if 'run_id' in self._info['experimental_info']:
            run_id = self._info['experimental_info']['run_id']
            
            #TODO
            user_uid = "" 
            send_alerts = True

            db_file_name = self._info['backup_path']
            
            if previous_status == 'stopped'      and new_status == 'initialising': pass #started tracking, looking for targets, no need to log this step
            if previous_status == 'initialising' and new_status == 'running': self._edb.addRun( run_id = run_id, experiment_type = "tracking", ethoscope_name = self._info['name'], ethoscope_id = self._id, username = user_name, user_id = user_uid, location = location, alert = send_alerts, comments = "", experimental_data = db_file_name ) #tracking started succesfully
            if previous_status == 'initialising' and new_status == 'stopping': self._edb.flagProblem( run_id = run_id, message = "self-stopped" )
            if previous_status == 'running'      and new_status == 'stopped': self._edb.stopRun( run_id = run_id ) #ethoscope manually stopped
            #not sure the unreach ones actually ever happen
            if previous_status == 'running'      and new_status == 'unreached': self._edb.updateEthoscopes(ethoscope_id = self._id, status="unreached")
            if previous_status == 'stopped'      and new_status == 'unreached': self._edb.updateEthoscopes(ethoscope_id = self._id, status="offline")
   
            #if previous_status == 'running'      and new_status == 'unreached': self._edb.flagProblem( run_id = run_id, message = "unreached" ) #ethoscope went offline during tracking!


        # gather info on the current backup if possible
        try:
            if time.time() - self._last_db_info > 60:
                dbd = db_diff(self._info["db_name"], self._ip, self._info['backup_path'])
                self._info['backup_status'] = dbd.compare_databases()
                self._last_db_info = time.time()

        except:
            self._info['backup_status'] = "N/A"


    def _make_backup_path(self,  timeout=30):
        '''
        '''
        
        try:
            import mysql.connector
            device_id = self._info["id"]
            device_name = self._info["name"]
            self._ethoscope_db_credentials["db"] = self._info["db_name"]
            
            com = "SELECT value from METADATA WHERE field = 'date_time'"

            mysql_db = mysql.connector.connect(host=self._ip,
                                               connect_timeout=timeout,
                                               **self._ethoscope_db_credentials,
                                               buffered=True)
            cur = mysql_db.cursor()
            cur.execute(com)
            query = [c for c in cur]
            timestamp = float(query[0][0])
            mysql_db.close()
            date_time = datetime.datetime.fromtimestamp(timestamp)
            formatted_time = date_time.strftime('%Y-%m-%d_%H-%M-%S')
            file_name = "%s_%s.db" % (formatted_time, device_id)
            output_db_file = os.path.join(self._results_dir,
                                          device_id,
                                          device_name,
                                          formatted_time,
                                          file_name
                                          )

        except Exception as e:
            #logging.error("Could not generate backup path for device. Probably a MySQL issue")
            #logging.error(traceback.format_exc())
            return {"backup_path": "None"}

        return {"backup_path": output_db_file}

    def stop(self):
        self._is_online = False

class DeviceScanner():
    """
    Uses zeroconf (aka Bonjour, aka Avahi etc) to passively listen for ethoscope devices registering themselves on the network.
    From: https://github.com/jstasiak/python-zeroconf
    """
    #avahi requires .local but some routers may have .lan
    #TODO: check if this is going to be a problem
    
    _suffix = ".local" 
    _service_type = "_device._tcp.local." 
    _device_type = "device"

    
    def __init__(self, device_refresh_period = 5, deviceClass=Device):
        self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self.devices = []
        self.device_refresh_period = device_refresh_period
        self._Device = deviceClass
        
    def start(self):
        # Use self as the listener class because I have add_service and remove_service methods
        self.browser = ServiceBrowser(self._zeroconf, self._service_type, self)
        
    def stop(self):
        self._zeroconf.close()

    def get_all_devices_info(self):
        '''
        Returns a dictionary in which each entry has key of device_id
        '''
        out = {}

        for device in self.devices:
            out[device.id()] = device.info()
        return out
        
    def get_device(self, id):
        """
        return info in memory for given device
        :param id: The ID of the device
        :return: the device instance
        """
        
        for device in self.devices:
            if device.id()==id:
                return device
        #if not found return none
        return
        # Not found, so produce an error
        #raise KeyError("No such %s device: %s" % (self._device_type, id) )
        
    def add (self, ip, port, name=None, device_id=None, zcinfo=None):
        """
        Adds a device to the list
        """
        
        device = self._Device(ip, port=port, refresh_period = self.device_refresh_period, results_dir = self.results_dir )
        if name: device.zeroconf_name = name
        
        device.start()
        
        if not device_id: device_id = device.id()
         
        self.devices.append(device)

        logging.info("New %s added with name = %s, id = %s at IP = %s:%s" % (self._device_type, name, device.id(), ip, port))

        
    def add_service(self, zeroconf, type, name):
        """
        Method required to be a Zeroconf listener. Called by Zeroconf when a "_device._tcp" service
        is registered on the network. Don't call directly.
        
        sample values:
        type = '_device._tcp.local.'
        name = 'DEVICE000._device._tcp.local.'
        """
        #logging.info("Got info about device %s" % name)

        
        try:
            info = zeroconf.get_service_info(type, name)

            if info:
                # this is no longer working with version of zeroconf 0.27+ - see https://github.com/home-assistant/core/pull/36277
                #ip = socket.inet_ntoa(info.address) 
                ip = socket.inet_ntoa(info.addresses[0])
                port = info.port
                self.add( ip, port, name, zcinfo = info )
                
        except Exception as error:
            logging.error("Exception trying to add zeroconf service '"+name+"' of type '"+type+"': "+str(error))
            
    def remove_service(self, zeroconf, type, name):
        """
        Method required to be a Zeroconf listener. Called by Zeroconf when a "_ethoscope._tcp" service
        unregisters itself. Don't call directly.
        """
        for device in self.devices:
            if device.zeroconf_name == name:
                logging.info("%s with id = %s has gone down" % (self._device_type.capitalize(), device.id() ))
                
                #we do not remove devices from the list when they go down so that keep a record of them in the node
                #self.devices.remove(device)
                return

    def update_service(self, zconf, typ, name):
        """
        Callback when a service is updated.
        """
        pass


class EthoscopeScanner(DeviceScanner):
    """
    Ethoscope specific Scanner
    """
    _suffix = ".local" 
    _service_type = "_ethoscope._tcp.local." 
    _device_type = "ethoscope"

    
    def __init__(self, device_refresh_period = 5, results_dir="/ethoscope_data/results", deviceClass=Ethoscope):
        self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self.devices = []
        self.device_refresh_period = device_refresh_period
        self.results_dir = results_dir
        self._Device = deviceClass
        self._edb = ExperimentalDB()
        
        self.timestarted = datetime.datetime.now()

    def _get_last_backup_time(self, device):
        try:
            backup_path = device.info()["backup_path"]
            time_since_backup = time.time() - os.path.getmtime(backup_path)
            return time_since_backup
        except OSError:
            return
        except KeyError:
            return
        except Exception as e:
            logging.error(traceback.format_exc())
            return

    def get_all_devices_info(self):
        '''
        Returns a dictionary in which each entry has key of device_id
        '''
        out = {}

        # First we generate a dictionary of active ethoscopes in the database. In this way we account for those that are in use but are actually offline
        all_known_ethoscopes = self._edb.getEthoscope ('all', asdict=True)
        
        for dv_db in all_known_ethoscopes:
            ethoscope = all_known_ethoscopes[dv_db]
            if ethoscope['active'] == 1:
                out[ethoscope['ethoscope_id']] = { 'name': ethoscope['ethoscope_name'], 
                                                   'id': ethoscope['ethoscope_id'],
                                                   'status' : "offline",
                                                   'ip' : ethoscope['last_ip'],
                                                   'time' : ethoscope['last_seen']}

        # Then we update that list with those ethoscopes that are actually online
        for device in self.devices:
            if device.name != "ETHOSCOPE_000":
                out[device.id()] = device.info()
                out[device.id()]["time_since_backup"] = self._get_last_backup_time(device)
            else:
                out[device.name] = device.info()
                
        return out

    def add (self, ip, port=ETHOSCOPE_PORT, name=None, device_id=None, zcinfo=None):
        """
        Add an ethoscope to the list
        TODO: Can be called manually or by zeroconf - it would be good to recognise which case we are in
        """
        
        #initialised the device and start it
        device = self._Device(ip, port=port, refresh_period = self.device_refresh_period, results_dir = self.results_dir )
        device.zeroconf_name = name
        device.start()

        #device_id = zcinfo.properties[b'id']
        #device_id = name.split("-")[1].split(".")[0]

        self.devices.append(device)
        logging.info("New %s added with name = %s at IP = %s:%s" % (self._device_type, name, ip, port))

    
    def retire_device (self, id, active=0):
        """
        Retire the device by changing its status to inactive in the database
        """
        self._edb.updateEthoscopes(ethoscope_id = id, active = active)
        new_data = self._edb.getEthoscope(id, asdict=True)[id]
        return {'id' : new_data['ethoscope_id'], 'active' : new_data['active']}
        
class SensorScanner(DeviceScanner):
    """
    Sensor specific scanner
    """
    _suffix = ".local" 
    _service_type = "_sensor._tcp.local." 
    _device_type = "sensor"
    
    def __init__(self, device_refresh_period = 60, deviceClass=Sensor):
        self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self.devices = []
        self.device_refresh_period = device_refresh_period
        self._Device = deviceClass
        self.results_dir = ""
        super(SensorScanner, self).__init__(device_refresh_period=self.device_refresh_period, deviceClass=self._Device)
        
    def start(self):
        # Use self as the listener class because I have add_service and remove_service methods
        self.browser = ServiceBrowser(self._zeroconf, self._service_type, self)
        
    def stop(self):
        self._zeroconf.close()
