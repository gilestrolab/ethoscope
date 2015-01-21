__author__ = 'quentin'

import time

class Dummy(object):

    def __init__(self):
        self._is_alive = True

    @property
    def dummy_variable(self):
        return "hello"

    def stop(self):
        self._is_alive = False

    def __del__(self):
        self.stop()

    def run(self):
        while self._is_alive:
            time.sleep(1)
            pass


if __name__ == "__main__":

    dummy = Dummy()
    dummy.run()

