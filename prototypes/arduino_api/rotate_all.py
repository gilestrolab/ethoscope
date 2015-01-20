__author__ = 'quentin'

from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface


import logging
logging.basicConfig(filename=('/tmp/%s.log' % __file__), level=logging.DEBUG)

sdi = SleepDepriverInterface()
for i in range(31):
    sdi.deprive(i)