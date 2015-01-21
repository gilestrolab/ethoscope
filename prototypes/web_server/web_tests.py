__author__ = 'quentin'

import time
from pysolovideo.web_utils.control_thread import ControlThread

if __name__ == "__main__":

    track = ControlThread()
    track.start()
    try:
        while True:
            time.sleep(2)
            print (track.dummy_variable)
    finally:
        track.stop()
        

