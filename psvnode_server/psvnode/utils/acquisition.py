
import subprocess
from time import sleep
from threading import Thread


class Acquisition(Thread):

    def __init__(self, ip, path):
        self.ip = ip
        self.path = path

    def run(self):

        while not self._force_stop:
            sleep(60)
            ad=subprocess.Popen(['rsync','-avz','-e','ssh','psv@'+self.ip+':'+self.path, '/tmp/results/'],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
            stdout_value, stderr_value  = ad._communicate('psv')






    def stop(self):
        if self._exception is not None:
            raise self._exception
        self._force_stop = True

