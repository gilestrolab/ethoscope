import subprocess
def get_version(dir, branch):
    version = subprocess.Popen(['git', 'rev-parse', branch],
                                   cwd=dir,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
    stdout, stderr = version.communicate()
    return stdout