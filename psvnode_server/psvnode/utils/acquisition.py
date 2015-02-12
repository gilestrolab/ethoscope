import urllib2
import json
import time
import pexpect
import logging
import subprocess

from threading import Thread

class Acquisition(Thread):

    def __init__(self, url, id):
        self.url = url
        self.id = id
        self._force_stop = False
        self.timeout = 10
        self._info={"log_file":"/tmp/node.log"}

        logging.basicConfig(filename=self._info['log_file'], level=logging.INFO)

        logger = logging.getLogger()
        logger.handlers[0].stream.close()
        logger.removeHandler(logger.handlers[0])

        file_handler = logging.FileHandler(self._info["log_file"])
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(filename)s, %(lineno)d, %(funcName)s: %(message)s")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        super(Acquisition, self).__init__()

    def run(self):

        last_round = time.time() + self.timeout
        while not self._force_stop:

            time.sleep(0.5)
            t = time.time()

            if t - last_round > self.timeout:
                logging.info("Recovering data from device "+self.url+" : "+self.id)
                self.sync_data()
                last_round = t


    def stop(self):
        self._force_stop = True


    def sync_data(self):
        req = urllib2.Request(url=self.url+':9000/data/'+self.id)
        f = urllib2.urlopen(req)
        message = f.read()
        if message:
            data = json.loads(message)
            result_files = data['monitor_info']['result_files']
            if result_files is not None:
                for result_file in result_files:
                    try:
                        # FIXME change /tmp route for something like data/+self.id+'/'+datetime.datetime()+'/'
                        command = ['rsync', '-avze','ssh','psv@'+self.url[7:]+':'+result_file, '/tmp/results']

                        ssh_sync = subprocess.Popen(command, shell=False, stdout=subprocess.PIPE)

                    except Exception as e:
                        logging.error("Can't syncronize "+result_file+":")
                        logging.error(e)