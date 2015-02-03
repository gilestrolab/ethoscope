import urllib2
import json
import time
import pexpect

from threading import Thread


class Acquisition(Thread):

    def __init__(self, url, id):
        self.url = url
        self.id = id
        self._force_stop = False
        self.timeout = 10

        super(Acquisition, self).__init__()

    def run(self):

        last_round = time.time() + self.timeout
        while not self._force_stop:

            time.sleep(0.5)
            t = time.time()

            if t - last_round > self.timeout:
                req = urllib2.Request(url=self.url+':9000/data/'+self.id+'/result_files')
                f = urllib2.urlopen(req)
                message = f.read()
                if message:
                    data = json.loads(message)

                if data['result_files'][0] is not None:
                    command = 'rsync -avz -e ssh psv@'+self.url[7:]+':'+data['result_files'][0]+' /tmp/results/'

                    ad=pexpect.spawn(command)
                    ad.expect('password:')
                    ad.sendline('psv')

                    print command
                    last_round = t





    def stop(self):
        self._force_stop = True

