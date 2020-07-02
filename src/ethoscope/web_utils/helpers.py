import random
import logging
import traceback
import datetime, time
import os
import re
from uuid import uuid4

def pi_version():
    """
    Detect the version of the Raspberry Pi.
    https://www.raspberrypi.org/documentation/hardware/raspberrypi/revision-codes/README.md
    
    We used to use cat /proc/cpuinfo but as of the 4.9 kernel, all Pis report BCM2835, even those with BCM2836, BCM2837 and BCM2711 processors. 
    You should not use this string to detect the processor. Decode the revision code using the information in the URL above, or simply cat /sys/firmware/devicetree/base/model
    """
    
    info_file = '/sys/firmware/devicetree/base/model'
    
    if os.path.exists(info_file):
    
        with open (info_file, 'r') as revision_input:
            revision_info = revision_input.read().rstrip('\x00')
    
        return revision_info
        
    else:
        return 0

def isMachinePI():
    """
    Return True if we are running on a Pi - proper ethoscope
    """
    return pi_version() != 0

def get_machine_name(path="/etc/machine-name"):
    """
    Reads the machine name
    This file will be present only on a real ethoscope
    When running locally, it will generate a randome name
    """
    
    if os.path.exists(path):
        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info

    else:
        return 'VIRTUASCOPE_' + str(random.randint(100,999))
        
def set_machine_name(id, path="/etc/machine-name"):
    '''
    Takes an id and updates the machine name accordingly in the format
    ETHOSCOPE_id; changes the hostname too.
    
    :param id: integer
    '''
    
    machine_name = "ETHOSCOPE_%03d" % id
    try:
        with open(path, 'w') as f:
            f.write(machine_name)
        logging.warning("Wrote new information in file: %s" % path)
        
        with open("/etc/hostname", 'w') as f:
            f.write(machine_name)
        logging.warning("Changed the machine hostname to: %s" % machine_name)
        

    except:
        raise

def set_machine_id(id, path="/etc/machine-id"):
    '''
    Takes an id and updates the machine id accordingly in the format
    0ID-UUID to make a 32 bytes string
    
    :param id: integer
    '''

    new_uuid = "%03d" % id + uuid4().hex[3:]
    
    try:
        with open(path, 'w') as f:
            f.write(new_uuid)
        logging.warning("Wrote new information in file: %s" % path)
            
    except:
        raise

def get_WIFI(path="/etc/netctl/wlan"):
    """
    """
    if os.path.exists(path):
        with open(path,'r') as f:
            wlan_settings = f.readlines()
        
        d = {}
        for line in wlan_settings:
            if "=" in line:
                d[ line.strip().split("=")[0] ] =  line.strip().split("=")[1]
        return d

    else:
        return {'error' : 'No WIFI Settings were found in path %s' % path}
    

def set_WIFI(ssid="ETHOSCOPE_WIFI", wpakey="ETHOSCOPE_1234", path="/etc/netctl/wlan"):
    """
    """

    wlan_settings = '''Description=ethoscope_wifi network
Interface=wlan0
Connection=wireless
Security=wpa
IP=dhcp
TimeoutDHCP=60
ESSID=%s
Key=%s
''' % (ssid, wpakey)
            
    try:
        with open(path, 'w') as f:
            f.write(wlan_settings)
        logging.warning("Wrote new information in file: %s" % path)
    except:
        raise
            
    

def set_etc_hostname(ip_address, nodename = "node", path="/etc/hosts"):
    '''
    Updates the settings in /etc/hosts to match the given IP address
    '''
    
    try:
        with open(path, 'w') as f:
            f.write("127.0.0.1\tlocalhost\n")
            f.write("%s\t%s\n" % (ip_address, nodename))
        logging.warning("Wrote new information in file: %s" % path)
    except:
        raise 

