import random
import logging
import traceback
import datetime, time
import os
import re
from uuid import uuid4

def pi_version():
    """
    Detect the version of the Raspberry Pi.  Returns either 1, 2 or
    None depending on if it's a Raspberry Pi 1 (model A, B, A+, B+),
    Raspberry Pi 2 (model B+), Raspberry Pi 3 or not a Raspberry Pi.
    """
    # Check /proc/cpuinfo for the Hardware field value.
    # As of June 2019
    # 2708 is pi 1
    # 2709 is pi 2 or 3 depending on revision
    # 2835 is pi 3
    # Anything else is not a pi.
    
    with open('/proc/cpuinfo', 'r') as infile:
        cpuinfo = infile.read()
    # Match a line like 'Hardware   : BCM2709'
    hardware = re.search('^Hardware\s+:\s+(\w+)$', cpuinfo,
                      flags=re.MULTILINE | re.IGNORECASE)
                      
    revision = re.search('^Revision\s+:\s+(\w+)$', cpuinfo,
                      flags=re.MULTILINE | re.IGNORECASE)
               
    if not hardware:
        # Couldn't find the hardware, assume it isn't a pi.
        return 0
    if hardware.group(1) == 'BCM2708':
        # Pi 1
        return 1
    elif hardware.group(1) == 'BCM2709' and '1041' in revision.group(1):
        # Pi 2
        return 2
    elif hardware.group(1) == 'BCM2709' and '2082' in revision.group(1):
        # Pi 3
        return 3
    elif hardware.group(1) == 'BCM2835' and '2082' in revision.group(1):
        # Pi 3
        return 3
    elif hardware.group(1) == 'BCM2835' and '1041' in revision.group(1):
        # Pi 3
        return 3
    else:
        # Something else, not a pi.
        return 0

def isMachinePI():
    """
    Return True if we are running on a Pi - proper ethoscope
    """
    return pi_version() > 0

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
        cmd = os.popen('/opt/vc/bin/vcgencmd get_camera').read().strip()
        out = dict(x.split('=') for x in cmd.split(' '))
        
        return out["detected"] == out["supported"] == "1"
    
    else:
        return false
    
    
def isExperimental():
    """
    return true if the machine is to be used as experimental
    this mymics a non-PI or a PI without plugged in camera
    to activate, create an empty file called /etc/isexperimental
    """
    return os.path.exists('/etc/isexperimental')
    

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
    
