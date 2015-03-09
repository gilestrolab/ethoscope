
import subprocess

def get_machine_id():
    """
    Reads the machine ID file and returns the value.
    """
    f = open('/etc/machine-id', 'r')
    pi_id = f.readline()
    pi_id = pi_id.strip()
    f.close()
    return pi_id


def get_version(dir, branch):
    version = subprocess.Popen(['git', 'rev-parse', branch] ,
                                   cwd=dir,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    stdout,stderr = version.communicate()
    return stdout.strip('\n')