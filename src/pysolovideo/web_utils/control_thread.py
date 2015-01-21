from threading import Thread
from pysolovideo.tracking.monitor import Monitor

class ControlThread(Thread):

    def __init__(self, *args, **kwargs):

        self.__monit = Monitor(*args, **kwargs)

        super(ControlThread, self).__init__()

    def run(self, **kwarg):
        self.__monit.run()

    def stop(self):
        self.__monit.stop()

    @property
    def last_frame(self):
        return self.__monit.last_frame

    @property
    def data_history(self):
        return self.__monit.data_history