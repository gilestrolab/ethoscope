
import subprocess
import random
import logging
import traceback

def get_machine_info(path):
    """
    Reads the machine NAME file and returns the value.
    """
    try:
        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info
    except Exception as e:
        logging.error(traceback.format_exc(e))
        return 'Debug-'+str(random.randint(1,100))

def get_version(dir, branch):
    version = subprocess.Popen(['git', 'rev-parse', branch] ,
                                   cwd=dir,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    stdout,stderr = version.communicate()
    return stdout.strip('\n')