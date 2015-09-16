
import subprocess
import random
import logging
import traceback

def get_machine_info(path):
    """
    Reads the machine NAME file and returns the value.
    """
    log = logging.Logger("dummy")
    try:

        with open(path,'r') as f:
            info = f.readline().rstrip()
        return info
    except Exception as e:
        log.warning(traceback.format_exc(e))
        return 'Debug-'+str(random.randint(1,100))

#
# def get_version(dir, branch):
#     version = subprocess.Popen(['git', 'rev-parse', branch] ,
#                                    cwd=dir,
#                                    stdout=subprocess.PIPE,
#                                    stderr=subprocess.PIPE)
#     stdout,stderr = version.communicate()
#     commit_id = stdout.strip('\n')
#
#     version_date = subprocess.Popen(['git', 'show', '-s', '--format=%ci'] ,
#                                    cwd=dir,
#                                    stdout=subprocess.PIPE,
#                                    stderr=subprocess.PIPE)
#     stdout,stderr = version_date.communicate()
#
#     commit_date = stdout.strip('\n')
#
#     return {"id":commit_id, "date":commit_date}