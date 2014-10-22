__author__ = 'quentin'

from pysolovideo.hardware_control.arduino_api import SleepDepriverInterface

sdi = SleepDepriverInterface(port='/dev/ttyACM0')


for i in range(3):
    sdi.deprive(i)
