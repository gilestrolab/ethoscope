import logging
import time
from ethoscope.hardware.interfaces.interfaces import BaseInterface

class WrongSerialPortError(Exception):
    pass

class NoValidPortError(Exception):
    pass

class SimpleLynxMotionInterface(BaseInterface):

    _baud = 115200
    _min_angle_pulse = (-90.,535.)
    _max_angle_pulse = (90.,2500.)
    _n_channels = 10

    def __init__(self, port=None, *args, **kwargs):
        """
        Class to connect and abstract the SSC-32U Lynx Motion servo controller.
        It assumes a BAUD of 115200, which can be configured on the board as described in the
        `user manual (page 34) <http://www.lynxmotion.com/images/data/lynxmotion_ssc-32u_usb_user_guide.pdf>`_.

        :param port: the serial port to use. Automatic detection if ``None``.
        :type port: str.
        :param args: additional arguments
        :param kwargs: additional keyword arguments
        """
        
        """
        for testing purposes, on a machine without real USB0 connection
        one can use a virtual terminal:
            socat -d -d pty,raw,echo=0 pty,raw,echo=0
        this will create two virtual pts ports (n and n+1)
            sudo ln -s /dev/pts/n /dev/ttyUSB0
        send data to /dev/pts/n and read from /dev/pts/n+1
            cat < /dev/pts/n+1
        """
        
        #lazy import
        import serial
        logging.info("Connecting to Lynx motion serial port...")

        self._serial = None
        if port is None:
            self._port =  self._find_port()
        else:
            self._port = port

        self._serial = serial.Serial(self._port, self._baud, timeout=2)
        time.sleep(2)
        self._test_serial_connection()
        super(SimpleLynxMotionInterface, self).__init__(*args, **kwargs)


    def _find_port(self):
        from serial.tools import list_ports
        import serial
        import os
        all_port_tuples = list_ports.comports()
        logging.info("listing serial ports")
        all_ports = set()
        for ap, _, _  in all_port_tuples:
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
        return  all_ports.pop()
            # for ap in list(all_ports):
        #     logging.info("trying port %s", str(ap))
        #
        #     try:
        #         #here we use a recursive strategy to find the good port (ap).
        #         SimpleLynxMotionInterface(ap)
        #         return ap
        #     except (WrongSerialPortError, serial.SerialException):
        #         warn_str = "Tried to use port %s. Failed." % ap
        #         logging.warning(warn_str)
        #         pass


    def __del__(self):
        if self._serial is not None:
            self._serial.close()
#
    def _test_serial_connection(self):
        return

        # try:
            # If we fail to ping the port, this is a wrong port

            #self._serial.write("L\n")
#             r = self._serial.readline()
#             if not r:
#                 raise WrongSleepDepPortError
#             self.deprive(0)
#
#         except (OSError, serial.SerialException):
#             raise WrongSleepDepPortError
# #
#
#

    def _angle_to_pulse(self,angle):
        """
        Convert an angle, to a pulse, using simple linear interpolation.
        :param angle: the angle to be converted, in degrees
        :type angle: float
        :return: the pulse width
        :rtype: int

        """
        min_a, min_p = self._min_angle_pulse
        max_a, max_p = self._max_angle_pulse
        if angle > max_a:
            raise Exception("Angle too wide: %i" % angle)
        if angle < min_a:
            raise Exception("Angle too narrow: %i" % angle)
        slope = (max_p - min_p)/(max_a-min_a)
        pulse = min_p + (angle - min_a) * slope
        return pulse

    def move_to_angle(self,channel,angle=0., duration=1000):
        """
        Move a given servo to an angle in a given time.

        :param channel: the number of the servo to be moved
        :type channel: int
        :param angle: the angle (between 0 and 180) to move to
        :type angle: int
        :param time: the time it takes to go from the original angle to the new one (in ms)
        :type time: int
        :return:
        """
        if channel < 1:
            raise Exception("idx must be greater or equal to one")
        pulse = self._angle_to_pulse(angle)
        instruction = b"# %i P %i T %i\r" % (channel - 1,pulse,duration)
        o = self._serial.write(instruction)
        time.sleep(float(duration)/1000.0)
        return o

    def move_with_speed(self, channel, speed=0, duration=1000):
        """
        Move a specified continous rotation servo to a speed for a certain time.

        :param channel: the number of the servo to be moved
        :type channel: int
        :param speed: the speed, between -100 and 100. The sign indicates the rotation direction (CW or CCW)
        :type speed: int
        :param duration: the time (ms) the stimulus should last
        :type duration: int
        :return:
        """
        
        if channel < 1:
            raise Exception("idx must be greater or equal to one")
        pulse = self._speed_to_pulse(speed)
        instruction = b"# %i P %i T %i\r" % (channel - 1,pulse,duration)
        o = self._serial.write(instruction)
        time.sleep(float(duration)/1000.0)
        return o        

    def _speed_to_pulse(self, speed):
        """
        Used for FEETECH FS90R Micro Continuous Rotation Servo
        See datasheet at: https://cdn-shop.adafruit.com/product-files/2442/FS90R-V2.0_specs.pdf
        :param speed: the speed to be converted to pulse, -100 to +100
        :type angle: int
        :return: the pulse width
        :rtype: int
        """
        min_speed, max_speed = (-100, 100)
        min_pulse, mid_pulse, max_pulse = (700, 1500, 2300)
        
        if speed < min_speed or speed > max_speed:
            raise Exception("Speed value not valid: must be between %i and %i" % (min_speed, max_speed))
        
        pulse = (speed / 100.0) * (max_pulse - mid_pulse) + mid_pulse
        return int(pulse)

    def send(self, *args, **kwargs):
        """
        The default sending paradigm is empty
        """
        #raise NotImplementedError
        pass
        
    def _warm_up(self):
        """
        This will move all motors consecutively.
        Useful for testing
        """
        for i in range(1, 1 + self._n_channels):
            self.send(i)
