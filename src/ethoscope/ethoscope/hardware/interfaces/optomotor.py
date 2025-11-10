import logging
import time

import serial

from ethoscope.hardware.interfaces.interfaces import SimpleSerialInterface


class WrongSerialPortError(Exception):
    pass


class NoValidPortError(Exception):
    pass


class OptoMotor(SimpleSerialInterface):
    _baud = 115200
    _n_channels = 24

    def __init__(self, port=None, *args, **kwargs):
        """
        TODO

        :param port: the serial port to use. Automatic detection if ``None``.
        :type port: str.
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """

        logging.info("Connecting to GMSD serial port...")

        self._serial = None
        if port is None:
            self._port = self._find_port()
        else:
            self._port = port

        self._serial = serial.Serial(self._port, self._baud, timeout=2)
        time.sleep(2)
        self._test_serial_connection()
        super(OptoMotor, self).__init__(*args, **kwargs)

    def activate(self, channel, duration, intensity):
        """
        Activates a component on a given channel of the PWM controller

        :param channel: the chanel idx to be activated
        :type channel: int
        :param duration: the time (ms) the stimulus should last for
        :type duration: int
        :param intensity: duty cycle, between 0 and 1000.
        :type intensity: int
        :return:
        """

        if channel < 0:
            raise Exception("chanel must be greater or equal to zero")

        duration = int(duration)
        intensity = int(intensity)
        instruction = b"P %i %i %i\r\n" % (channel, duration, intensity)
        o = self._serial.write(instruction)
        return o

    def send(self, channel, duration=10000, intensity=1000):
        self.activate(channel, duration, intensity)

    def _warm_up(self):
        """
        Send a warm-up command that will test all channels
        """
        for i in range(self._n_channels):
            self.send(i, duration=1000)
            time.sleep(1.000)  # s