def get_commit_version(commit):
    '''
    '''
    return {"id":str(commit),
            "date":datetime.datetime.utcfromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
def get_git_version():
    '''
    return the current git version
    '''
    
    import git
    wd = os.getcwd()

    while wd != "/":
        try:
            repo = git.Repo(wd)
            commit = repo.commit()
            return get_commit_version(commit)

        except git.InvalidGitRepositoryError:
            wd = os.path.dirname(wd)
            
    raise Exception("Not in a git Tree")

def file_in_dir_r(file, dir):
    file_dir_path = os.path.dirname(file).rstrip("//")
    dir_path = dir.rstrip("//")
    if file_dir_path == dir_path:
        return True
    elif file_dir_path == "":
        return False
    else:
        return file_in_dir_r(file_dir_path, dir_path)

def cpu_serial():
    """
    on a rPI, return a unique identifier of the CPU
    """
    serial = ''
    
    if isMachinePI():
        with open('/proc/cpuinfo', 'r') as infile:
            cpuinfo = infile.read()
        # Match a line like 'Serial   : xxxxx'
        serial = re.search('^Serial\s+:\s+(\w+)$', cpuinfo,
                          flags=re.MULTILINE | re.IGNORECASE)
        
        serial = serial.group(1)
        
    return serial
        
        
def hasPiCamera():
    """
    return True if a piCamera is supported and detected
    """
    if isMachinePI():
       with os.popen('/opt/vc/bin/vcgencmd get_camera') as cmd:
           out_cmd = cmd.read().strip()
       out = dict(x.split('=') for x in out_cmd.split(' '))
       
       return out["detected"] == out["supported"] == "1"

    else:
        return False
        
def getPiCameraVersion():
    """
    If a PiCamera is connected, returns the model

    #PINoIR v1
    #{'IFD0.Model': 'RP_ov5647', 'IFD0.Make': 'RaspberryPi'}
    #PINoIR v2
    #{'IFD0.Model': 'RP_imx219', 'IFD0.Make': 'RaspberryPi'}
    
    """
    
    known_versions = {'RP_ov5647': 'PINoIR 1', 'RP_imx219': 'PINoIR 2'}
    
    picamera_info_file = '/etc/picamera-version'
    
    if hasPiCamera():

        try:
            with open(picamera_info_file, 'r') as infile:
                camera_info = eval(infile.read())
            
            camera_info['version'] = known_versions[ camera_info['IFD0.Model'] ]
            
        except:
            camera_info = "This is a new ethoscope. Run tracking once to detect the camera module"
            
        return camera_info
    else:
        
        return False

def isSuperscope():
    """
    The following lsusb device
    Bus 001 Device 003: ID 05a3:9230 ARC International Camera
    is the one we currently use for the SuperScope
    https://www.amazon.co.uk/gp/product/B07R7JXV35/ref=ppx_yo_dt_b_asin_title_o06_s00?ie=UTF8&psc=1
    
    Eventually we will include the new rPI camera too
    https://uk.farnell.com/raspberry-pi/rpi-hq-camera/rpi-high-quality-camera-12-3-mp/dp/3381605
    
    """
    
    pass
    
    
def isExperimental(new_value=None):
    """
    return true if the machine is to be used as experimental
    this mymics a non-PI or a PI without plugged in camera
    to activate, create an empty file called /etc/isexperimental
    """
    filename = '/etc/isexperimental'
    current_value = os.path.exists(filename)
    
    if new_value == None:
        return current_value
        
    if new_value == True and current_value == False:
        #create file
        with open(filename, mode='w'):
            logging.warning("Created a new empty file in %s. The machine is now experimental." % filename)
    
    elif new_value == False and current_value == True:
        #delete file
        os.remove(filename)
        logging.warning("Removed file %s. The machine is not experimental." % filename)
        
    
    

def get_machine_id(path="/etc/machine-id"):
    """
    Reads the machine ID
    This file should be present on any linux installation because, when missing, it is automatically generated by the OS
    """
    
    with open(path,'r') as f:
        info = f.readline().rstrip()
    return info


def get_etc_hostnames():
    """
    Parses /etc/hosts file and returns all the hostnames in a dictionary.
    """
    with open('/etc/hosts', 'r') as f:
        hostlines = f.readlines()
        
    hostlines = [line.strip() for line in hostlines
                 if not line.startswith('#') and line.strip() != '']
    hosts = {}
    for line in hostlines:
        entries = line.split("#")[0].split()
        hosts [ entries[1] ] = entries[0]

    return hosts
    
def get_core_temperature():
    """
    Returns the internal core temperature in degrees celsius
    """
    if isMachinePI():
        try:
            with os.popen("/opt/vc/bin/vcgencmd measure_temp") as df:
                temp = float("".join(filter(lambda d: str.isdigit(d) or d == '.', df.read())))
            return temp
        except:
            return 0
    else: 
        return 0

def get_SD_CARD_AGE():
    """
    Given the machine_id file is created at the first boot, it assumes the SD card is as old as the file itself
    :return: timestamp of the card
    """
    try:
        return time.time() - os.path.getmtime("/etc/machine-id")
        
    except:
        return
        
        
def get_partition_infos():
    """
    Returns information about mounted partition and their free availble space
    """
    try:
        with os.popen('df -Th') as df:
            df_info = df.read().strip().split('\n')
        keys = df_info[0]
        values = df_info[1:]
        
        return [dict([(key, value) for key, value in zip(keys.split(), line.split())]) for line in values]
        
    except:
        return
    
def set_datetime(time_on_node):
    """
    Set date and time on the PI
    time_on_node is the time to be set in the datetime format
    """
    
    cmd = 'date -s "%s"' % time_on_node.strftime("%d %b %Y %H:%M:%S") # 26 Jun 2020 15:04:25
    
    try:
        with os.popen(cmd, 'r') as c:
            c.read()
        
        return True
        
    except:
        return False
