import logging
import time
from ethoscope.hardware.interfaces.interfaces import BaseInterface


class WrongSerialPortError(Exception):
    pass


class NoValidPortError(Exception):
    pass


class GearMotorSD(BaseInterface):
    _baud = 115200
    _n_channels = 10

    def __init__(self, port=None, *args, **kwargs):
        """
        TODO

        :param port: the serial port to use. Automatic detection if ``None``.
        :type port: str.
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """


        # lazy import
        import serial
        logging.info("Connecting to GMSD serial port...")

        self._serial = None
        if port is None:
            self._port = self._find_port()
        else:
            self._port = port

        self._serial = serial.Serial(self._port, self._baud, timeout=2)
        time.sleep(2)
        self._test_serial_connection()
        super(GearMotorSD, self).__init__(*args, **kwargs)

    def _find_port(self):
        from serial.tools import list_ports
        import serial
        import os
        all_port_tuples = list_ports.comports()
        logging.info("listing serial ports")
        all_ports = set()
        for ap, _, _ in all_port_tuples:
            p = os.path.basename(ap)
            print(p)
            if p.startswith("ttyUSB") or p.startswith("ttyACM"):
                all_ports |= {ap}
                logging.info("\t%s", str(ap))

        if len(all_ports) == 0:
            logging.error("No valid port detected!. Possibly, device not plugged/detected.")
            raise NoValidPortError()

        elif len(all_ports) > 2:
            logging.info("Several port detected, using first one: %s", str(all_ports))
        return all_ports.pop()

    def __del__(self):
        if self._serial is not None:
            self._serial.close()
            #

    def _test_serial_connection(self):
        return


    def move(self, channel, duration, speed):
        """
        Move a motor for a certain time at a given speed.

        :param channel: the number of the motor to be moved
        :type channel: int
        :param speed: the speed, between 0 and 100.
        :type speed: int
        :param duration: the time (ms) the stimulus should last for
        :type duration: int
        :return:
        """

        if channel < 1:
            raise Exception("idx must be greater or equal to one")

        duration = int(duration)
        speed = int(speed)
        instruction = "M %i %i %i\r" % (channel, duration, speed)
        o = self._serial.write(instruction)
        #
        return o

    def send(self, channel, duration=1000, speed=100):
        """
        The default sending paradigm is empty
        """
        self.move(channel, duration, speed)

    def _warm_up(self):
        for i in range(self._n_channels):
            self.send(i + 1)