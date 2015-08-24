__author__ = 'quentin'

from ethoscope.hardware_control.arduino_api import SleepDepriverInterface

sdi = SleepDepriverInterface()


sdi.deprive(0)
#sdi.deprive(0)

# for i in range(12,32):
#     sdi.deprive(i)
