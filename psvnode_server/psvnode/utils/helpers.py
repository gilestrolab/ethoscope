import subprocess
import os
def get_version(dir, branch):
    version = subprocess.Popen(['git', 'rev-parse', branch],
                                   cwd=dir,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    stdout, stderr = version.communicate()
    return stdout.strip('\n')

def which(program):
    # verbatim from
    # http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None