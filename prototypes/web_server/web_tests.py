__author__ = 'quentin'

import time
from threading import Thread, Lock

class Dummy(object):

    def __init__(self):
        self._is_alive = True
        self._iteration = 0

    @property
    def dummy_variable(self):
        return self._iteration

    def stop(self):
        self._is_alive = False

    def __del__(self):
        self.stop()

    def run(self):
        while self._is_alive:
            time.sleep(1)
            self._iteration +=1
            pass


def test_foo():
    dummy.run()

if __name__ == "__main__":

    dummy = Dummy()
    lock = Lock()



    Thread(target=test_foo, args=(a,lock)).start()

