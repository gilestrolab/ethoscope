
import subprocess
import random
import logging
import traceback

def get_machine_id():
    """
    Reads the machine ID file and returns the value.
    """
    f = open('/etc/machine-id', 'r')
    pi_id = f.readline()
    pi_id = pi_id.strip()
    f.close()
    return pi_id

def get_machine_name():
    """
    Reads the machine NAME file and returns the value.
    """
    try:
        f = open('/etc/machine-name', 'r')
        pi_name = f.readline()
        pi_name = pi_name.strip()
        f.close()
        return pi_name
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