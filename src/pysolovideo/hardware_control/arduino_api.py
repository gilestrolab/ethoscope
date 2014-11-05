__author__ = 'quentin'

import serial
from serial.tools import list_ports

import time
import logging


class NoValidPortError(serial.SerialException):
    pass
class WrongSleepDepPortError(serial.SerialException):
    pass

class SleepDepriverInterface(object):
    _baud = 57600

    def __init__(self, port=None):
    # def __init__(self, port="/dev/ttyACM0"):
        self._serial = None

        if port is None:
            self._port =  self._find_port()
        else:
            self._port = port

        self._serial = serial.Serial(self._port, self._baud, timeout=2)
        time.sleep(2)

        self._test_serial_connection()

    def _find_port(self):
        all_ports = list_ports.comports()

        for ap, _, _  in all_ports:
            try:
                SleepDepriverInterface(ap)
                return ap
            except (WrongSleepDepPortError, serial.SerialException):
                pass
        raise NoValidPortError()

    def __del__(self):
        if self._serial is not None:
            self._serial.close()

    def _test_serial_connection(self):

        try:
            # If we fail to ping the port, this is a wrong port
            print "boo"
            self._serial.write("L\n")

            r = self._serial.readline()
            print "bam"
            if not r:
                raise WrongSleepDepPortError
            self.deprive(0)

        except (OSError, serial.SerialException):
            raise WrongSleepDepPortError


    def deprive(self, channel):
        cmd = "M %i\n" % (channel + 1)
        self._serial.write(cmd)
        logging.info("Sending command to SD: %s" % cmd)
