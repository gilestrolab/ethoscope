

import random
import logging
import traceback
import datetime
import os
import re

def pi_version():
    """
    Detect the version of the Raspberry Pi.  Returns either 1, 2 or
    None depending on if it's a Raspberry Pi 1 (model A, B, A+, B+),
    Raspberry Pi 2 (model B+), Raspberry Pi 3 or not a Raspberry Pi.
    """
    # Check /proc/cpuinfo for the Hardware field value.
    # As of September 2016
    # 2708 is pi 1
    # 2709 is pi 2 or 3 depending on revision
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
        return None
    if hardware.group(1) == 'BCM2708':
        # Pi 1
        return 1
    elif hardware.group(1) == 'BCM2709' and '1041' in revision.group(1):
        # Pi 2
        return 2
    elif hardware.group(1) == 'BCM2709' and '2082' in revision.group(1):
        # Pi 3
        return 3
    else:
        # Something else, not a pi.
        return None

def isMachinePI():
    """
    Return True if we are running on a Pi - proper ethoscope
    """
    return pi_version() > 0

def get_machine_info(path):
    """
    Reads the machine NAME file and returns the value.
    """
    try:
        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info
    except Exception as e:
        logging.warning(traceback.format_exc(e))
        return 'Debug-'+str(random.randint(1,100))


def get_commit_version(commit):
    return {"id":str(commit),
            "date":datetime.datetime.utcfromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
def get_version():
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
        
        
    
